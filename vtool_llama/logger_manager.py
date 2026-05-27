"""
Gestor de logging y debug para vtool_llama.

Proporciona:
- Logging a archivo con rotación por día
- Debug en consola con colores (usando colorama + rich)
- Formato consistente con marcas de tiempo
- Niveles: DEBUG, INFO, WARNING, ERROR

Cuando debug está activado, se muestran bloques como:
  [MODEL]  modelo cargado
  [GPU]    VRAM estimada: 6.8 GB
  [CHAT]   inferencia completada en 2.3s
  [TOKENS] 45.2 tokens/s
  [MEMORY] uso de contexto: 1560/4096 tokens

Cuando debug está desactivado, solo se registran warnings/errores.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional


# Niveles personalizados para los "tags" del debug
DEBUG_TAGS = {
    "MODEL": "\033[36m[MODEL]\033[0m",      # Cyan
    "GPU": "\033[35m[GPU]\033[0m",          # Magenta
    "CHAT": "\033[32m[CHAT]\033[0m",        # Verde
    "TOKENS": "\033[33m[TOKENS]\033[0m",    # Amarillo
    "MEMORY": "\033[34m[MEMORY]\033[0m",    # Azul
    "CONFIG": "\033[37m[CONFIG]\033[0m",    # Blanco
    "ERROR": "\033[31m[ERROR]\033[0m",      # Rojo
}


class LoggerManager:
    """
    Configura y expone el sistema de logging.

    Args:
        logs_dir: directorio donde guardar los archivos .log
        enable_file_logging: si es True, escribe logs a archivo
        debug_enabled: si es True, muestra mensajes de debug en
                       consola con colores
        component: nombre del componente (ej: "engine", "model_manager")
    """

    def __init__(
        self,
        logs_dir: str | Path | None = None,
        enable_file_logging: bool = True,
        debug_enabled: bool = False,
        component: str = "vtool_llama",
    ):
        self._logs_dir = Path(logs_dir) if logs_dir else (Path("logs") if enable_file_logging else None)
        self._component = component
        self._debug_enabled = debug_enabled
        self._enable_file_logging = enable_file_logging
        self._logger: Optional[logging.Logger] = None

        self._setup_logger()

    # ------------------------------------------------------------------
    # Configuración interna
    # ------------------------------------------------------------------

    def _setup_logger(self) -> None:
        """
        Crea y configura el logger raíz del componente.

        - Crea el directorio de logs si no existe
        - Agrega un handler de archivo con rotación diaria
        - El handler de consola se controla según debug_enabled
        """
        self._logger = logging.getLogger(f"vtool_llama.{self._component}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Handler de archivo con rotación diaria
        if self._enable_file_logging and self._logs_dir is not None:
            self._logs_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            log_file = self._logs_dir / f"chat_{today}.log"

            file_handler = TimedRotatingFileHandler(
                filename=str(log_file),
                when="midnight",
                interval=1,
                backupCount=30,       # mantener 30 días de historial
                encoding="utf-8",
                delay=False,
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)

    # ------------------------------------------------------------------
    # Métodos de logging con tags
    # ------------------------------------------------------------------

    def debug(self, tag: str, message: str) -> None:
        """
        Envía un mensaje de debug con un tag de color.

        Solo se muestra en consola si debug_enabled=True.
        Siempre se escribe al archivo de log.

        Args:
            tag: una de las claves de DEBUG_TAGS (MODEL, GPU, etc.)
            message: texto del mensaje
        """
        if self._logger is None:
            return
        self._logger.debug(f"[{tag}] {message}")

        # Salida coloreada a consola
        if self._debug_enabled:
            colored_tag = DEBUG_TAGS.get(tag, f"[{tag}]")
            print(f"{colored_tag} {message}", file=sys.stderr)

    def info(self, message: str) -> None:
        """Mensaje informativo (siempre al archivo, solo si debug a consola)."""
        if self._logger is None:
            return
        self._logger.info(message)
        if self._debug_enabled:
            print(f"\033[32m[INFO]\033[0m {message}", file=sys.stderr)

    def warning(self, message: str) -> None:
        """Advertencia (siempre visible)."""
        if self._logger is None:
            return
        self._logger.warning(message)
        print(f"\033[33m[WARN]\033[0m {message}", file=sys.stderr)

    def error(self, message: str) -> None:
        """Error (siempre visible, en rojo)."""
        if self._logger is None:
            return
        self._logger.error(message)
        print(f"\033[31m[ERROR]\033[0m {message}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Control de debug en runtime
    # ------------------------------------------------------------------

    def enable_debug(self) -> None:
        """Activa la salida de debug en consola."""
        self._debug_enabled = True
        self.debug("CONFIG", "Debug de consola activado")

    def disable_debug(self) -> None:
        """Desactiva la salida de debug en consola."""
        self.debug("CONFIG", "Debug de consola desactivado")
        self._debug_enabled = False

    @property
    def debug_enabled(self) -> bool:
        return self._debug_enabled

    @debug_enabled.setter
    def debug_enabled(self, value: bool) -> None:
        if value:
            self.enable_debug()
        else:
            self.disable_debug()

    @property
    def logger(self) -> logging.Logger:
        """El logger subyacente de Python logging."""
        return self._logger
