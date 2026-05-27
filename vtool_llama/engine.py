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
import threading
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
from .stats_manager import StatsManager
from .types import ConfigSchema, GenerationStats, ModelInfo


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
        # 6. Cargar modelo automáticamente si se solicita
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
            texto de la respuesta del asistente (str) o el diccionario de mensaje si llama a una herramienta (dict)

        Raises:
            EmptyPromptError: si el prompt está vacío
            ModelNotLoadedError: si no hay modelo cargado
            InferenceError: si falla la generación
        """
        self._validate_prompt(prompt)

        with self._lock:
            # Agregar mensaje del usuario al historial
            self._memory.add_user_message(prompt)

            # Auto-trim si está activado
            self._auto_trim_if_needed()

            # Obtener mensajes para el contexto
            messages = self._memory.get_context_messages()

            # Medir tiempo de inferencia
            self._stats.begin_generation()

            try:
                # Generar respuesta (sin streaming)
                result = self._model_manager.generate(
                    messages=messages,
                    stream=False,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repeat_penalty=repeat_penalty,
                    tools=tools,
                    tool_choice=tool_choice,
                )

                # Extraer el mensaje y sus componentes
                msg_choice = result["choices"][0]["message"]
                response_text = msg_choice.get("content") or ""
                tool_calls = msg_choice.get("tool_calls", None)

                # Registrar estadísticas
                self._record_stats(result)

                # Agregar respuesta al historial
                self._memory.add_assistant_message(content=response_text, tool_calls=tool_calls)

                # Debug: mostrar tiempo y tokens
                self._log_generation_stats()

                # Si el modelo decidió llamar a una herramienta, devolvemos el objeto mensaje
                if tool_calls:
                    return msg_choice
                return response_text

            except ModelNotLoadedError:
                raise
            except Exception as e:
                raise InferenceError(f"Error en chat(): {e}") from e

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

        with self._lock:
            # Agregar mensaje del usuario al historial
            self._memory.add_user_message(prompt)

            # Auto-trim si está activado
            self._auto_trim_if_needed()

            # Obtener mensajes para el contexto
            messages = self._memory.get_context_messages()

            # Medir tiempo de inferencia
            self._stats.begin_generation()

            try:
                # Generar respuesta con streaming
                stream = self._model_manager.generate(
                    messages=messages,
                    stream=True,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repeat_penalty=repeat_penalty,
                    tools=tools,
                    tool_choice=tool_choice,
                )

                # Acumular la respuesta completa o los tool calls para el historial
                full_response = ""
                tool_calls_chunks = []
                for chunk in stream:
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    # Si hay tool_calls en el delta
                    if "tool_calls" in delta and delta["tool_calls"]:
                        tool_calls_chunks.append(delta["tool_calls"])
                        yield chunk
                    else:
                        token = delta.get("content", "")
                        if token:
                            full_response += token
                            yield token

                # Reconstruir tool_calls si hubo streaming de herramientas
                final_tool_calls = None
                if tool_calls_chunks:
                    # Agrupar los fragmentos de tool_calls
                    final_tool_calls = self._reconstruct_tool_calls(tool_calls_chunks)

                # Registrar estadísticas desde el último chunk
                self._record_stats_from_stream(stream, full_response)

                # Agregar respuesta completa o tool_calls al historial
                self._memory.add_assistant_message(content=full_response or None, tool_calls=final_tool_calls)

                # Debug: mostrar tiempo y tokens
                self._log_generation_stats()

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
            m.content for m in self._memory.messages
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
                m.content for m in self._memory.messages
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
        """Al salir del contexto, descargar el modelo si está configurado."""
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
