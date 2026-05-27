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
    SCENE_PROMPT,
    parse_text_tool_calls,
    strip_text_tool_calls,
    execute_text_tool,
    TEXT_TOOL_RE,
    find_tool_pattern_start,
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
                    if not tool_calls and not memory_saved:
                        text_tools = parse_text_tool_calls(response_text)
                        if text_tools:
                            internal_call_found = False
                            external_calls = []
                            for fn_name, fn_args_text in text_tools:
                                if fn_name == "remember_memory":
                                    execute_text_tool(fn_name, fn_args_text, self.add_memory, self._log_info)
                                    memory_saved = True
                                    internal_call_found = True
                                elif fn_name == "describe_scene":
                                    execute_text_tool(fn_name, fn_args_text, self.add_memory, self._log_info)
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

                    # --- Limpiar full_response de tool calls en texto plano ---
                    # El buffering en línea ya reemplazó los patrones por
                    # mensajes amigables, pero full_response aún los contiene
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
