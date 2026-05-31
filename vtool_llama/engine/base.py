"""
Motor principal de vtool_llama — Core.

Expone la clase VToolLlama, que es la interfaz pública de toda
la librería. Los métodos específicos se definen en módulos
hermanos (chat.py, character.py, memory.py, etc.) y se asignan
a esta clase.

Uso esperado:
    from vtool_llama import VToolLlama

    llm = VToolLlama()

    respuesta = llm.chat("Hola, ¿cómo estás?")
    print(respuesta)
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Optional

from .chat_memory import ChatMemory
from .config_manager import ConfigManager
from ..db import ChatStore
from ..exceptions import (
    ConfigError,
)
from .logger_manager import LoggerManager
from ..model import ModelManager
from .slash_registry import SlashCommandRegistry
from ..character import CharacterManager
from .stats_manager import StatsManager
from ..types import Branch, ChatMessage, ConfigSchema
from ..utils import TokenCounter
from ..soul import SoulGenerator
from ..tools import (
    ToolExecutionManager,
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
        chars_dir = self._config.characters_directory or None
        self._character_manager = CharacterManager(
            base_dir=chars_dir,
            logger_fn=self._log_debug,
        )

        # ------------------------------------------------------------------
        # 6b. Inicializar Tool Execution Manager
        # ------------------------------------------------------------------
        self._tool_manager = ToolExecutionManager(
            add_memory_fn=self._character_manager.add_memory,
            log_info_fn=self._log_info,
            log_debug_fn=self._log_debug,
        )
        self._scene_requested = False

        # ------------------------------------------------------------------
        # 6c. Inicializar Soul System (opcional)
        # ------------------------------------------------------------------
        self._soul_generator = SoulGenerator(
            character_manager=self._character_manager,
            model_manager=self._model_manager,
            config=self._config,
            log_debug_fn=self._log_debug,
            log_info_fn=self._log_info,
            log_warning_fn=self._log_warning,
        )

        # ------------------------------------------------------------------
        # 6d. ChromaDB semántico (opcional, manual)
        # ------------------------------------------------------------------
        self._semantic_chroma = None
        self._semantic_saving = False

        # ------------------------------------------------------------------
        # 6e. Flag de carga de personaje
        # ------------------------------------------------------------------
        self._loading: bool = False
        self._archive_retries: int = 0

        # ------------------------------------------------------------------
        # 6f. Tag del usuario para identidad en mensajes (v13)
        # ------------------------------------------------------------------
        self._user_tag: str = "PLAYER"

        # ------------------------------------------------------------------
        # 6g. Buffer para #char (pensamiento del personaje)
        # ------------------------------------------------------------------
        self._char_thought_buffer: list[tuple[str, str]] = []

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
        # 8b. Inline Processor (v15)
        # ------------------------------------------------------------------
        from .inline import InlineProcessor, register_default_hash_commands
        self._inline_processor = InlineProcessor()
        register_default_hash_commands(self._inline_processor)

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
    # API PÚBLICA — MODELO
    # ======================================================================

    def load_model(self, model_path: Optional[str] = None) -> None:
        with self._lock:
            self._model_manager.load_model(model_path)

    def reload_model(self) -> None:
        with self._lock:
            self._model_manager.reload_model()

    def unload_model(self) -> None:
        with self._lock:
            self._model_manager.unload_model()

    def switch_model(self, model_path: str) -> None:
        with self._lock:
            self._model_manager.switch_model(model_path)

    def get_model_info(self) -> dict:
        return self._model_manager.get_model_info()

    def list_available_models(self) -> list[dict[str, str]]:
        with self._lock:
            return self._model_manager.list_available_models()

    def supports_tools(self) -> bool:
        return self._model_manager.supports_tools()

    def generate_raw(self, messages: list[dict], **kwargs) -> Any:
        """Genera una respuesta con el modelo SIN system prompt ni inyección de personalidad.
        Útil para procesar DNA, traducciones, mejoras de personaje, etc.

        Args:
            messages: lista de dicts con role y content (formato OpenAI)
            **kwargs: max_tokens, temperature, top_p, etc.
        """
        with self._lock:
            return self._model_manager.generate(messages=messages, **kwargs)

    @property
    def model_loading(self) -> bool:
        return self._model_manager.loading

    # ======================================================================
    # API PÚBLICA — CONFIGURACIÓN
    # ======================================================================

    def get_config(self) -> ConfigSchema:
        return self._config

    def reload_config(self) -> None:
        with self._lock:
            self._config = self._config_manager.reload()
            self._memory.system_prompt = self._config.system_prompt
            self._memory._history_limit = self._config.history_limit
        self._log_debug("CONFIG", "Configuración recargada desde archivo")

    # ======================================================================
    # API PÚBLICA — DEBUG
    # ======================================================================

    def enable_debug(self) -> None:
        self._log_manager.enable_debug()
        self._config.enable_console_debug = True

    def disable_debug(self) -> None:
        self._config.enable_console_debug = False
        self._log_manager.disable_debug()

    # ======================================================================
    # PROPIEDADES PÚBLICAS
    # ======================================================================

    @property
    def state_manager(self) -> CharacterManager:
        return self._character_manager

    @property
    def slash_commands(self) -> SlashCommandRegistry:
        return self._slash_commands

    @property
    def chat_store(self) -> Optional[ChatStore]:
        return getattr(self, '_chat_store', None)

    @property
    def token_counter(self) -> Optional[TokenCounter]:
        return getattr(self, '_token_counter', None)

    @property
    def semantic_saving(self) -> bool:
        return self._semantic_saving

    @property
    def loading(self) -> bool:
        """Indica si hay una carga de personaje en curso."""
        return self._loading

    def get_tool_stats(self) -> dict:
        """Retorna métricas de uso de herramientas del character actual."""
        return dict(self._tool_manager.stats)

    def checkout(self, branch_id: str, leaf_message_id: int) -> None:
        """Rollback no destructivo a un branch + mensaje específico."""
        if not self._chat_store or not self._memory._conversation_id:
            raise RuntimeError("No hay ChatStore activo. Cargá un personaje primero.")
        self._chat_store.checkout(self._memory._conversation_id, branch_id, leaf_message_id)
        self._memory._branch_id = branch_id
        self._memory._active_leaf_id = leaf_message_id
        self.mark_semantic_dirty()
        self._log_debug("CHECKOUT", f"Checkout a {branch_id} @ msg {leaf_message_id}")

    def delete_message(self, message_id: int) -> None:
        """Soft-delete de un mensaje del historial."""
        if not self._chat_store:
            raise RuntimeError("No hay ChatStore activo.")
        self._chat_store.soft_delete_message(message_id)
        self.mark_semantic_dirty()
        self._log_debug("CHAT", f"Mensaje {message_id} marcado como eliminado.")

    def regenerate_response(self, message_id: int, label: str = "") -> str:
        """Regenera desde un mensaje: crea branch, checkout, retorna branch_id."""
        if not self._chat_store or not self._memory._conversation_id:
            raise RuntimeError("No hay ChatStore activo.")
        branch_id = self._chat_store.create_branch(
            self._memory._conversation_id, message_id, label=label or f"Regenerado desde msg {message_id}",
        )
        self._chat_store.checkout(self._memory._conversation_id, branch_id, message_id)
        self._memory._branch_id = branch_id
        self._memory._active_leaf_id = message_id
        self.mark_semantic_dirty()
        self._log_debug("BRANCH", f"Branch '{branch_id}' creado desde msg {message_id}")
        return branch_id

    def get_conversation_tree(self) -> list[Branch]:
        """Lista todas las ramas de la conversación actual."""
        if not self._chat_store or not self._memory._conversation_id:
            return []
        return self._chat_store.get_branches(self._memory._conversation_id)

    def get_message_path(self, leaf_message_id: int) -> list[ChatMessage]:
        """Reconstruye el camino desde la raíz hasta leaf."""
        if not self._chat_store:
            return []
        return self._chat_store.get_message_path(leaf_message_id)

    def get_chat_history(self, limit: int = 100, include_context: bool = False) -> list[dict]:
        """Retorna el historial de la conversación activa como list[dict].
        Cada dict tiene: id, role, content, status, created_at, branch_id.

        Args:
            limit: cantidad máxima de mensajes
            include_context: si es True, incluye mensajes role='context'
        """
        if not self._chat_store or not self._memory._conversation_id:
            return []
        messages = self._chat_store.get_active_branch_messages(
            self._memory._conversation_id,
            self._memory._branch_id,
            self._memory._active_leaf_id,
            limit=limit,
        )
        result = []
        for m in messages:
            if not include_context and m.role == "context":
                continue
            result.append({
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "status": m.status,
                "created_at": m.created_at,
                "branch_id": m.branch_id,
                "message_index": m.message_index,
            })
        return result

    def get_token_usage(self) -> dict:
        """Retorna estadísticas de uso de tokens del contexto actual.

        Returns:
            dict con:
              - system_tokens: tokens del system prompt
              - history_tokens: tokens del historial (sin system)
              - total_tokens: tokens del prompt actual
              - max_tokens: n_ctx configurado
              - reserved: context_reserve_tokens
              - effective_context_limit: max_tokens - reserved
              - prompt_budget_available: tokens disponibles para mas prompt/contexto manteniendo la reserva
              - response_capacity: tokens maximos que aun caben para la respuesta antes de n_ctx
              - safe_max_response_tokens: min(config.max_tokens, response_capacity)
              - budget_available: alias legacy de prompt_budget_available
              - usage_pct: porcentaje usado (0-100)
              - messages: cantidad de mensajes en RAM
        """
        # Si el core está expandido (v8), reportamos el n_ctx del usuario,
        # no el n_ctx real del modelo (que es user_n_ctx + n_keep)
        max_tokens = self._config.n_ctx
        if self._model_manager._core_expanded and self._model_manager._user_n_ctx:
            max_tokens = self._model_manager._user_n_ctx
        reserved = self._config.context_reserve_tokens
        configured_max_response = max(0, int(getattr(self._config, "max_tokens", 0) or 0))

        def _count(text: str) -> int:
            if not text:
                return 0
            if self._model_manager.is_loaded:
                return self._model_manager.count_tokens(text)
            return max(1, round(len(text) / 4))

        def _count_messages(messages: list[dict]) -> int:
            if not messages:
                return 0
            if self._model_manager.is_loaded and hasattr(self._model_manager, "count_messages_tokens"):
                return self._model_manager.count_messages_tokens(messages)
            text = " ".join(m.get("content", "") for m in messages if m.get("content"))
            return _count(text)

        system_text = ""
        history_text = ""
        system_messages = []
        history_messages = []
        for m in self._memory.messages:
            if m.role == "system" and m.content:
                system_text += " " + m.content
                system_messages.append({"role": m.role, "content": m.content})
            elif m.content:
                history_text += " " + m.content
                history_messages.append({"role": m.role, "content": m.content})

        all_messages = system_messages + history_messages
        system_tokens = _count_messages(system_messages) if system_messages else _count(system_text)
        history_tokens = _count_messages(history_messages) if history_messages else _count(history_text)
        # Si el core está expandido (v8), el system prompt no descuenta del presupuesto
        core_expanded = self._model_manager._core_expanded and self._model_manager._user_n_ctx
        total_tokens = history_tokens if core_expanded else (_count_messages(all_messages) if all_messages else 0)
        effective_context_limit = max(0, max_tokens - reserved)
        prompt_budget_available = max(0, effective_context_limit - total_tokens)
        response_capacity = max(0, max_tokens - total_tokens)
        safe_max_response_tokens = min(configured_max_response, response_capacity) if configured_max_response else response_capacity
        usage_pct = round((total_tokens / max_tokens) * 100, 1) if max_tokens > 0 else 0
        effective_usage_pct = round((total_tokens / effective_context_limit) * 100, 1) if effective_context_limit > 0 else 100.0
        # Métricas del KV cache real (plan v6)
        n_keep = getattr(self._model_manager, "_n_keep", None) or 0
        kv_cache_tokens = 0
        if self._model_manager.is_loaded:
            raw = getattr(self._model_manager._model, "n_tokens", None)
            if isinstance(raw, (int, float)):
                kv_cache_tokens = int(raw)
        kv_cache_usage_pct = (
            round((kv_cache_tokens / max_tokens) * 100, 1)
            if max_tokens > 0 and kv_cache_tokens > 0
            else 0.0
        )

        system_full_tokens = system_tokens
        system_compact_tokens = system_tokens
        if self._character_manager.is_loaded:
            try:
                count_fn = self._model_manager.count_tokens if self._model_manager.is_loaded else None
                full_prompt = self._character_manager.build_full_system_prompt(self._config.system_prompt, self._config)
                compact_prompt = self._character_manager.build_compact_system_prompt(self._config.system_prompt, self._config)
                system_full_tokens = _count_messages([{"role": "system", "content": full_prompt}]) if count_fn else _count(full_prompt)
                system_compact_tokens = _count_messages([{"role": "system", "content": compact_prompt}]) if count_fn else _count(compact_prompt)
            except Exception:
                system_full_tokens = system_tokens
                system_compact_tokens = system_tokens

        result = {
            "system_tokens": system_tokens,
            "system_full_tokens": system_full_tokens,
            "system_compact_tokens": system_compact_tokens,
            "system_saved_tokens": max(0, system_full_tokens - system_compact_tokens),
            "history_tokens": history_tokens,
            "prompt_tokens": total_tokens,
            "total_tokens": total_tokens,
            "max_tokens": max_tokens,
            "reserved": reserved,
            "effective_context_limit": effective_context_limit,
            "prompt_budget_available": prompt_budget_available,
            "available_context_tokens": prompt_budget_available,
            "response_capacity": response_capacity,
            "safe_max_response_tokens": safe_max_response_tokens,
            "budget_available": prompt_budget_available,
            "usage_pct": usage_pct,
            "effective_usage_pct": effective_usage_pct,
            "context_over_budget": total_tokens > effective_context_limit,
            "can_generate_reserved": response_capacity >= reserved,
            "messages": len(self._memory.messages),
            "n_keep": n_keep,
            "kv_cache_tokens": kv_cache_tokens,
            "kv_cache_usage_pct": kv_cache_usage_pct,
        }

        return result

    def get_prompt_layer_usage(self) -> dict:
        """Retorna tokens por capa del prompt del personaje actual."""
        count_fn = self._model_manager.count_tokens if self._model_manager.is_loaded else None
        breakdown = self._character_manager.get_prompt_layer_breakdown(
            self._config.system_prompt,
            count_fn=count_fn,
            config=self._config,
        )
        max_tokens = self._config.n_ctx
        effective_limit = max(0, max_tokens - self._config.context_reserve_tokens)
        breakdown["max_tokens"] = max_tokens
        breakdown["reserved"] = self._config.context_reserve_tokens
        breakdown["effective_context_limit"] = effective_limit
        breakdown["static_usage_pct"] = (
            round((breakdown["static_tokens"] / max_tokens) * 100, 1)
            if max_tokens > 0 else 0
        )
        breakdown["static_effective_usage_pct"] = (
            round((breakdown["static_tokens"] / effective_limit) * 100, 1)
            if effective_limit > 0 else 100.0
        )
        breakdown["conversation_budget_after_static"] = max(0, effective_limit - breakdown["static_tokens"])
        if self._character_manager.is_loaded:
            compact_prompt = self._character_manager.build_compact_system_prompt(self._config.system_prompt, self._config)
            count_fn = self._model_manager.count_tokens if self._model_manager.is_loaded else None
            compact_tokens = count_fn(compact_prompt) if count_fn else max(1, round(len(compact_prompt) / 4))
            breakdown["compact_static_tokens"] = compact_tokens
            breakdown["compact_saves_tokens"] = max(0, breakdown["static_tokens"] - compact_tokens)
            breakdown["conversation_budget_after_compact"] = max(0, effective_limit - compact_tokens)
        return breakdown

    def mark_semantic_dirty(self) -> None:
        """Marca la conversación actual para rebuild semántico.
        Se llama automáticamente en checkout, delete_message y regenerate_response."""
        if self._chat_store and self._memory._conversation_id:
            self._chat_store.mark_semantic_dirty(self._memory._conversation_id)

    def _auto_index_if_needed(self) -> None:
        """Indexa automáticamente si se superó el umbral o si está sucio."""
        if not self._chat_store or not self._memory._conversation_id or not self._semantic_chroma or not self._semantic_chroma.is_available:
            return

        try:
            sync = self._chat_store.get_semantic_sync(self._memory._conversation_id)
            is_dirty = bool(sync.get("dirty", 1))

            if is_dirty:
                self._log_debug("SEMANTIC", "Auto-indexado: Rebuild necesario por dirty flag.")
                self.index_conversation(incremental=False)
                return

            last_id = sync.get("last_synced_message_id", 0)
            new_msgs = self._chat_store.get_branch_messages_since(
                self._memory._conversation_id, self._memory._branch_id, since_id=last_id, limit=50
            )

            # Auto-indexar si hay al menos 10 mensajes nuevos (~5 turnos)
            if len(new_msgs) >= 10:
                self._log_debug("SEMANTIC", f"Auto-indexado: Iniciando indexado incremental con {len(new_msgs)} mensajes nuevos.")
                self.index_conversation(incremental=True)
        except Exception as e:
            self._log_warning(f"Error en auto-indexado semántico: {e}")

    def index_conversation(self, incremental: bool = True) -> int:
        if self._semantic_saving:
            self._log_debug("SEMANTIC", "Ya hay un indexado en curso, ignorando.")
            return 0
        self._semantic_saving = True
        try:
            return self._index_conversation_impl(incremental)
        finally:
            self._semantic_saving = False

    def _index_conversation_impl(self, incremental: bool = True) -> int:
        """Indexa la conversación activa en ChromaDB como chunks semánticos.
        Si incremental=True, solo indexa mensajes nuevos desde el último sync.
        Si incremental=False o hay dirty flag, rebuild completo.

        Retorna cantidad de chunks indexados.
        """
        if not self._chat_store or not self._memory._conversation_id:
            raise RuntimeError("No hay ChatStore activo.")

        sync = self._chat_store.get_semantic_sync(self._memory._conversation_id)
        rebuild = not incremental or sync.get("dirty", 1)

        conv = self._chat_store.get_conversation(self._memory._conversation_id)
        if not self._semantic_chroma:
            self._log_warning("ChromaDB no configurado para memoria semántica.")
            return 0

        if rebuild:
            self._log_debug("SYNC", "Rebuild completo del índice semántico.")
            self._semantic_chroma.clear()
            last_id = 0
        else:
            last_id = sync.get("last_synced_message_id", 0)
            self._log_debug("SYNC", f"Sync incremental desde message_id {last_id}")

        # Obtener mensajes nuevos
        new_msgs = self._chat_store.get_branch_messages_since(
            self._memory._conversation_id, self._memory._branch_id, since_id=last_id, limit=500
        )
        if not new_msgs:
            return 0

        # Agrupar en chunks de ~10 mensajes
        chunk_size = 10
        indexed = 0

        for i in range(0, len(new_msgs), chunk_size):
            chunk = new_msgs[i:i + chunk_size]
            text = "\n".join(f"{m.role}: {m.content}" for m in chunk if m.content)
            if not text.strip():
                continue

            doc_id = (
                f"conv_{self._memory._conversation_id}_"
                f"{self._memory._branch_id}_{chunk[0].id}_{chunk[-1].id}"
            )
            self._semantic_chroma.add_document(
                doc_id=doc_id,
                document=f"[Conversación - {conv.character_name}]\n{text}",
                metadata={
                    "conversation_id": self._memory._conversation_id,
                    "start_id": chunk[0].id,
                    "end_id": chunk[-1].id,
                    "branch_id": self._memory._branch_id,
                },
            )
            indexed += 1

        # Actualizar sync state
        import hashlib
        last_msg_id = new_msgs[-1].id
        sync_payload = "|".join(
            f"{m.id}:{m.branch_id}:{m.role}:{hashlib.sha256((m.content or '').encode('utf-8')).hexdigest()}"
            for m in new_msgs
        )
        sync_hash = hashlib.sha256(sync_payload.encode("utf-8")).hexdigest()[:12]
        self._chat_store.update_semantic_sync(
            self._memory._conversation_id,
            last_msg_id,
            self._memory._branch_id,
            sync_hash,
        )

        self._log_debug("SYNC", f"Indexados {indexed} chunks semánticos (hasta msg {last_msg_id}).")
        return indexed

    def rebuild_semantic_memory(self) -> int:
        """Forza rebuild completo del índice semántico."""
        return self.index_conversation(incremental=False)

    # ======================================================================
    # LOGGING INTERNO
    # ======================================================================

    def _log_debug(self, tag: str, message: str) -> None:
        if hasattr(self, "_log_manager") and self._log_manager:
            self._log_manager.debug(tag, message)
        # También al character_log.md si el debug_logger existe
        deb = getattr(self, "_debug_logger", None)
        if deb and deb._enabled and tag in ("SQLITE", "CHROMA", "STATE", "MODEL", "TOOL"):
            deb.log_event(tag, message)

    def _log_info(self, message: str) -> None:
        if hasattr(self, "_log_manager") and self._log_manager:
            self._log_manager.info(message)

    def _log_warning(self, message: str) -> None:
        if hasattr(self, "_log_manager") and self._log_manager:
            self._log_manager.warning(message)
        else:
            print(f"WARN: {message}")

    def _log_error(self, message: str) -> None:
        if hasattr(self, "_log_manager") and self._log_manager:
            self._log_manager.error(message)
        else:
            print(f"ERROR: {message}")

    # ======================================================================
    # CONTEXTO (Context Manager)
    # ======================================================================

    def __enter__(self) -> "VToolLlama":
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
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
