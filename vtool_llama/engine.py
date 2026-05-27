"""
Motor principal de vtool_llama.

Expone la clase VToolLlama, que es la interfaz pública de toda
la librería. Coordina:
- ConfigManager: configuración desde JSON
- ModelManager: carga, inferencia y descarga del modelo GGUF
- ChatMemory: historial de conversación estilo OpenAI
- LoggerManager: logging a archivo y debug en consola
- StatsManager: estadísticas de rendimiento

Uso esperado:
    from vtool_llama import VToolLlama

    llm = VToolLlama()

    respuesta = llm.chat("Hola, ¿cómo estás?")
    print(respuesta)

    for token in llm.stream_chat("Explícame Python"):
        print(token, end="")
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import deque
from pathlib import Path
from typing import Any, Generator, Optional

from .chat_memory import ChatMemory
from .config_manager import ConfigManager
from .exceptions import (
    ConfigError,
    EmptyPromptError,
    InferenceError,
    ModelNotLoadedError,
    VToolLlamaError,
)
from .logger_manager import LoggerManager
from .model_manager import ModelManager
from .slash_commands import SlashCommandRegistry
from .character_manager import CharacterManager
from .stats_manager import StatsManager
from .types import ConfigSchema, EpisodeSnapshot, GenerationStats, ModelInfo, PersonalityState
from .tools import (
    INTERNAL_TOOLS,
    SCENE_SYSTEM_COMMAND,
    parse_text_tool_calls,
    strip_text_tool_calls,
    execute_text_tool,
)


class VToolLlama:
    """
    Clase principal de la librería vtool_llama.

    Proporciona la API completa para interactuar con modelos
    GGUF locales: chat, streaming, gestión de memoria,
    configuración dinámica, y monitoreo.

    Args:
        config_path: ruta personalizada al config.json.
                     Si es None, busca en vtool_llama/config/config.json
        auto_load: si es True, carga el modelo al instanciar la clase
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        auto_load: bool = True,
    ):
        # Lock principal de la instancia (thread-safe)
        self._lock = threading.RLock()

        # ------------------------------------------------------------------
        # 1. Cargar configuración
        # ------------------------------------------------------------------
        self._config_manager = ConfigManager(config_path=config_path)
        try:
            self._config: ConfigSchema = self._config_manager.load()
        except ConfigError as e:
            # Si no hay config, usar valores por defecto
            self._config = ConfigSchema()
            self._log_warning(f"No se pudo cargar config.json: {e}. Usando defaults.")

        # ------------------------------------------------------------------
        # 2. Inicializar logger
        # ------------------------------------------------------------------
        self._log_manager = LoggerManager(
            logs_dir="logs" if self._config.enable_logging else None,
            enable_file_logging=self._config.enable_logging,
            debug_enabled=self._config.enable_console_debug,
            component="engine",
        )

        # ------------------------------------------------------------------
        # 3. Inicializar memoria de conversación
        # ------------------------------------------------------------------
        self._memory = ChatMemory(
            system_prompt=self._config.system_prompt,
            history_limit=self._config.history_limit,
            auto_trim=self._config.auto_trim_context,
        )

        # ------------------------------------------------------------------
        # 4. Inicializar gestor de estadísticas
        # ------------------------------------------------------------------
        self._stats = StatsManager()

        # ------------------------------------------------------------------
        # 5. Inicializar gestor del modelo
        # ------------------------------------------------------------------
        self._model_manager = ModelManager(
            config=self._config,
            logger_fn=self._log_debug,
            error_fn=self._log_error,
        )

        # ------------------------------------------------------------------
        # 6. Inicializar Character System
        # ------------------------------------------------------------------
        self._character_manager = CharacterManager(
            logger_fn=self._log_debug,
        )

        # ------------------------------------------------------------------
        # 7. Short memory (últimos N mensajes para contexto inmediato)
        # ------------------------------------------------------------------
        self._short_memory: deque[dict] = deque(
            maxlen=self._config.short_memory_limit
        )

        # ------------------------------------------------------------------
        # 8. Slash commands
        # ------------------------------------------------------------------
        self._slash_commands = SlashCommandRegistry()
        self._register_default_slash_commands()

        # ------------------------------------------------------------------
        # 9. Cargar modelo automáticamente si se solicita
        # ------------------------------------------------------------------
        if auto_load:
            try:
                self.load_model()
            except Exception as e:
                self._log_warning(f"No se pudo cargar el modelo automáticamente: {e}")
                self._log_info(
                    "Usa llm.load_model('ruta/al/modelo.gguf') manualmente."
                )

    # ======================================================================
    # API PÚBLICA — CHAT
    # ======================================================================

    def chat(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[Any] = None,
    ) -> Any:
        """
        Envía un mensaje y espera la respuesta completa.

        Si el prompt empieza con '/', se ejecuta como slash command
        sin invocar al modelo.

        Args:
            prompt: texto del usuario
            max_tokens: máximo de tokens a generar
            temperature: temperatura (0.0 a 2.0)
            top_p: nucleus sampling
            top_k: top-k sampling
            repeat_penalty: penalización de repetición
            tools: lista de herramientas opcionales (OpenAI format)
            tool_choice: tipo de selección de herramienta

        Returns:
            texto de la respuesta del asistente (str) o el diccionario de mensaje si llama a una herramienta de usuario (dict)

        Raises:
            EmptyPromptError: si el prompt está vacío
            ModelNotLoadedError: si no hay modelo cargado
            InferenceError: si falla la generación
        """
        self._validate_prompt(prompt)

        # --- 0. Cargar herramientas internas (Auto-Tools) ---
        internal_tools = list(INTERNAL_TOOLS)
        
        # Combinar tools del usuario con internas
        active_tools = (tools or []) + internal_tools

        # --- 1. Interceptar slash commands ---
        scene_prompt = SCENE_PROMPT
        if prompt.strip().lower() == "/scene_view":
            prompt = scene_prompt
            slash_result = None
        else:
            slash_result = self._handle_slash_command(prompt)
            
        if slash_result is not None:
            return slash_result

        # --- 2. Interceptar #mem (atajo directo para guardar memoria) ---
        mem_prefix = "#mem "
        if prompt.strip().startswith(mem_prefix):
            mem_content = prompt.strip()[len(mem_prefix):].strip()
            if mem_content:
                self._character_manager.add_memory(
                    content=mem_content, always_include=True, priority=1.0,
                )
                self._log_info(f"🧠 [#mem] Memoria guardada: {mem_content}")
                char_name = self._character_manager.character_name.capitalize() if self._character_manager.character_name else "El personaje"
                prompt = f"(Has guardado un recuerdo: '{mem_content}') Confirma brevemente en character que lo has recordado, sin mencionar herramientas ni sistemas."

        with self._lock:
            # --- 3. Actualizar short memory ---
            self._short_memory.append({"role": "user", "content": prompt})

            # --- 4. Agregar mensaje del usuario al historial largo ---
            self._memory.add_user_message(prompt)

            # Auto-trim si está activado
            self._auto_trim_if_needed()

            # --- 4. Inyectar personality state en system prompt ---
            self._inject_personality_into_system_prompt()

            # Ciclo de razonamiento interno (Auto-Tools loop)
            # El modelo puede llamar a herramientas internas (remember_memory)
            # y luego continuar generando. MAX_LOOPS evita bucles infinitos.
            loop_count = 0
            MAX_LOOPS = 3
            memory_saved = False
            
            while loop_count < MAX_LOOPS:
                loop_count += 1
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
                        tools=active_tools,
                        tool_choice=tool_choice,
                    )

                    msg_choice = result["choices"][0]["message"]
                    response_text = msg_choice.get("content") or ""
                    tool_calls = msg_choice.get("tool_calls", None)

                    self._record_stats(result)
                    
                    if tool_calls:
                        # Identificar si es una tool interna (Auto-Tool)
                        internal_call_found = False
                        for tc in tool_calls:
                            fn_name = tc.get("function", {}).get("name", "")
                            if fn_name == "remember_memory":
                                internal_call_found = True
                                try:
                                    args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                                    mem_content = args.get("content", "")
                                    if mem_content:
                                        self.add_memory(mem_content, priority=1.0)
                                        self._log_info(f"🧠 [Auto-Tool] Memoria guardada automáticamente: {mem_content}")
                                        memory_saved = True
                                        self._memory.add_assistant_message(content=None, tool_calls=[tc])
                                        self._memory.add_tool_message(content="Memoria guardada exitosamente. Ahora respondele al usuario.", tool_call_id=tc.get("id", ""))
                                except Exception as e:
                                    self._log_warning(f"Fallo al ejecutar remember_memory: {e}")

                            elif fn_name == "describe_scene":
                                internal_call_found = True
                                self._log_info(f"🎬 [Auto-Tool] Descripción de escena solicitada")
                                self._memory.add_assistant_message(content=None, tool_calls=[tc])
                                self._memory.add_tool_message(
                                    content=scene_prompt,
                                    tool_call_id=tc.get("id", ""),
                                )

                        if internal_call_found:
                            # Re-evaluar el bucle para que el modelo genere la respuesta de texto
                            continue

                        # Si no es interna, validar contra las tools del usuario
                        if tools:
                            valid_tool_calls = self._validate_tool_calls(tool_calls, tools)
                            if valid_tool_calls:
                                self._memory.add_assistant_message(content=response_text, tool_calls=valid_tool_calls)
                                self._short_memory.append({"role": "assistant", "content": "(Llama a herramienta externa)"})
                                return msg_choice

                    # --- Fallback: parser de tool_calls en texto plano ---
                    # Algunos modelos GGUF escriben tool calls como texto
                    # en vez de usar el formato OpenAI estructurado:
                    #   {{remember_memory{content: "..."}}}
                    #   {{get_weather{location: "Madrid"}}}
                    if not tool_calls and not memory_saved:
                        text_tools = parse_text_tool_calls(response_text)
                        if text_tools:
                            internal_call_found = False
                            external_calls = []
                            for fn_name, fn_args in text_tools:
                                if fn_name == "remember_memory":
                                    mem_content = fn_args.get("content", "")
                                    if mem_content:
                                        self.add_memory(mem_content, priority=1.0)
                                        self._log_info(f"🧠 [Auto-Tool/Texto] Memoria guardada: {mem_content}")
                                        memory_saved = True
                                        internal_call_found = True
                                elif fn_name == "describe_scene":
                                    self._log_info(f"🎬 [Auto-Tool/Texto] Descripción de escena solicitada")
                                    internal_call_found = True
                                else:
                                    external_calls.append({
                                        "function": {"name": fn_name, "arguments": json.dumps(fn_args)}
                                    })
                            response_text = strip_text_tool_calls(response_text)
                            if internal_call_found:
                                continue
                            if external_calls and tools:
                                valid = self._validate_tool_calls(external_calls, tools)
                                if valid:
                                    self._memory.add_assistant_message(content=response_text, tool_calls=valid)
                                    self._short_memory.append({"role": "assistant", "content": "(Llama a herramienta externa)"})
                                    return {"choices": [{"message": {"tool_calls": valid}}]}

                    # Respuesta normal de texto (sin tool_calls o internas ya resueltas)
                    if memory_saved:
                        char_name = self._character_manager.character_name.capitalize() if self._character_manager.character_name else "El personaje"
                        response_text = f"** {char_name} recordará esto **\n\n" + response_text
                        
                    self._memory.add_assistant_message(content=response_text, tool_calls=None)
                    self._short_memory.append({"role": "assistant", "content": response_text})
                    self._log_generation_stats()
                    return response_text

                except ModelNotLoadedError:
                    raise
                except Exception as e:
                    raise InferenceError(f"Error en chat(): {e}") from e
                    
            return "Error: Excedido el límite máximo de razonamiento interno."

    def stream_chat(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[Any] = None,
    ) -> Generator[Any, None, None]:
        """
        Envía un mensaje y recibe la respuesta token por token o chunks de tool_calls.

        Si el prompt empieza con '/', se ejecuta como slash command
        sin invocar al modelo (yield de la respuesta directa).

        Args:
            prompt: texto del usuario
            max_tokens: máximo de tokens a generar
            temperature: temperatura (0.0 a 2.0)
            top_p: nucleus sampling
            top_k: top-k sampling
            repeat_penalty: penalización de repetición
            tools: lista de herramientas opcionales (OpenAI format)
            tool_choice: tipo de selección de herramienta

        Yields:
            cada token de la respuesta en tiempo real o chunks del stream

        Raises:
            EmptyPromptError: si el prompt está vacío
            ModelNotLoadedError: si no hay modelo cargado
        """
        self._validate_prompt(prompt)

        scene_prompt = SCENE_PROMPT

        # --- 1. Interceptar slash commands ---
        if prompt.strip().lower() == "/scene_view":
            prompt = scene_prompt
            slash_result = None
        else:
            slash_result = self._handle_slash_command(prompt)
            
        if slash_result is not None:
            yield slash_result
            return

        # --- 2. Interceptar #mem (atajo directo para guardar memoria) ---
        mem_prefix = "#mem "
        if prompt.strip().startswith(mem_prefix):
            mem_content = prompt.strip()[len(mem_prefix):].strip()
            if mem_content:
                self._character_manager.add_memory(
                    content=mem_content, always_include=True, priority=1.0,
                )
                self._log_info(f"🧠 [#mem] Memoria guardada: {mem_content}")
                char_name = self._character_manager.character_name.capitalize() if self._character_manager.character_name else "El personaje"
                prompt = f"(Has guardado un recuerdo: '{mem_content}') Confirma brevemente en character que lo has recordado, sin mencionar herramientas ni sistemas."

        # --- 0. Cargar herramientas internas (Auto-Tools) ---
        internal_tools = list(INTERNAL_TOOLS)
        
        # Combinar tools del usuario con internas
        active_tools = (tools or []) + internal_tools

        # --- 2. Forzar rebuild del KV Cache si hay memorias nuevas ---
        self._check_and_rebuild_if_needed()

        with self._lock:
            # --- 3. Actualizar short memory ---
            self._short_memory.append({"role": "user", "content": prompt})

            # --- 4. Agregar mensaje del usuario al historial largo ---
            self._memory.add_user_message(prompt)

            # Auto-trim si está activado
            self._auto_trim_if_needed()

            # --- 5. Inyectar personality state en system prompt ---
            self._inject_personality_into_system_prompt()
            
            loop_count = 0
            MAX_LOOPS = 3
            
            while loop_count < MAX_LOOPS:
                loop_count += 1
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
                        tools=active_tools,
                        tool_choice=tool_choice,
                    )

                    full_response = ""
                    tool_calls_chunks = []
                    
                    for chunk in stream:
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})

                        if "tool_calls" in delta and delta["tool_calls"]:
                            tool_calls_chunks.append(delta["tool_calls"])
                            # No yield de tool calls internos para no ensuciar la consola del usuario
                            # yield chunk
                        else:
                            token = delta.get("content", "")
                            if token:
                                full_response += token
                                yield token

                    final_tool_calls = None
                    if tool_calls_chunks:
                        final_tool_calls = self._reconstruct_tool_calls(tool_calls_chunks)

                    self._record_stats_from_stream(stream, full_response)
                    
                    if final_tool_calls:
                        internal_call_found = False
                        for tc in final_tool_calls:
                            fn_name = tc.get("function", {}).get("name", "")
                            if fn_name == "remember_memory":
                                internal_call_found = True
                                try:
                                    args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                                    mem_content = args.get("content", "")
                                    if mem_content:
                                        self.add_memory(mem_content, priority=1.0)
                                        self._log_info(f"🧠 [Auto-Tool] Memoria guardada automáticamente: {mem_content}")
                                        char_name = self._character_manager.character_name.capitalize() if self._character_manager.character_name else "El personaje"
                                        yield f"\n** {char_name} recordará esto **\n\n"
                                        
                                        self._memory.add_assistant_message(content=None, tool_calls=[tc])
                                        self._memory.add_tool_message(content="Memoria guardada exitosamente. Continua tu respuesta ahora.", tool_call_id=tc.get("id", ""))
                                except Exception as e:
                                    self._log_warning(f"Fallo al ejecutar remember_memory en stream: {e}")

                            elif fn_name == "describe_scene":
                                internal_call_found = True
                                self._log_info(f"🎬 [Auto-Tool] Descripción de escena solicitada en stream")
                                self._memory.add_assistant_message(content=None, tool_calls=[tc])
                                self._memory.add_tool_message(
                                    content=scene_prompt,
                                    tool_call_id=tc.get("id", ""),
                                )
                                    
                        if internal_call_found:
                            continue # Re-iniciar bucle de streaming para generar el texto de confirmación
                            
                        # Si es herramienta externa
                        if tools:
                            valid_tool_calls = self._validate_tool_calls(final_tool_calls, tools)
                            if valid_tool_calls:
                                self._memory.add_assistant_message(content=full_response or None, tool_calls=valid_tool_calls)
                                # Para streaming, yield del objeto simulado de tool call final
                                yield {"choices": [{"message": {"tool_calls": valid_tool_calls}}]}
                                return

                    # --- Fallback: parser de tool_calls en texto plano ---
                    if not final_tool_calls:
                        text_tools = parse_text_tool_calls(full_response)
                        if text_tools:
                            for fn_name, fn_args in text_tools:
                                if fn_name == "remember_memory":
                                    mem_content = fn_args.get("content", "")
                                    if mem_content:
                                        self.add_memory(mem_content, priority=1.0)
                                        self._log_info(f"🧠 [Auto-Tool/Texto] Memoria guardada en stream: {mem_content}")
                                        char_name = self._character_manager.character_name.capitalize() if self._character_manager.character_name else "El personaje"
                                        yield f"\n** {char_name} recordará esto **\n\n"
                                elif fn_name == "describe_scene":
                                    self._log_info(f"🎬 [Auto-Tool/Texto] Descripción de escena solicitada en stream")
                                elif tools:
                                    # Tool externa en texto plano → devolver como si fuera real
                                    tc = {"function": {"name": fn_name, "arguments": json.dumps(fn_args)}}
                                    valid = self._validate_tool_calls([tc], tools)
                                    if valid:
                                        self._memory.add_assistant_message(content=None, tool_calls=valid)
                                        yield {"choices": [{"message": {"tool_calls": valid}}]}
                                        return
                            full_response = strip_text_tool_calls(full_response)

                    # Final de respuesta textual
                    self._memory.add_assistant_message(content=full_response or None, tool_calls=None)
                    if full_response:
                        self._short_memory.append({"role": "assistant", "content": full_response})
                    self._log_generation_stats()
                    return

                except ModelNotLoadedError:
                    raise
                except Exception as e:
                    raise InferenceError(f"Error en stream_chat(): {e}") from e

    def _reconstruct_tool_calls(self, chunks: list[list[dict]]) -> list[dict]:
        """Reconstruye llamadas a herramientas acumuladas desde el stream delta."""
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

    def chat_with_thinking(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
    ) -> tuple[str, str]:
        """
        Envía un mensaje y retorna la tupla (thinking_content, final_answer).
        Soporta tanto el campo nativo 'reasoning_content' de llama-cpp-python como el parseo de etiquetas <think>.
        """
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

                # Registrar estadísticas
                self._record_stats(result)

                # Si no hay reasoning nativo, pero hay etiquetas en content:
                if not thinking and "<think>" in content:
                    parts = content.split("</think>", 1)
                    thinking = parts[0].replace("<think>", "").strip()
                    content = parts[1].strip() if len(parts) > 1 else ""

                # Reconstruir mensaje para guardar en el historial (formato compatible)
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

    def stream_chat_with_thinking(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
    ) -> Generator[tuple[str, str], None, None]:
        """
        Envía un mensaje y recibe tuplas (tipo, token) donde tipo es 'thinking' o 'content'.
        Maneja tanto streaming nativo de 'reasoning_content' como etiquetas <think> fragmentadas en 'content'.
        """
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

                    # 1. Si llega reasoning_content nativo de llama.cpp
                    if thinking_token:
                        full_response += thinking_token
                        yield ("thinking", thinking_token)
                        continue

                    if not content_token:
                        continue

                    full_response += content_token
                    buffer += content_token

                    # 2. Parseador incremental robusto para etiquetas <think> y </think>
                    while True:
                        if mode == "content":
                            idx = buffer.find("<think>")
                            if idx == -1:
                                # Guardar parciales de etiqueta de apertura (ej: '<th') al final del buffer
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
                                # Guardar parciales de etiqueta de cierre (ej: '</thi') al final del buffer
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

                # Vaciar buffer restante al final
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

    def add_tool_message(self, content: str, tool_call_id: str) -> None:
        """Agrega la respuesta de una herramienta al historial."""
        with self._lock:
            self._memory.add_tool_message(content, tool_call_id)

    # ======================================================================
    # API PÚBLICA — MEMORIA
    # ======================================================================

    def clear_memory(self) -> None:
        """
        Limpia el historial de conversación.
        Preserva el system prompt.
        """
        with self._lock:
            self._memory.clear()
        self._log_debug("MEMORY", "Historial de conversación limpiado")

    def reset_chat(self) -> None:
        """
        Reinicia completamente la conversación.
        Alias de clear_memory().
        """
        self.clear_memory()

    def get_memory(self) -> list[dict[str, str]]:
        """
        Retorna el historial actual como lista de dicts.

        Returns:
            [{"role": "...", "content": "..."}, ...]
        """
        return self._memory.messages_dict

    def export_memory_json(self, path: Optional[str] = None) -> str:
        """
        Exporta el historial a JSON.

        Args:
            path: si se proporciona, escribe el archivo

        Returns:
            string JSON del historial
        """
        return self._memory.export_json(path)

    def import_memory_json(self, json_str_or_path: str) -> None:
        """
        Importa un historial desde JSON.

        Args:
            json_str_or_path: string JSON o ruta de archivo
        """
        with self._lock:
            self._memory.import_json(json_str_or_path)
        self._log_debug("MEMORY", "Historial importado correctamente")

    def set_system_prompt(self, prompt: str) -> None:
        """
        Cambia el system prompt de la conversación.

        Args:
            prompt: nuevo system prompt
        """
        with self._lock:
            self._memory.system_prompt = prompt
            self._config.system_prompt = prompt
        self._log_debug("CONFIG", f"System prompt actualizado: {prompt[:50]}...")

    # ======================================================================
    # API PÚBLICA — MODELO
    # ======================================================================

    def load_model(self, model_path: Optional[str] = None) -> None:
        """
        Carga un modelo GGUF en memoria.

        Args:
            model_path: ruta al .gguf. Si es None, usa models_directory
                       + default_model del config. También acepta solo
                       el nombre del archivo (lo busca en el directorio).
        """
        with self._lock:
            self._model_manager.load_model(model_path)

    def reload_model(self) -> None:
        """
        Recarga el modelo actual con la configuración vigente.
        Útil después de modificar config.json.
        """
        with self._lock:
            self._model_manager.reload_model()

    def unload_model(self) -> None:
        """
        Descarga el modelo de memoria para liberar VRAM/RAM.
        """
        with self._lock:
            self._model_manager.unload_model()

    def switch_model(self, model_path: str) -> None:
        """
        Cambia a un modelo GGUF diferente.

        Args:
            model_path: ruta al nuevo archivo .gguf
        """
        with self._lock:
            self._model_manager.switch_model(model_path)

    def get_model_info(self) -> dict:
        """
        Retorna información del modelo cargado.

        Returns:
            dict con model_name, context_size, gpu_layers, estimated_vram
        """
        return self._model_manager.get_model_info()

    def list_available_models(self) -> list[dict[str, str]]:
        """
        Escanea el directorio de modelos y retorna todos los .gguf
        disponibles con su nombre, ruta y tamaño.

        Permite al proyecto principal mostrar un menú de modelos
        o validar que existe antes de cargarlo.

        Returns:
            list[dict] — cada dict tiene filename, path, size_gb, modified
        """
        with self._lock:
            return self._model_manager.list_available_models()

    def supports_tools(self) -> bool:
        """
        Detecta si el modelo cargado soporta function calling nativo
        (OpenAI-style tool calls) revisando su chat template en la
        metadata del GGUF.

        Returns:
            True si el modelo soporta tools, False si no
        """
        return self._model_manager.supports_tools()

    # ======================================================================
    # API PÚBLICA — DEBUG
    # ======================================================================

    def enable_debug(self) -> None:
        """Activa la salida de debug en consola."""
        self._log_manager.enable_debug()
        self._config.enable_console_debug = True

    def disable_debug(self) -> None:
        """Desactiva la salida de debug en consola."""
        self._config.enable_console_debug = False
        self._log_manager.disable_debug()

    # ======================================================================
    # API PÚBLICA — CONTEXTO
    # ======================================================================

    def trim_memory(self) -> int:
        """
        Recorta manualmente el historial para liberar contexto.

        Returns:
            cantidad de mensajes eliminados
        """
        with self._lock:
            if not self._model_manager.is_loaded:
                self._log_warning("No hay modelo cargado para contar tokens exactos.")
                self._memory.clear()
                return 0

            removed = self._memory.trim_to_token_budget(
                max_context_tokens=self._config.n_ctx,
                reserve_tokens=self._config.context_reserve_tokens,
                count_fn=self._model_manager.count_tokens,
            )

            if removed > 0:
                self._log_debug("MEMORY", f"Contexto recortado: {removed} mensaje(s) eliminado(s)")

            return removed

    # ======================================================================
    # API PÚBLICA — CONFIGURACIÓN
    # ======================================================================

    def get_config(self) -> ConfigSchema:
        """Retorna la configuración actual."""
        return self._config

    def reload_config(self) -> None:
        """
        Recarga la configuración desde config.json.
        Útil si se modificó el archivo externamente.
        """
        with self._lock:
            self._config = self._config_manager.reload()
            self._memory.system_prompt = self._config.system_prompt
            self._memory._history_limit = self._config.history_limit
        self._log_debug("CONFIG", "Configuración recargada desde archivo")

    # ======================================================================
    # API PÚBLICA — CHARACTER SYSTEM
    # ======================================================================

    def list_characters(self) -> list[str]:
        return self._character_manager.list_characters()

    def create_character(self, name: str, identity_data: dict, personality_data: dict, speech_data: dict, rules_data: dict, initial_memories: list = None) -> None:
        """
        Crea un nuevo personaje con el DNA y memorias iniciales dadas.
        """
        self._character_manager.create_character(
            name=name,
            identity_data=identity_data,
            personality_data=personality_data,
            speech_data=speech_data,
            rules_data=rules_data,
            initial_memories=initial_memories
        )

    def generate_character_with_ai(self, name: str, prompt: str) -> None:
        """
        Usa el LLM actual para generar un personaje completo y guardarlo en disco.
        Requiere que auto_load=True al instanciar VToolLlama, o haber llamado a load_model().
        """
        if not self._model_manager.is_loaded:
            raise RuntimeError("El modelo debe estar cargado para usar generate_character_with_ai(). Instancia con auto_load=True o llama a load_model() primero.")

        system_prompt = (
            "Eres un experto diseñador de personajes y escritor creativo. "
            "Tu tarea es crear un perfil de personaje rico y detallado basado en la solicitud del usuario.\n"
            "DEBES responder ÚNICAMENTE con un objeto JSON válido, sin Markdown, sin explicaciones, solo el JSON puro.\n"
            "NO agregues campos adicionales ni cambies los nombres de los campos existentes. "
            "Usa EXACTAMENTE los nombres de clave que aparecen en la estructura de abajo.\n\n"
            "El JSON DEBE tener esta estructura exacta (sin campos extra):\n"
            "{\n"
            '  "identity": {\n'
            '    "name": "Nombre público",\n'
            '    "role": "Su rol o título",\n'
            '    "background": "Historia de fondo muy detallada y creativa",\n'
            '    "scenario": "El mundo actual o contexto donde se encuentra"\n'
            "  },\n"
            '  "personality": {\n'
            '    "traits": ["rasgo1", "rasgo2", "rasgo3"],\n'
            '    "motivations": ["su principal motivación", "otra motivación"],\n'
            '    "flaws": ["defecto de carácter", "miedo principal"]\n'
            "  },\n"
            '  "speech": {\n'
            '    "style": "ej. Casual, Formal, Sarcástico",\n'
            '    "tone": "ej. Cálido, Frío",\n'
            '    "verbosity": "Bajo, Medio o Alto",\n'
            '    "examples": [\n'
            '      "{{user}}: hola\\n{{char}}: *levanta la mirada* ¿Qué quieres?",\n'
            '      "{{user}}: ayúdame\\n{{char}}: *suspira* Supongo que no hay otra opción."\n'
            '    ]\n'
            "  },\n"
            '  "rules": {\n'
            '    "core_rules": ["regla importante 1", "regla 2"],\n'
            '    "never_do": ["lo que nunca debe hacer 1"],\n'
            '    "response_style": ["ej. usa asteriscos para acciones", "ej. respuestas cortas"],\n'
            '    "roleplay_mode": true\n'
            "  },\n"
            '  "memories": ["memoria inicial 1 sobre sí mismo o el usuario", "memoria 2"]\n'
            "}"
        )

        self._log_info(f"Generando personaje '{name}' con IA...")
        
        # Ajustamos parámetros para generación creativa pero estructurada
        result = self._model_manager.generate(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            stream=False,
            max_tokens=1024,
            temperature=0.8
        )
        
        response_text = result["choices"][0]["message"].get("content", "")
        
        # Parseo robusto del JSON
        import json
        try:
            start_idx = response_text.find("{")
            end_idx = response_text.rfind("}") + 1
            if start_idx == -1 or end_idx == 0:
                raise ValueError("No se encontró JSON en la respuesta del modelo.")
            
            clean_json = response_text[start_idx:end_idx]
            data = json.loads(clean_json)
            
            self.create_character(
                name=name,
                identity_data=data.get("identity", {}),
                personality_data=data.get("personality", {}),
                speech_data=data.get("speech", {}),
                rules_data=data.get("rules", {}),
                initial_memories=data.get("memories", [])
            )
            
            self._log_info(f"¡Personaje '{name}' autogenerado con éxito!")
            
        except Exception as e:
            self._log_error(f"Fallo al generar personaje con IA. Respuesta raw: {response_text}")
            raise RuntimeError(f"Error parseando el personaje autogenerado: {e}")

    def load_character(self, name: str) -> None:
        self._character_manager.load_character(name)
        
        # 1. Intentar cargar KV Cache acelerado
        char_dir = self._character_manager._char_dir
        if char_dir and self._model_manager.is_loaded:
            base_kv_path = char_dir / "memory" / "base.state"
            full_kv_path = char_dir / "memory" / "personality_plus_memory.state"
            
            prompt = self._character_manager.build_system_prompt(self._config.system_prompt)
            
            # Si el base no existe, el warmup se encarga de crear base y luego full
            if not base_kv_path.exists() or not full_kv_path.exists() or self._character_manager.check_needs_rebuild(prompt):
                self._warmup_character_cache(prompt)
            else:
                self._model_manager.load_kv_state(str(full_kv_path))

        # 2. Forzar actualización del prompt en memoria
        self._inject_personality_into_system_prompt()

    def _warmup_character_cache(self, prompt: Optional[str] = None) -> None:
        """Pre-evalúa el system prompt usando arquitectura dual (Base + Dynamic)."""
        char_dir = self._character_manager._char_dir
        if not char_dir or not self._model_manager.is_loaded:
            return
            
        base_kv_path = char_dir / "memory" / "base.state"
        full_kv_path = char_dir / "memory" / "personality_plus_memory.state"
        
        # 1. Base State (DNA)
        base_prompt = self._character_manager.build_base_system_prompt(self._config.system_prompt)
        if not base_kv_path.exists():
            self._log_debug("STATE", "Generando KV Cache Base (DNA)...")
            self._model_manager.warmup_system_prompt(base_prompt)
            self._model_manager.save_kv_state(str(base_kv_path))
            
        # 2. Cargar Base State
        self._model_manager.load_kv_state(str(base_kv_path))
        
        # 3. Full State (DNA + Memory + Mods + Runtime)
        if prompt is None:
            prompt = self._character_manager.build_system_prompt(self._config.system_prompt)
            
        self._log_debug("STATE", "Añadiendo Memoria al KV Cache Base...")
        # Al enviarle el prompt completo, Llama internamente detecta que el prefijo
        # coincide con el Base State y solo procesa los tokens nuevos (Memoria).
        self._model_manager.warmup_system_prompt(prompt)
        self._model_manager.save_kv_state(str(full_kv_path))
        self._character_manager.mark_rebuild_done(prompt)

    def rebuild_personality_state(self) -> None:
        """
        Reconstruye el estado de personalidad del agente usando el
        historial de conversación actual.

        Usa el LLM para generar un resumen estructurado de:
        - Preferencias del usuario
        - Herramientas usadas frecuentemente
        - Estilo conversacional detectado

        Solo se ejecuta si el modelo está cargado. Si no, marca
        el estado como sincronizado sin procesar.
        """
        with self._lock:
            if not self._model_manager.is_loaded:
                self._log_warning("No hay modelo cargado para rebuild_personality_state")
                return

            # Obtener memorias y contexto actual
            memories_text = "\n".join(
                f"- {m.content}" for m in self._character_manager.memories
            )
            history_sample = ""
            non_system = [m for m in self._memory.messages if m.role != "system"]
            # Tomar los últimos 20 mensajes como muestra
            for m in non_system[-20:]:
                if m.content:
                    history_sample += f"{m.role}: {m.content[:100]}\n"

            rebuild_prompt = (
                "Analiza la siguiente información del usuario y genera un resumen "
                "estructurado en formato JSON. NO incluyas explicaciones, SOLO el JSON.\n\n"
                f"Memorias guardadas:\n{memories_text}\n\n"
                f"Últimos mensajes:\n{history_sample}\n\n"
                "Genera un JSON con esta estructura exacta:\n"
                '{\n'
                '  "dynamics": ["observación 1", "observación 2"],\n'
                '  "trust_level": 0.5,\n'
                '  "familiarity": 0.2\n'
                '}'
            )

            try:
                # Usar generate directamente para no contaminar el historial
                result = self._model_manager.generate(
                    messages=[
                        {"role": "system", "content": "Eres un analizador de patrones. Responde SOLO con JSON válido."},
                        {"role": "user", "content": rebuild_prompt},
                    ],
                    stream=False,
                    max_tokens=256,
                    temperature=0.3,
                )
                response_text = result["choices"][0]["message"].get("content", "")

                # Parsear JSON de la respuesta
                # Intentar extraer JSON del texto
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    parsed = json.loads(response_text[json_start:json_end])

                    # Actualizar relationship state
                    rel = self._character_manager.relationship_state
                    if "dynamics" in parsed:
                        rel.dynamics = parsed["dynamics"]
                    if "trust_level" in parsed:
                        rel.trust_level = float(parsed["trust_level"])
                    if "familiarity" in parsed:
                        rel.familiarity = float(parsed["familiarity"])

                    self._log_debug("STATE", f"Personality state reconstruido: {parsed}")
                else:
                    self._log_warning("rebuild_personality_state: no se pudo extraer JSON válido")

            except Exception as e:
                self._log_warning(f"Error en rebuild_personality_state: {e}")

            # Guardar el state en disco
            self._character_manager.save_state()
            
            # Generar el nuevo KV Cache con la memoria consolidada
            self._warmup_character_cache()

    def add_memory(
        self,
        content: str,
        priority: float = 0.5,
        always_include: bool = False,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """
        Agrega una memoria persistente al estado del agente.

        Args:
            content: texto de la memoria
            priority: peso de relevancia (0.0 a 1.0)
            always_include: si siempre se inyecta en el prompt
            tags: etiquetas opcionales

        Returns:
            dict con id y content de la memoria creada.
        """
        entry = self._character_manager.add_memory(
            content=content,
            priority=priority,
            always_include=always_include,
            tags=tags,
        )
        return {"id": entry.id, "content": entry.content}

    def save_episode(self) -> "EpisodeSnapshot":
        """
        Guarda un snapshot episódico de la conversación actual.
        
        Toma los últimos 5 mensajes no-system del historial,
        genera un resumen con el LLM, y guarda un archivo versionado
        (episode_001.json, episode_002.json, etc.) que nunca se sobreescribe.
        
        Returns:
            EpisodeSnapshot creado
        """
        # Recopilar últimos 5 mensajes no-system
        non_system = [m for m in self._memory.messages if m.role != "system"]
        last_messages = []
        for m in non_system[-5:]:
            msg = {"role": m.role, "content": m.content or ""}
            last_messages.append(msg)
        
        if not last_messages:
            raise RuntimeError("No hay mensajes para guardar como episodio.")
        
        # Generar resumen con LLM
        summary = self._generate_episode_summary(last_messages)
        
        # Guardar a disco
        episode = self._character_manager.save_episode(
            messages=last_messages,
            summary=summary,
        )
        return episode

    def _generate_episode_summary(self, messages: list[dict]) -> str:
        """
        Usa el LLM para generar un resumen conciso de los mensajes dados.
        Si el modelo no está cargado, genera un resumen simple por concatenación.
        """
        # Construir texto de los mensajes
        conversation_text = ""
        for m in messages:
            role_label = "Usuario" if m["role"] == "user" else "Personaje"
            conversation_text += f"{role_label}: {m.get('content', '')}\n"
        
        if not self._model_manager.is_loaded:
            # Fallback sin LLM
            return conversation_text[:200].strip()
        
        try:
            result = self._model_manager.generate(
                messages=[
                    {"role": "system", "content": "Genera un resumen BREVE (máximo 2 oraciones) de esta conversación. Solo el resumen, sin explicaciones."},
                    {"role": "user", "content": f"Conversación:\n{conversation_text}\n\nResumen:"},
                ],
                stream=False,
                max_tokens=100,
                temperature=0.3,
            )
            summary = result["choices"][0]["message"].get("content", "").strip()
            return summary or conversation_text[:200].strip()
        except Exception as e:
            self._log_warning(f"No se pudo generar resumen con LLM: {e}")
            return conversation_text[:200].strip()

    def list_episodes(self) -> list[dict]:
        """Lista todos los episodios guardados del personaje actual."""
        return self._character_manager.list_episodes()

    def load_episode(self, episode_id: int) -> None:
        """Carga un episodio específico por su ID (rollback)."""
        self._character_manager.load_episode(episode_id)
        self._inject_personality_into_system_prompt()

    def delete_episode(self, episode_id: int) -> bool:
        """Elimina un episodio por su ID."""
        return self._character_manager.delete_episode(episode_id)

    def get_state_info(self) -> dict:
        """
        Retorna información del estado actual del agente.

        Returns:
            dict con personality, relationship, memories, mood, versiones.
        """
        state = {'name': self._character_manager.character_name}
        state["needs_rebuild"] = self._character_manager.needs_rebuild
        return state

    @property
    def state_manager(self) -> CharacterManager:
        """Acceso directo al CharacterManager para configuración avanzada."""
        return self._character_manager

    @property
    def slash_commands(self) -> SlashCommandRegistry:
        """Acceso al registro de slash commands para extensión."""
        return self._slash_commands

    # ======================================================================
    # MÉTODOS INTERNOS
    # ======================================================================

    def _validate_prompt(self, prompt: str) -> None:
        """
        Valida que el prompt no esté vacío.

        Raises:
            EmptyPromptError: si el prompt es None o solo espacios
        """
        if not prompt or not prompt.strip():
            raise EmptyPromptError(
                "El prompt no puede estar vacío. Proporciona un texto válido."
            )

    def _extract_response_text(self, result: Any) -> str:
        """
        Extrae el texto de respuesta del resultado de llama-cpp-python.

        Args:
            result: salida de model.create_chat_completion()

        Returns:
            texto de la respuesta
        """
        try:
            return result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            self._log_warning(f"No se pudo extraer texto de la respuesta: {e}")
            return str(result)

    def _extract_token_from_chunk(self, chunk: Any) -> tuple[str, str]:
        """
        Extrae un token de pensamiento (reasoning) y un token de contenido (content)
        de un chunk de streaming.

        Args:
            chunk: un elemento del generador de streaming

        Returns:
            tuple[str, str] -> (thinking_token, content_token)
        """
        try:
            choices = chunk.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                thinking = delta.get("reasoning_content", "") or ""
                content = delta.get("content", "") or ""
                return thinking, content
        except (KeyError, IndexError, TypeError, AttributeError):
            pass
        return "", ""

    def _record_stats(self, result: Any) -> None:
        """
        Registra estadísticas de una generación completa.

        Args:
            result: salida de model.create_chat_completion()
        """
        try:
            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

            self._stats.end_generation(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_name=self._model_manager.model_info.model_name,
            )
        except Exception as e:
            self._log_warning(f"No se pudieron registrar estadísticas: {e}")

    def _record_stats_from_stream(
        self,
        stream: Any,
        full_response: str,
    ) -> None:
        """
        Registra estadísticas a partir de un stream.

        Args:
            stream: el generador de streaming (ya consumido)
            full_response: texto completo generado
        """
        # En streaming, la información de tokens puede estar en
        # el último chunk o debemos estimarla
        try:
            # Intentar obtener usage del último chunk si está disponible
            if hasattr(stream, "_last_chunk") and stream._last_chunk:
                usage = stream._last_chunk.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
            else:
                # Estimar por cantidad de caracteres
                prompt_tokens = 0
                completion_tokens = len(full_response) // 4

            self._stats.end_generation(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_name=self._model_manager.model_info.model_name,
            )
        except Exception as e:
            self._log_warning(f"No se pudieron registrar estadísticas del stream: {e}")
            self._stats.end_generation(
                model_name=self._model_manager.model_info.model_name,
            )

    def _check_and_rebuild_if_needed(self) -> None:
        """
        Si el flag _needs_rebuild está activo (por agregar memoria,
        cambiar mods, etc.), regenera el KV Cache antes del próximo chat.
        """
        if not self._character_manager.is_loaded or not self._model_manager.is_loaded:
            return
        char_dir = self._character_manager._char_dir
        if not char_dir:
            return
        prompt = self._character_manager.build_system_prompt(self._config.system_prompt)
        if self._character_manager.check_needs_rebuild(prompt):
            self._log_debug("STATE", "Rebuild pendiente — regenerando KV Cache antes del chat...")
            self._warmup_character_cache(prompt)
            self._log_debug("STATE", "KV Cache regenerado.")

    def _auto_trim_if_needed(self) -> None:
        """
        Verifica si el contexto está cerca del límite y recorta
        automáticamente si es necesario y está configurado.
        """
        if not self._config.auto_trim_context:
            return

        if not self._model_manager.is_loaded:
            return

        # Obtener tokens actuales aproximados
        context_text = " ".join(
            m.content for m in self._memory.messages if m.content
        )
        current_tokens = self._model_manager.count_tokens(context_text)

        # Verificar si estamos cerca del límite
        from .tokenizer_utils import is_context_near_limit

        if is_context_near_limit(
            current_tokens=current_tokens,
            max_tokens=self._config.n_ctx,
            reserve_tokens=self._config.context_reserve_tokens,
        ):
            removed = self.trim_memory()
            if removed > 0:
                self._log_debug("MEMORY", f"Auto-trim: {removed} mensaje(s) eliminado(s)")

    def _inject_personality_into_system_prompt(self) -> None:
        """
        Construye el system prompt final combinando el prompt base
        del config con las capas de personalidad del CharacterManager,
        y lo inyecta en la ChatMemory.
        """
        enriched_prompt = self._character_manager.build_system_prompt(
            self._config.system_prompt
        )
        # Solo actualizar si realmente cambió para evitar trabajo innecesario
        if self._memory.system_prompt != enriched_prompt:
            self._memory.system_prompt = enriched_prompt

    def _handle_slash_command(self, text: str) -> Optional[str]:
        """
        Verifica si el texto es un slash command y lo ejecuta.

        Args:
            text: texto del usuario

        Returns:
            Respuesta del comando si se ejecutó, None si no es
            un slash command.
        """
        if not text or not text.startswith("/"):
            return None

        if self._slash_commands.is_slash_command(text):
            self._log_debug("SLASH", f"Ejecutando comando: {text}")
            result = self._slash_commands.handle(text)
            return result

        return None

    def _validate_tool_calls(
        self,
        tool_calls: list[dict],
        tools: list[dict],
    ) -> list[dict]:
        """
        Valida que las tool_calls del modelo correspondan a
        herramientas reales definidas por el usuario.

        Filtra cualquier tool_call cuyo nombre no exista en la
        lista de tools proporcionada. Esto evita que el modelo
        "alucine" nombres de herramientas.

        Args:
            tool_calls: lista de llamadas generadas por el modelo
            tools: lista de definiciones de herramientas del usuario

        Returns:
            Lista filtrada de tool_calls válidas.
        """
        # Extraer nombres válidos de herramientas
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

    def _register_default_slash_commands(self) -> None:
        """
        Registra los slash commands predeterminados del sistema.
        """
        # /mem — Agregar una memoria persistente
        self._slash_commands.register(
            "mem",
            self._cmd_mem,
            "Agrega una memoria persistente. Uso: /mem <texto>",
        )

        # /rebuild — Reconstruir el estado de personalidad
        self._slash_commands.register(
            "rebuild",
            self._cmd_rebuild,
            "Reconstruye el estado de personalidad del agente.",
        )

        # /state — Exportar estado actual como JSON
        self._slash_commands.register(
            "state",
            self._cmd_state,
            "Muestra el estado actual del agente.",
        )

        # /memories — Listar memorias
        self._slash_commands.register(
            "memories",
            self._cmd_memories,
            "Lista todas las memorias persistentes.",
        )

        # /mood — Cambiar estado de ánimo
        self._slash_commands.register(
            "mood",
            self._cmd_mood,
            "Cambia un valor de mood. Uso: /mood <key> <value>",
        )

        # /rel — Cambiar estado de relación
        self._slash_commands.register(
            "rel",
            self._cmd_rel,
            "Modifica o consulta el relationship state. Uso: /rel <trust> <familiarity>",
        )

        # /help — Ayuda de comandos
        self._slash_commands.register(
            "help",
            self._cmd_help,
            "Muestra la lista de comandos disponibles.",
        )
        
        # /scene_view — (Interceptado nativamente, solo para documentación)
        self._slash_commands.register(
            "scene_view",
            lambda _: "Comando procesado por el motor interno.",
            "Obliga al personaje a describir la escena actual, el entorno y sus acciones en detalle inmersivo.",
        )
        
        # /save_episode — Guardar snapshot episódico
        self._slash_commands.register(
            "save_episode",
            self._cmd_save_episode,
            "Guarda un snapshot de la conversación actual como episodio versionado.",
        )

        # /episodes — Listar episodios
        self._slash_commands.register(
            "episodes",
            self._cmd_episodes,
            "Lista todos los episodios guardados. Uso: /episodes [load N | delete N]",
        )

    # ------------------------------------------------------------------
    # Handlers de slash commands
    # ------------------------------------------------------------------

    def _cmd_mem(self, args: str) -> str:
        """Handler para /mem."""
        if not args.strip():
            return "Uso: /mem <texto a recordar>"
        entry = self._character_manager.add_memory(
            content=args.strip(),
            always_include=True,
            priority=1.0,
        )
        return f"✓ Memoria guardada (id: {entry.id}): {entry.content}"

    def _cmd_rebuild(self, args: str) -> str:
        """Handler para /rebuild."""
        self.rebuild_personality_state()
        return "✓ Estado de personalidad reconstruido."

    def _cmd_state(self, args: str) -> str:
        """Handler para /state."""
        state = self.get_state_info()
        return json.dumps(state, ensure_ascii=False, indent=2)

    def _cmd_memories(self, args: str) -> str:
        """Handler para /memories."""
        memories = self._character_manager.memories
        if not memories:
            return "No hay memorias guardadas."
        lines = []
        for m in memories:
            tags = f" [{', '.join(m.tags)}]" if m.tags else ""
            pin = " 📌" if m.always_include else ""
            lines.append(f"  [{m.id}] {m.content}{tags}{pin}")
        return "Memorias:\n" + "\n".join(lines)

    def _cmd_mood(self, args: str) -> str:
        """Handler para /mood (Usa el CharacterMod priority system)."""
        if not args:
            return "Uso: /mood <layer> <value> [intensity] (ej: /mood speech silencioso 1.0)"
        parts = args.split()
        if len(parts) < 2:
            return "Error: Formato incorrecto. Uso: /mood <layer> <value>"
        
        layer = parts[0]
        value = " ".join(parts[1:])
        intensity = 1.0
        # If last part is numeric, use it as intensity
        if len(parts) >= 3:
            try:
                intensity = float(parts[-1])
                value = " ".join(parts[1:-1])
            except ValueError:
                pass

        from .types import CharacterMod
        mod = CharacterMod(id=f"temp_{layer}", target_layer=layer, override_value=value, intensity=intensity)
        self._character_manager.set_mod(mod)
        
        # Update system prompt dynamically
        self._inject_personality_into_system_prompt()
        return f"✓ Mod aplicado a '{layer}': {value} (Intensidad {intensity:.1f})"

    def _cmd_rel(self, args: str) -> str:
        """Handler para /rel (Relationship Engine)."""
        if not args:
            rel = self._character_manager.relationship_state
            return f"Estado de relación actual:\nConfianza: {rel.trust_level:.2f}\nFamiliaridad: {rel.familiarity:.2f}"
        
        parts = args.split()
        if len(parts) == 2:
            try:
                trust = float(parts[0])
                fam = float(parts[1])
                self._character_manager.relationship_state.trust_level = trust
                self._character_manager.relationship_state.familiarity = fam
                self._character_manager.save_state()
                return f"✓ Relación actualizada: Trust={trust:.2f}, Familiarity={fam:.2f}"
            except ValueError:
                pass
        return "Uso: /rel <trust> <familiarity> (ej: /rel 0.8 0.5)"

    def _cmd_help(self, args: str) -> str:
        """Handler para /help."""
        return self._slash_commands.get_help_text()

    def _cmd_save_episode(self, args: str) -> str:
        """Handler para /save_episode."""
        try:
            episode = self.save_episode()
            return f"✓ Episodio #{episode.episode_id} guardado. Resumen: {episode.summary[:100]}..."
        except Exception as e:
            return f"Error al guardar episodio: {e}"

    def _cmd_episodes(self, args: str) -> str:
        """Handler para /episodes."""
        parts = args.strip().split() if args else []
        
        # /episodes load N
        if len(parts) == 2 and parts[0] == "load":
            try:
                ep_id = int(parts[1])
                self._character_manager.load_episode(ep_id)
                self._inject_personality_into_system_prompt()
                return f"✓ Episodio #{ep_id} restaurado (rollback)."
            except (ValueError, Exception) as e:
                return f"Error: {e}"
        
        # /episodes delete N
        if len(parts) == 2 and parts[0] == "delete":
            try:
                ep_id = int(parts[1])
                ok = self._character_manager.delete_episode(ep_id)
                return f"✓ Episodio #{ep_id} eliminado." if ok else f"Episodio #{ep_id} no encontrado."
            except (ValueError, Exception) as e:
                return f"Error: {e}"
        
        # /episodes (listar)
        episodes = self._character_manager.list_episodes()
        if not episodes:
            return "No hay episodios guardados."
        lines = ["Episodios guardados:"]
        for ep in episodes:
            current = " ← actual" if (self._character_manager.current_episode and ep["episode_id"] == self._character_manager.current_episode.episode_id) else ""
            lines.append(f"  #{ep['episode_id']:03d} [{ep['timestamp'][:16]}] ({ep['message_count']} msgs) {ep['summary']}{current}")
        lines.append("\nUso: /episodes load N | /episodes delete N")
        return "\n".join(lines)

    def _log_generation_stats(self) -> None:
        """Muestra estadísticas de la última generación si debug está activo."""
        if not self._log_manager.debug_enabled:
            return

        stats = self._stats.current
        if stats is None:
            return

        self._log_manager.debug(
            "CHAT",
            f"Inferencia completada en {stats.duration_ms:.1f}ms "
            f"| prompt: {stats.prompt_tokens}tok "
            f"| completion: {stats.completion_tokens}tok "
            f"| total: {stats.total_tokens}tok"
        )
        self._log_manager.debug(
            "TOKENS",
            f"Velocidad: {stats.tokens_per_second} tok/s "
            f"| Total generado: {self._stats.total_tokens_generated} tokens"
        )

        # Mostrar uso de contexto
        if self._model_manager.is_loaded:
            context_text = " ".join(
                m.content for m in self._memory.messages if m.content
            )
            ctx_tokens = self._model_manager.count_tokens(context_text)
            self._log_manager.debug(
                "MEMORY",
                f"Contexto: {ctx_tokens}/{self._config.n_ctx} tokens "
                f"({(ctx_tokens / self._config.n_ctx * 100):.1f}%) "
                f"| Mensajes: {len(self._memory.messages)}"
            )

    # ======================================================================
    # LOGGING INTERNO
    # ======================================================================

    def _log_debug(self, tag: str, message: str) -> None:
        """Envía mensaje de debug al logger."""
        if self._log_manager:
            self._log_manager.debug(tag, message)

    def _log_info(self, message: str) -> None:
        """Envía mensaje informativo al logger."""
        if self._log_manager:
            self._log_manager.info(message)

    def _log_warning(self, message: str) -> None:
        """Envía advertencia al logger."""
        if self._log_manager:
            self._log_manager.warning(message)

    def _log_error(self, message: str) -> None:
        """Envía error al logger."""
        if self._log_manager:
            self._log_manager.error(message)

    # ======================================================================
    # CONTEXTO (Context Manager)
    # ======================================================================

    def __enter__(self) -> "VToolLlama":
        """Soporte para 'with VToolLlama() as llm:'."""
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Al salir del contexto, guardar episodio y descargar el modelo si está configurado."""
        # Auto-guardar episodio si hay conversación
        try:
            non_system = [m for m in self._memory.messages if m.role != "system"]
            if non_system and self._character_manager.is_loaded:
                self.save_episode()
                self._log_debug("EPISODE", "Episodio auto-guardado al cerrar.")
        except Exception as e:
            self._log_warning(f"No se pudo auto-guardar episodio al cerrar: {e}")
        
        if self._config.auto_unload_model:
            self.unload_model()

    # ======================================================================
    # REPR
    # ======================================================================

    def __repr__(self) -> str:
        """Representación legible de la instancia."""
        loaded = self._model_manager.is_loaded
        model_name = self._model_manager.model_info.model_name if loaded else "No cargado"
        context = self._config.n_ctx
        messages = len(self._memory.messages)

        return (
            f"VToolLlama(modelo='{model_name}', "
            f"contexto={context}, "
            f"mensajes={messages}, "
            f"cargado={loaded})"
        )
