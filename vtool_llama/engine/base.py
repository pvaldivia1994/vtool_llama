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

import json
import os
import re
import threading
from collections import deque
from pathlib import Path
from typing import Any, Callable, Generator, Optional

from .chat_memory import ChatMemory
from .config_manager import ConfigManager
from ..exceptions import (
    ConfigError,
    EmptyPromptError,
    InferenceError,
    ModelNotLoadedError,
    VToolLlamaError,
)
from .logger_manager import LoggerManager
from ..model import ModelManager
from .slash_registry import SlashCommandRegistry
from ..character import CharacterManager
from .stats_manager import StatsManager
from ..types import ConfigSchema, EpisodeSnapshot, GenerationStats, ModelInfo, PersonalityState
from ..soul import SoulGenerator, RuntimeSoulAccessor
from ..tools import (
    INTERNAL_TOOLS,
    SCENE_SYSTEM_COMMAND,
    TOOL_USAGE_POLICY,
    ToolExecutionManager,
    StreamPostProcessor,
    parse_text_tool_calls,
    strip_text_tool_calls,
    execute_text_tool,
    has_memory_trigger,
    has_scene_trigger,
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

    # ======================================================================
    # LOGGING INTERNO
    # ======================================================================

    def _log_debug(self, tag: str, message: str) -> None:
        if self._log_manager:
            self._log_manager.debug(tag, message)

    def _log_info(self, message: str) -> None:
        if self._log_manager:
            self._log_manager.info(message)

    def _log_warning(self, message: str) -> None:
        if self._log_manager:
            self._log_manager.warning(message)

    def _log_error(self, message: str) -> None:
        if self._log_manager:
            self._log_manager.error(message)

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
