"""chat.py — Métodos de chat y streaming de VToolLlama."""

from __future__ import annotations

from typing import Any, Generator, Optional

from .base import VToolLlama
from ..exceptions import EmptyPromptError, InferenceError, ModelNotLoadedError
from ..tools import (
    INTERNAL_TOOLS,
    SCENE_SYSTEM_COMMAND,
    StreamPostProcessor,
    execute_text_tool,
)

VToolLlama._scene_requested = False


def add_tool_message(self: VToolLlama, content: str, tool_call_id: str) -> None:
    with self._lock:
        self._memory.add_tool_message(content, tool_call_id)

VToolLlama.add_tool_message = add_tool_message


def _reconstruct_tool_calls(self: VToolLlama, chunks: list[list[dict]]) -> list[dict]:
    tool_calls_map = {}
    for chunk in chunks:
        for tc in chunk:
            idx = tc.get("index", 0)
            if idx not in tool_calls_map:
                tool_calls_map[idx] = {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {"name": "", "arguments": ""}
                }
            if "id" in tc and tc["id"]:
                tool_calls_map[idx]["id"] = tc["id"]
            if "function" in tc:
                fn = tc["function"]
                if "name" in fn and fn["name"]:
                    tool_calls_map[idx]["function"]["name"] += fn["name"]
                if "arguments" in fn and fn["arguments"]:
                    tool_calls_map[idx]["function"]["arguments"] += fn["arguments"]
    return list(tool_calls_map.values())

VToolLlama._reconstruct_tool_calls = _reconstruct_tool_calls


def _validate_tool_calls(
    self: VToolLlama,
    tool_calls: list[dict],
    tools: list[dict],
) -> list[dict]:
    valid_names = set()
    for tool in tools:
        if "function" in tool:
            valid_names.add(tool["function"].get("name", ""))

    validated = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        fn_name = fn.get("name", "")
        if fn_name in valid_names:
            validated.append(tc)
        else:
            self._log_warning(
                f"Tool call '{fn_name}' no existe en las herramientas "
                f"definidas. Ignorando (posible alucinación del modelo)."
            )

    return validated if validated else None

VToolLlama._validate_tool_calls = _validate_tool_calls


def _inject_soul_context_into_messages(
    self: VToolLlama, messages: list[dict], user_prompt: str
) -> list[dict]:
    soul = getattr(self._character_manager, '_soul_accessor', None)
    if not soul or not soul.is_active:
        return messages
    if not messages:
        return messages

    context = soul.retrieve_context(user_prompt, top_k=3)
    if not context:
        return messages

    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            messages[i] = dict(messages[i])
            messages[i]["content"] = (
                messages[i]["content"].rstrip()
                + "\n\n" + context
            )
            break
    return messages

VToolLlama._inject_soul_context_into_messages = _inject_soul_context_into_messages


def _inject_chat_memory_into_messages(
    self: VToolLlama, messages: list[dict], user_prompt: str
) -> list[dict]:
    if not self._character_manager:
        return messages

    limit = getattr(self._config, "chat_memory_retrieval_limit", 3)
    if limit <= 0:
        return messages

    relevant_turns = self._character_manager.retrieve_relevant_chat(user_prompt, top_k=limit)
    if not relevant_turns:
        return messages

    relevant_turns = [t for t in relevant_turns if t.get("similarity", 0) > 0.35]
    if not relevant_turns:
        return messages

    context_lines = []
    for t in relevant_turns:
        doc = t.get("document", "")
        if doc:
            context_lines.append(f"[{t.get('metadata', {}).get('timestamp', 'Pasado')}] {doc}")

    if context_lines:
        context_str = "\n".join(context_lines)
        injection = f"\n\n[CONTEXTO: Recuerdos de conversaciones pasadas que podrían ser relevantes para responder ahora:]\n{context_str}\n"

        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                messages[i] = dict(messages[i])
                messages[i]["content"] += injection
                self._log_info(f"🧠 [ChatMemory] Se inyectaron {len(context_lines)} turnos pasados al contexto.")
                break

    return messages

VToolLlama._inject_chat_memory_into_messages = _inject_chat_memory_into_messages


def _apply_emotional_trigger(self: VToolLlama, prompt: str) -> None:
    psych_mgr = getattr(self._character_manager, '_psychology_manager', None)
    if not psych_mgr:
        return
    try:
        psych_mgr.apply_emotional_trigger(prompt)
        psych_mgr.synthesize_persona()
    except Exception:
        pass

VToolLlama._apply_emotional_trigger = _apply_emotional_trigger


def _feed_response_to_drift_detector(self: VToolLlama, response_text: str) -> None:
    psych_mgr = getattr(self._character_manager, '_psychology_manager', None)
    if not psych_mgr or not psych_mgr.persona:
        return
    try:
        from ..psychology import DriftDetector
        if not hasattr(self, '_drift_detector'):
            self._drift_detector = DriftDetector()
        drift = self._drift_detector.feed(response_text, psych_mgr.persona)
        if drift:
            self._log_debug("PSY", f"Drift detected: {drift.reason}")
            recent = [{"response": response_text}]
            psych_mgr.tick(recent_interactions=recent)
            self._character_manager.save_psychology_state()
    except Exception:
        pass

VToolLlama._feed_response_to_drift_detector = _feed_response_to_drift_detector


def _psychology_tick(self: VToolLlama) -> None:
    psych_mgr = getattr(self._character_manager, '_psychology_manager', None)
    if not psych_mgr:
        return
    try:
        recent_hist = []
        for m in self._memory.messages[-6:]:
            if m.content and m.role in ("user", "assistant"):
                recent_hist.append({"response": m.content})
        psych_mgr.tick(recent_interactions=recent_hist)
    except Exception:
        pass

VToolLlama._psychology_tick = _psychology_tick


def _on_stream_tool_detected(self: VToolLlama, fn_name: str, fn_args: dict) -> None:
    if fn_name in ("store_long_term_memory", "remember_memory"):
        execute_text_tool(
            fn_name, fn_args,
            add_memory_fn=self._character_manager.add_memory,
            log_fn=self._log_info,
        )
    elif fn_name in ("get_scene_state", "describe_scene"):
        self._log_debug("TOOL", "Scene state solicitada via stream interceptor")
        self._scene_requested = True

VToolLlama._on_stream_tool_detected = _on_stream_tool_detected


def chat(
    self: VToolLlama,
    prompt: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    repeat_penalty: Optional[float] = None,
    tools: Optional[list[dict]] = None,
    tool_choice: Optional[Any] = None,
) -> Any:
    self._validate_prompt(prompt)

    internal_tools = list(INTERNAL_TOOLS)
    active_tools = (tools or []) + internal_tools

    scene_prompt = SCENE_SYSTEM_COMMAND
    if prompt.strip().lower() == "/scene_view":
        prompt = scene_prompt
        slash_result = None
    else:
        slash_result = self._handle_slash_command(prompt)

    if slash_result is not None:
        return slash_result

    mem_prefix = "#mem "
    system_injection = ""
    if prompt.strip().startswith(mem_prefix):
        mem_content = prompt.strip()[len(mem_prefix):].strip()
        if mem_content:
            self._character_manager.add_memory(
                content=mem_content, always_include=True, priority=1.0,
            )
            self._log_info(f"🧠 [#mem] Memoria guardada: {mem_content}")
            system_injection = f"\n\n[SYSTEM: El usuario acaba de guardar un recuerdo: '{mem_content}'. Confirma brevemente en character que lo has recordado, sin mencionar herramientas ni sistemas.]"

    with self._lock:
        self._short_memory.append({"role": "user", "content": prompt})

        self._memory.add_user_message(prompt)
        self._auto_trim_if_needed()

        self._inject_personality_into_system_prompt()
        self._apply_emotional_trigger(prompt)

        loop_count = 0
        MAX_LOOPS = 3
        memory_saved = False

        while loop_count < MAX_LOOPS:
            loop_count += 1
            messages = self._memory.get_context_messages()

            if loop_count == 1:
                self._inject_soul_context_into_messages(messages, prompt)
                self._inject_chat_memory_into_messages(messages, prompt)

            if system_injection and loop_count == 1:
                if messages and messages[-1].get("role") == "user":
                    messages[-1] = dict(messages[-1])
                    messages[-1]["content"] += system_injection

            self._stats.begin_generation()

            try:
                result = self._model_manager.generate(
                    messages=messages,
                    stream=False,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repeat_penalty=repeat_penalty,
                    tools=active_tools,
                    tool_choice=tool_choice,
                )

                msg_choice = result["choices"][0]["message"]
                response_text = msg_choice.get("content") or ""
                tool_calls = msg_choice.get("tool_calls", None)

                self._record_stats(result)

                handled = self._tool_manager.handle_structured_calls(
                    tool_calls or [],
                    scene_prompt,
                    tools,
                )
                if handled["internal_found"]:
                    for tc in (tool_calls or []):
                        fn_name = tc.get("function", {}).get("name", "")
                        if fn_name in ("store_long_term_memory", "remember_memory"):
                            self._memory.add_assistant_message(content=None, tool_calls=[tc])
                            self._memory.add_tool_message(
                                content="Memoria guardada. Ahora respondele al usuario.",
                                tool_call_id=tc.get("id", ""),
                            )
                        elif fn_name in ("get_scene_state", "describe_scene"):
                            self._memory.add_assistant_message(content=None, tool_calls=[tc])
                            self._memory.add_tool_message(
                                content=scene_prompt,
                                tool_call_id=tc.get("id", ""),
                            )
                    if handled["memory_saved"]:
                        memory_saved = True
                    continue

                if handled["external_calls"]:
                    self._memory.add_assistant_message(content=response_text, tool_calls=handled["external_calls"])
                    self._short_memory.append({"role": "assistant", "content": "(Llama a herramienta externa)"})
                    return msg_choice

                if not tool_calls and not memory_saved:
                    text_handled = self._tool_manager.handle_text_calls(
                        response_text,
                        scene_prompt,
                        tools,
                    )
                    if text_handled["internal_found"]:
                        response_text = text_handled["cleaned_text"]
                        if text_handled["memory_saved"]:
                            memory_saved = True
                        continue
                    if text_handled["external_calls"]:
                        self._memory.add_assistant_message(content=response_text, tool_calls=text_handled["external_calls"])
                        self._short_memory.append({"role": "assistant", "content": "(Llama a herramienta externa)"})
                        return msg_choice

                if self._tool_manager.needs_tool_coercion(prompt, response_text, bool(tool_calls), False):
                    coercion = self._tool_manager.build_coercion_prompt(prompt)
                    if coercion:
                        self._log_debug("TOOL", f"Coercion retry: {coercion[:60]}...")
                        coerce_result = self._model_manager.generate(
                            messages=messages + [{"role": "user", "content": coercion}],
                            stream=False,
                            max_tokens=100,
                            temperature=0.2,
                            top_p=0.9,
                            tools=active_tools,
                            tool_choice="auto",
                        )
                        coerce_choice = coerce_result["choices"][0]["message"]
                        coerce_tools = coerce_choice.get("tool_calls", None)
                        if coerce_tools:
                            result = coerce_result
                            msg_choice = coerce_choice
                            response_text = coerce_choice.get("content") or ""
                            tool_calls = coerce_tools
                            continue

                if memory_saved:
                    char_name = self._character_manager.character_name.capitalize() if self._character_manager.character_name else "El personaje"
                    response_text = f"** {char_name} recordará esto **\n\n" + response_text

                self._feed_response_to_drift_detector(response_text)

                self._memory.add_assistant_message(content=response_text, tool_calls=None)
                self._short_memory.append({"role": "assistant", "content": response_text})
                self._log_generation_stats()

                if response_text:
                    self._character_manager.save_chat_turn(prompt, response_text)

                return response_text

            except ModelNotLoadedError:
                raise
            except Exception as e:
                raise InferenceError(f"Error en chat(): {e}") from e

    return "Error: Excedido el límite máximo de razonamiento interno."

VToolLlama.chat = chat


def stream_chat(
    self: VToolLlama,
    prompt: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    repeat_penalty: Optional[float] = None,
    tools: Optional[list[dict]] = None,
    tool_choice: Optional[Any] = None,
) -> Generator[Any, None, None]:
    self._validate_prompt(prompt)

    scene_prompt = SCENE_SYSTEM_COMMAND

    if prompt.strip().lower() == "/scene_view":
        prompt = scene_prompt
        slash_result = None
    else:
        slash_result = self._handle_slash_command(prompt)

    if slash_result is not None:
        yield slash_result
        return

    mem_prefix = "#mem "
    system_injection = ""
    if prompt.strip().startswith(mem_prefix):
        mem_content = prompt.strip()[len(mem_prefix):].strip()
        if mem_content:
            self._character_manager.add_memory(
                content=mem_content, always_include=True, priority=1.0,
            )
            self._log_info(f"🧠 [#mem] Memoria guardada: {mem_content}")
            system_injection = f"\n\n[SYSTEM: El usuario acaba de guardar un recuerdo: '{mem_content}'. Confirma brevemente en character que lo has recordado, sin mencionar herramientas ni sistemas.]"

    internal_tools = list(INTERNAL_TOOLS)
    active_tools = (tools or []) + internal_tools

    self._check_and_rebuild_if_needed()

    with self._lock:
        self._short_memory.append({"role": "user", "content": prompt})
        self._memory.add_user_message(prompt)
        self._auto_trim_if_needed()
        self._inject_personality_into_system_prompt()

        loop_count = 0
        MAX_LOOPS = 3

        while loop_count < MAX_LOOPS:
            loop_count += 1
            messages = self._memory.get_context_messages()

            if loop_count == 1:
                self._inject_soul_context_into_messages(messages, prompt)
                self._inject_chat_memory_into_messages(messages, prompt)

            if system_injection and loop_count == 1:
                if messages and messages[-1].get("role") == "user":
                    messages[-1] = dict(messages[-1])
                    messages[-1]["content"] += system_injection

            self._stats.begin_generation()

            try:
                stream = self._model_manager.generate(
                    messages=messages,
                    stream=True,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repeat_penalty=repeat_penalty,
                    tools=active_tools,
                    tool_choice=tool_choice,
                )

                full_response = ""
                tool_calls_chunks = []

                stream_pp = StreamPostProcessor(
                    on_tool_executed=self._on_stream_tool_detected,
                    log_fn=self._log_info,
                )

                for chunk in stream:
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    if "tool_calls" in delta and delta["tool_calls"]:
                        tool_calls_chunks.append(delta["tool_calls"])
                    else:
                        for event in stream_pp.feed(delta):
                            if event["type"] == "text":
                                full_response += event["content"]
                                yield event["content"]
                            elif event["type"] == "tool_executed":
                                pass

                for event in stream_pp.flush():
                    if event["type"] == "text":
                        full_response += event["content"]
                        yield event["content"]

                final_tool_calls = None
                if tool_calls_chunks:
                    final_tool_calls = self._reconstruct_tool_calls(tool_calls_chunks)

                self._record_stats_from_stream(stream, full_response)

                handled = self._tool_manager.handle_structured_calls(
                    final_tool_calls or [],
                    scene_prompt,
                    tools,
                )
                if handled["internal_found"]:
                    for tc in (final_tool_calls or []):
                        fn_name = tc.get("function", {}).get("name", "")
                        if fn_name in ("store_long_term_memory", "remember_memory"):
                            char_name = self._character_manager.character_name.capitalize() if self._character_manager.character_name else "El personaje"
                            yield f"\n** {char_name} recordará esto **\n\n"
                            self._memory.add_assistant_message(content=None, tool_calls=[tc])
                            self._memory.add_tool_message(content="Memoria guardada. Continua tu respuesta.", tool_call_id=tc.get("id", ""))
                        elif fn_name in ("get_scene_state", "describe_scene"):
                            self._memory.add_assistant_message(content=None, tool_calls=[tc])
                            self._memory.add_tool_message(
                                content=scene_prompt,
                                tool_call_id=tc.get("id", ""),
                            )
                    continue

                if handled["external_calls"]:
                    self._memory.add_assistant_message(content=full_response or None, tool_calls=handled["external_calls"])
                    yield {"choices": [{"message": {"tool_calls": handled["external_calls"]}}]}
                    return

                if self._scene_requested:
                    self._scene_requested = False
                    self._memory.add_assistant_message(content=None)
                    self._memory.add_tool_message(
                        content=scene_prompt,
                        tool_call_id="scene_stream",
                    )
                    continue

                if not final_tool_calls:
                    text_handled = self._tool_manager.handle_text_calls(
                        full_response,
                        scene_prompt,
                        tools,
                    )
                    if text_handled["memory_saved"]:
                        char_name = self._character_manager.character_name.capitalize() if self._character_manager.character_name else "El personaje"
                        yield f"\n** {char_name} recordará esto **\n\n"
                    full_response = text_handled["cleaned_text"]

                    if text_handled["external_calls"]:
                        self._memory.add_assistant_message(content=None, tool_calls=text_handled["external_calls"])
                        yield {"choices": [{"message": {"tool_calls": text_handled["external_calls"]}}]}
                        return

                self._memory.add_assistant_message(content=full_response or None, tool_calls=None)
                if full_response:
                    self._short_memory.append({"role": "assistant", "content": full_response})
                    self._character_manager.save_chat_turn(prompt, full_response)

                self._log_generation_stats()
                return

            except ModelNotLoadedError:
                raise
            except Exception as e:
                raise InferenceError(f"Error en stream_chat(): {e}") from e

VToolLlama.stream_chat = stream_chat


def chat_with_thinking(
    self: VToolLlama,
    prompt: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    repeat_penalty: Optional[float] = None,
) -> tuple[str, str]:
    self._validate_prompt(prompt)

    with self._lock:
        self._memory.add_user_message(prompt)
        self._auto_trim_if_needed()
        messages = self._memory.get_context_messages()
        self._stats.begin_generation()

        try:
            result = self._model_manager.generate(
                messages=messages,
                stream=False,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repeat_penalty=repeat_penalty,
            )

            msg_choice = result["choices"][0]["message"]
            thinking = msg_choice.get("reasoning_content") or ""
            content = msg_choice.get("content") or ""

            self._record_stats(result)

            if not thinking and "<think>" in content:
                parts = content.split("</think>", 1)
                thinking = parts[0].replace("<think>", "").strip()
                content = parts[1].strip() if len(parts) > 1 else ""

            full_history_content = content
            if thinking:
                full_history_content = f"<think>\n{thinking}\n</think>\n{content}"

            self._memory.add_assistant_message(full_history_content)
            self._log_generation_stats()

            return thinking, content

        except ModelNotLoadedError:
            raise
        except Exception as e:
            raise InferenceError(f"Error en chat_with_thinking(): {e}") from e

VToolLlama.chat_with_thinking = chat_with_thinking


def stream_chat_with_thinking(
    self: VToolLlama,
    prompt: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    repeat_penalty: Optional[float] = None,
) -> Generator[tuple[str, str], None, None]:
    self._validate_prompt(prompt)

    with self._lock:
        self._memory.add_user_message(prompt)
        self._auto_trim_if_needed()
        messages = self._memory.get_context_messages()
        self._stats.begin_generation()

        try:
            stream = self._model_manager.generate(
                messages=messages,
                stream=True,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repeat_penalty=repeat_penalty,
            )

            full_response = ""
            mode = "content"
            buffer = ""

            for chunk in stream:
                thinking_token, content_token = self._extract_token_from_chunk(chunk)

                if thinking_token:
                    full_response += thinking_token
                    yield ("thinking", thinking_token)
                    continue

                if not content_token:
                    continue

                full_response += content_token
                buffer += content_token

                while True:
                    if mode == "content":
                        idx = buffer.find("<think>")
                        if idx == -1:
                            open_tag_candidate = buffer.rfind("<")
                            if open_tag_candidate != -1 and "<think>".startswith(buffer[open_tag_candidate:]):
                                before = buffer[:open_tag_candidate]
                                if before:
                                    yield ("content", before)
                                buffer = buffer[open_tag_candidate:]
                            else:
                                yield ("content", buffer)
                                buffer = ""
                            break

                        before = buffer[:idx]
                        if before:
                            yield ("content", before)
                        buffer = buffer[idx + 7:]
                        mode = "thinking"

                    elif mode == "thinking":
                        idx = buffer.find("</think>")
                        if idx == -1:
                            close_tag_candidate = buffer.rfind("<")
                            if close_tag_candidate != -1 and "</think>".startswith(buffer[close_tag_candidate:]):
                                before = buffer[:close_tag_candidate]
                                if before:
                                    yield ("thinking", before)
                                buffer = buffer[close_tag_candidate:]
                            else:
                                yield ("thinking", buffer)
                                buffer = ""
                            break

                        thought = buffer[:idx]
                        if thought:
                            yield ("thinking", thought)
                        buffer = buffer[idx + 8:]
                        mode = "content"

            if buffer:
                if mode == "thinking":
                    yield ("thinking", buffer)
                else:
                    yield ("content", buffer)

            self._record_stats_from_stream(stream, full_response)
            self._memory.add_assistant_message(full_response)
            self._log_generation_stats()

        except ModelNotLoadedError:
            raise
        except Exception as e:
            raise InferenceError(f"Error en stream_chat_with_thinking(): {e}") from e

VToolLlama.stream_chat_with_thinking = stream_chat_with_thinking
