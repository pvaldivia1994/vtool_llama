"""chat.py — Métodos de chat y streaming de VToolLlama."""

from __future__ import annotations

from typing import Any, Generator, Optional

from .base import VToolLlama
from ..exceptions import InferenceError, ModelNotLoadedError
from ..tools import (
    StreamPostProcessor,
    TOOL_USAGE_POLICY,
    execute_text_tool,
    get_active_internal_tools,
)


def _get_inference_messages(self: VToolLlama) -> list[dict]:
    """Retorna los mensajes para inferencia con tags correctos (v15).

    - Usa self._user_tag en vez de [USER] hardcodeado
    - Detecta multi-personaje: [ROBERTO] texto → [ROBERTO][SPEAK]
    - Salta mensajes ya pre-tagueados por InlineProcessor
    """
    import re
    messages = self._memory.get_context_messages()
    tag = self._user_tag.upper() if self._user_tag else "PLAYER"

    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not content:
            continue

        # Ya pre-tagueado por InlineProcessor (ej: [PLAYER][SPEAK] Hola)
        if re.match(r'^\[\w+\]\[(?:SPEAK|ACT|THOUGHT)\]', content):
            continue

        # [CONTINUE] es un marcador especial, no un mensaje del jugador
        if content.strip() == "[CONTINUE]":
            continue

        # Multi-personaje: [ROBERTO] texto → [ROBERTO][SPEAK] texto
        m = re.match(r'^\[(\w+)\]\s+(.*)', content)
        if m and m.group(1).isupper() and len(m.group(1)) <= 12:
            msg["content"] = f"[{m.group(1)}][SPEAK] {m.group(2)}"
            msg["speaker_tag"] = m.group(1)
            continue

        # Sin tag → asignar el tag del usuario
        msg["content"] = f"[{tag}][SPEAK] {content}"

    return messages

VToolLlama._get_inference_messages = _get_inference_messages


def _inject_tool_policy_if_needed(
    self: VToolLlama,
    messages: list[dict],
    user_prompt: str,
) -> None:
    """Inyecta TOOL_USAGE_POLICY como mensaje system antes del último user.

    NO modifica el system_prompt estable del core (v6).
    Solo agrega la política si hay tools internas activas para este turno.
    """
    if not self._character_manager.is_loaded:
        return
    active = get_active_internal_tools(user_prompt, self._config)
    if not active:
        return

    policy_msg = {"role": "system", "content": TOOL_USAGE_POLICY}
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            messages.insert(i, policy_msg)
            return
    messages.append(policy_msg)

VToolLlama._inject_tool_policy_if_needed = _inject_tool_policy_if_needed


def _log_debug_turn(self: VToolLlama, prompt: str, messages: list[dict],
                     response: str = "") -> None:
    """Helper para debug logging en chat/stream/thinking."""
    deb = getattr(self, "_debug_logger", None)
    if not deb or not deb._enabled:
        return
    try:
        deb.log_turn_start(prompt)
        deb.log_messages_sent_to_model(messages)
        if response:
            deb.log_model_response(response)
            deb.log_context_info(self.get_token_usage())
    except Exception:
        pass

VToolLlama._log_debug_turn = _log_debug_turn


def _split_tagged_response(self: VToolLlama, text: str, speaker: str = "") -> str:
    """Post-procesa la respuesta separando [ACT] + dialogo en lineas (v13)."""
    import re
    if not speaker:
        speaker = self._character_manager.character_name.upper() if self._character_manager.is_loaded else "AGENT"
    lines = text.split("\n")
    result = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # [ID][ACT] *accion* texto_extra
        m = re.match(r'^\[(\w+)\]\[ACT\]\s+(\*[^*]+\*)\s*(.*)', line)
        if m:
            sp = m.group(1)
            result.append(f"[{sp}][ACT] {m.group(2).strip()}")
            extra = m.group(3).strip()
            if extra:
                result.append(f"[{sp}][SPEAK] {extra}" if not extra.startswith("*") else f"[{sp}][ACT] {extra}")
            continue
        # [ID][SPEAK] con asteriscos al inicio
        m = re.match(r'^\[(\w+)\]\[SPEAK\]\s+(\*[^*]+\*)\s*(.*)', line)
        if m:
            sp = m.group(1)
            result.append(f"[{sp}][ACT] {m.group(2).strip()}")
            extra = m.group(3).strip()
            if extra:
                result.append(f"[{sp}][SPEAK] {extra}")
            continue
        result.append(line)
    return "\n".join(result)

VToolLlama._split_tagged_response = _split_tagged_response


def _extract_inline_context(self: VToolLlama, prompt: str) -> str:
    """Extrae contexto inline legacy del prompt.

    [context <tipo> <texto>]  → legacy, tipo explícito
    [TEXTO LARGO]             → shortcut scene
    (TEXTO LARGO)             → shortcut time
    """
    import re
    from ..orquestador import CONTEXT_TYPES, ContextInjector

    if not self._chat_store or not self._memory._conversation_id:
        return prompt

    injector = ContextInjector(
        self._chat_store, self._memory._conversation_id, self._memory._branch_id
    )
    cleaned = prompt

    # Legacy: [context tipo texto]
    for match in re.finditer(r'\[context\s+(\w+)\s+(.*?)\]', prompt, re.IGNORECASE):
        ctx_type = match.group(1).lower()
        content = match.group(2).strip()
        if ctx_type in CONTEXT_TYPES and content:
            injector.add(ctx_type, content)
            self._log_debug("CTX", f"[context {ctx_type}]: {content[:50]}")
        cleaned = cleaned.replace(match.group(0), "", 1)

    # [TEXTO LARGO] → scene (multi-word, 2+ palabras)
    for match in re.finditer(r'\[(\w+(?:\s+\w+)+[^\]]*?)\]', cleaned):
        content = match.group(1).strip()
        if content:
            injector.add("scene", content)
            self._log_debug("CTX", f"[scene]: {content[:50]}")
        cleaned = cleaned.replace(match.group(0), "", 1)

    # (TEXTO LARGO) → time (multi-word, 2+ palabras)
    for match in re.finditer(r'\((\w+(?:\s+\w+)+[^)]*?)\)', cleaned):
        content = match.group(1).strip()
        if content:
            injector.add("time", content)
            self._log_debug("CTX", f"(time): {content[:50]}")
        cleaned = cleaned.replace(match.group(0), "", 1)

    return cleaned.strip()

VToolLlama._extract_inline_context = _extract_inline_context


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

    # v15: inyectar en CADA user message (soporta multi-segmento)
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            messages[i] = dict(messages[i])
            messages[i]["content"] = (
                messages[i]["content"].rstrip()
                + "\n\n" + context
            )
    return messages

VToolLlama._inject_soul_context_into_messages = _inject_soul_context_into_messages


def _inject_dynamic_state_into_messages(self: VToolLlama, messages: list[dict]) -> list[dict]:
    # v10: desactivado por defecto (inject_dynamic_state: false)
    if not getattr(self._config, "inject_dynamic_state", False):
        return messages
    if not self._character_manager.is_loaded:
        return messages

    dynamic_prompt = self._character_manager.build_dynamic_prompt()
    if not dynamic_prompt.strip():
        return messages

    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            # v10: el header ahora usa el tag del orquestador
            messages.insert(i, {"role": "system", "content": dynamic_prompt})
            break
    else:
        messages.append({"role": "system", "content": dynamic_prompt})

    return messages

VToolLlama._inject_dynamic_state_into_messages = _inject_dynamic_state_into_messages


def _inject_chat_memory_into_messages(
    self: VToolLlama, messages: list[dict], user_prompt: str
) -> list[dict]:
    """Deprecado — el ContextBuilder maneja la recuperación de contexto."""
    return messages

VToolLlama._inject_chat_memory_into_messages = _inject_chat_memory_into_messages


def _inject_scene_context(self: VToolLlama, messages: list[dict]) -> list[dict]:
    """Si inject_scene_context está activo, genera una descripción de escena
    basada en los últimos mensajes y la inyecta como contexto system."""
    if not self._config.inject_scene_context or not self._chat_store:
        return messages

    history = self.get_chat_history(limit=10)
    if not history:
        return messages

    lines = []
    for msg in history:
        if msg["role"] == "user":
            lines.append(f"Usuario: {msg['content']}")
        elif msg["role"] == "assistant":
            name = self._character_manager.character_name or "Personaje"
            lines.append(f"{name}: {msg['content']}")
    conversation = "\n".join(lines)

    try:
        result = self._model_manager.generate(
            messages=[{
                "role": "user",
                "content": (
                    "Resumí en 2-3 oraciones la escena actual según esta "
                    "conversación. Solo los hechos, sin florituras.\n\n"
                    f"{conversation}"
                ),
            }],
            stream=False, max_tokens=200, temperature=0.3,
        )
        scene = result["choices"][0]["message"].get("content", "").strip()
        if scene:
            self._log_debug("SCENE", f"Contexto de escena inyectado: {scene[:60]}...")
            messages.append({"role": "system", "content": f"[ESCENA ACTUAL] {scene}"})
    except Exception:
        pass

    return messages

VToolLlama._inject_scene_context = _inject_scene_context


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
    execute_text_tool(
        fn_name, fn_args,
        add_memory_fn=self._character_manager.add_memory,
        log_fn=self._log_info,
    )

VToolLlama._on_stream_tool_detected = _on_stream_tool_detected


VToolLlama._inject_char_thoughts = lambda self, messages: None


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
    if self._loading:
        raise RuntimeError(
            "El personaje se está cargando. Esperá a que termine antes de chatear."
        )
    self._validate_prompt(prompt)

    internal_tools = get_active_internal_tools(prompt, self._config)
    active_tools = (tools or []) + internal_tools

    # Paso 1: Extraer context inline legacy [context tipo texto] + [texto] scene
    prompt = self._extract_inline_context(prompt)

    # Paso 2: Slash commands
    slash_result = self._handle_slash_command(prompt)
    scene_prompt = ""
    if slash_result is not None:
        return slash_result

    # Paso 3: Procesar inline commands (#, [], :, *)
    original_prompt = prompt
    inline_messages: list[dict] = []
    had_inline = False
    if self._inline_processor and self._inline_processor.has_inline_commands(prompt):
        had_inline = True
        inline_messages = self._inline_processor.process(prompt, self)

    # Si todo el contenido fue consumido por comandos inline
    # (ej: solo [SCENE], solo (time), o combinaciones sin texto restante)
    if had_inline and not inline_messages:
        prompt = "[CONTINUE]"
        original_prompt = "[CONTINUE]"

    with self._lock:
        tag = self._user_tag.upper() if self._user_tag else "PLAYER"

        if inline_messages:
            for msg in inline_messages:
                tagged = f"[{tag}][{msg['tag']}] {msg['content']}"
                self._short_memory.append({"role": "user", "content": tagged})
                self._memory.add_user_message(
                    tagged, speaker_tag=tag,
                )
        else:
            # Mensaje normal sin comandos inline
            self._short_memory.append({"role": "user", "content": prompt})
            self._memory.add_user_message(prompt)

        self._auto_trim_if_needed()

        # Emotional trigger sobre el texto ORIGINAL combinado (v15)
        self._apply_emotional_trigger(original_prompt)

        loop_count = 0
        MAX_LOOPS = 3
        memory_saved = False
        skip_generation = False

        while loop_count < MAX_LOOPS:
            loop_count += 1
            messages = self._get_inference_messages()

            if loop_count == 1:
                self._inject_soul_context_into_messages(messages, original_prompt)
                self._inject_dynamic_state_into_messages(messages)
                self._inject_tool_policy_if_needed(messages, original_prompt)

            try:
                if not skip_generation:
                    self._stats.begin_generation()
                    result = self._model_manager.generate(
                        messages=messages,
                        stream=False,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        top_k=top_k,
                        repeat_penalty=repeat_penalty,
                        tools=active_tools or None,
                        tool_choice=tool_choice,
                    )

                    msg_choice = result["choices"][0]["message"]
                    response_text = msg_choice.get("content") or ""
                    tool_calls = msg_choice.get("tool_calls", None)

                    self._log_debug_turn(original_prompt, messages, response_text)
                    self._record_stats(result)
                else:
                    skip_generation = False

                handled = self._tool_manager.handle_structured_calls(
                    tool_calls or [],
                    scene_prompt,
                    tools,
                )
                if handled["internal_found"]:
                    for tc in (tool_calls or []):
                        fn_name = tc.get("function", {}).get("name", "")
                        if fn_name == "store_long_term_memory":
                            self._memory.add_assistant_message(content=None, tool_calls=[tc])
                            self._memory.add_tool_message(
                                content="Memoria guardada. Ahora respondele al usuario.",
                                tool_call_id=tc.get("id", ""),
                            )
                    if handled["memory_saved"]:
                        memory_saved = True
                    continue

                if handled["external_calls"]:
                    self._memory.add_assistant_message(content=response_text, tool_calls=handled["external_calls"])
                    self._short_memory.append({"role": "assistant", "content": "(Llama a herramienta externa)"})
                    return msg_choice

                if not tool_calls and not memory_saved and self._config.enable_text_tool_fallback:
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

                if self._tool_manager.needs_tool_coercion(original_prompt, response_text, bool(tool_calls), False):
                    coercion = self._tool_manager.build_coercion_prompt(original_prompt)
                    if coercion:
                        self._log_debug("TOOL", f"Coercion retry: {coercion[:60]}...")
                        coerce_result = self._model_manager.generate(
                            messages=messages + [{"role": "user", "content": coercion}],
                            stream=False,
                            max_tokens=100,
                            temperature=0.2,
                            top_p=0.9,
                            tools=active_tools or None,
                            tool_choice="auto",
                        )
                        coerce_choice = coerce_result["choices"][0]["message"]
                        coerce_tools = coerce_choice.get("tool_calls", None)
                        if coerce_tools:
                            result = coerce_result
                            msg_choice = coerce_choice
                            response_text = coerce_choice.get("content") or ""
                            tool_calls = coerce_tools
                            skip_generation = True
                            continue

                if memory_saved:
                    char_name = self._character_manager.character_name.capitalize() if self._character_manager.character_name else "El personaje"
                    response_text = f"** {char_name} recordará esto **\n\n" + response_text

                self._feed_response_to_drift_detector(response_text)

                self._memory.add_assistant_message(content=self._split_tagged_response(response_text), tool_calls=None)
                self._short_memory.append({"role": "assistant", "content": response_text})
                self._log_generation_stats()

                # Marcar contexto como entregado
                try:
                    from ..orquestador import ContextInjector
                    if self._chat_store and self._memory._conversation_id:
                        inj = ContextInjector(self._chat_store, self._memory._conversation_id, self._memory._branch_id)
                        active = inj.list(only_active=True)
                        if active:
                            inj.mark_delivered([e.id for e in active])
                except Exception:
                    pass

                self._auto_index_if_needed()
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
    if self._loading:
        raise RuntimeError(
            "El personaje se está cargando. Esperá a que termine antes de chatear."
        )
    self._validate_prompt(prompt)

    prompt = self._extract_inline_context(prompt)

    slash_result = self._handle_slash_command(prompt)
    scene_prompt = ""
    if slash_result is not None:
        yield slash_result
        return

    original_prompt = prompt
    inline_messages: list[dict] = []
    had_inline = False
    if self._inline_processor and self._inline_processor.has_inline_commands(prompt):
        had_inline = True
        inline_messages = self._inline_processor.process(prompt, self)

    if had_inline and not inline_messages:
        prompt = "[CONTINUE]"
        original_prompt = "[CONTINUE]"

    internal_tools = get_active_internal_tools(original_prompt, self._config)
    active_tools = (tools or []) + internal_tools

    self._check_and_rebuild_if_needed()

    with self._lock:
        tag = self._user_tag.upper() if self._user_tag else "PLAYER"

        if inline_messages:
            for msg in inline_messages:
                tagged = f"[{tag}][{msg['tag']}] {msg['content']}"
                self._short_memory.append({"role": "user", "content": tagged})
                self._memory.add_user_message(tagged, speaker_tag=tag)
        else:
            self._short_memory.append({"role": "user", "content": prompt})
            self._memory.add_user_message(prompt)

        self._auto_trim_if_needed()
        self._apply_emotional_trigger(original_prompt)

        loop_count = 0
        MAX_LOOPS = 3

        while loop_count < MAX_LOOPS:
            loop_count += 1
            messages = self._get_inference_messages()

            if loop_count == 1:
                self._inject_soul_context_into_messages(messages, original_prompt)
                self._inject_dynamic_state_into_messages(messages)
                self._inject_tool_policy_if_needed(messages, original_prompt)

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
                    tools=active_tools or None,
                    tool_choice=tool_choice,
                )

                full_response = ""
                tool_calls_chunks = []

                stream_pp = StreamPostProcessor(
                    on_tool_executed=(
                        self._on_stream_tool_detected
                        if self._config.enable_stream_tool_execution
                        else None
                    ),
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

                self._log_debug_turn(original_prompt, messages, full_response)

                handled = self._tool_manager.handle_structured_calls(
                    final_tool_calls or [],
                    scene_prompt,
                    tools,
                )
                if handled["internal_found"]:
                    for tc in (final_tool_calls or []):
                        fn_name = tc.get("function", {}).get("name", "")
                        if fn_name == "store_long_term_memory":
                            char_name = self._character_manager.character_name.capitalize() if self._character_manager.character_name else "El personaje"
                            yield f"\n** {char_name} recordará esto **\n\n"
                            self._memory.add_assistant_message(content=None, tool_calls=[tc])
                            self._memory.add_tool_message(content="Memoria guardada. Continua tu respuesta.", tool_call_id=tc.get("id", ""))
                    continue

                if handled["external_calls"]:
                    self._memory.add_assistant_message(content=self._split_tagged_response(full_response or ""), tool_calls=handled["external_calls"])
                    yield {"choices": [{"message": {"tool_calls": handled["external_calls"]}}]}
                    return

                if (
                    not final_tool_calls
                    and self._config.enable_text_tool_fallback
                    and not self._config.enable_stream_tool_execution
                ):
                    text_tool_source = "\n".join(stream_pp.pending_tool_patterns) or full_response
                    text_handled = self._tool_manager.handle_text_calls(
                        text_tool_source,
                        scene_prompt,
                        tools,
                    )
                    if text_handled["memory_saved"]:
                        char_name = self._character_manager.character_name.capitalize() if self._character_manager.character_name else "El personaje"
                        yield f"\n** {char_name} recordará esto **\n\n"

                    if text_handled["external_calls"]:
                        self._memory.add_assistant_message(content=None, tool_calls=text_handled["external_calls"])
                        yield {"choices": [{"message": {"tool_calls": text_handled["external_calls"]}}]}
                        return

                self._memory.add_assistant_message(content=self._split_tagged_response(full_response or ""), tool_calls=None)
                if full_response:
                    self._short_memory.append({"role": "assistant", "content": full_response})

                self._log_generation_stats()

                # Marcar contexto como entregado
                try:
                    from ..orquestador import ContextInjector
                    if self._chat_store and self._memory._conversation_id:
                        inj = ContextInjector(self._chat_store, self._memory._conversation_id, self._memory._branch_id)
                        active = inj.list(only_active=True)
                        if active:
                            inj.mark_delivered([e.id for e in active])
                except Exception:
                    pass

                self._auto_index_if_needed()
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

    if self._config.disable_thinking:
        content = self.chat(prompt, max_tokens=max_tokens, temperature=temperature,
                            top_p=top_p, top_k=top_k, repeat_penalty=repeat_penalty)
        return "", content

    with self._lock:
        self._memory.add_user_message(prompt)
        self._auto_trim_if_needed()
        messages = self._get_inference_messages()
        self._inject_dynamic_state_into_messages(messages)
        self._inject_tool_policy_if_needed(messages, prompt)

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

            # Debug log: mensajes + respuesta
            self._log_debug_turn(prompt, messages, content)

            self._memory.add_assistant_message(self._split_tagged_response(full_history_content))
            self._log_generation_stats()
            self._auto_save_if_needed()

            # Marcar contexto como entregado
            try:
                from ..orquestador import ContextInjector
                if self._chat_store and self._memory._conversation_id:
                    inj = ContextInjector(self._chat_store, self._memory._conversation_id, self._memory._branch_id)
                    active = inj.list(only_active=True)
                    if active:
                        inj.mark_delivered([e.id for e in active])
            except Exception:
                pass

            self._auto_index_if_needed()

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

    if self._config.disable_thinking:
        for token in self.stream_chat(prompt, max_tokens=max_tokens, temperature=temperature,
                                      top_p=top_p, top_k=top_k, repeat_penalty=repeat_penalty):
            yield ("content", token)
        return

    with self._lock:
        self._memory.add_user_message(prompt)
        self._auto_trim_if_needed()
        messages = self._get_inference_messages()
        self._inject_dynamic_state_into_messages(messages)
        self._inject_tool_policy_if_needed(messages, prompt)

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

            # Debug log: mensajes + respuesta
            self._log_debug_turn(prompt, messages, full_response)

            self._memory.add_assistant_message(self._split_tagged_response(full_response))
            self._log_generation_stats()
            self._auto_save_if_needed()

            # Marcar contexto como entregado
            try:
                from ..orquestador import ContextInjector
                if self._chat_store and self._memory._conversation_id:
                    inj = ContextInjector(self._chat_store, self._memory._conversation_id, self._memory._branch_id)
                    active = inj.list(only_active=True)
                    if active:
                        inj.mark_delivered([e.id for e in active])
            except Exception:
                pass

            self._auto_index_if_needed()

        except ModelNotLoadedError:
            raise
        except Exception as e:
            raise InferenceError(f"Error en stream_chat_with_thinking(): {e}") from e

VToolLlama.stream_chat_with_thinking = stream_chat_with_thinking
