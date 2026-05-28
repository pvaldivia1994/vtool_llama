"""
Gestor de configuración para vtool_llama.

Responsabilidades:
- Cargar config.json desde la ruta por defecto o una personalizada
- Validar que todas las claves obligatorias existan
- Proveer acceso tipado a la configuración (usando ConfigSchema)
- Recargar configuración en caliente si cambia

Flujo:
1. El usuario (o engine) crea ConfigManager con una ruta opcional
2. load() lee y valida el JSON
3. get() retorna un ConfigSchema tipado
4. reload() permite recargar sin reiniciar la app
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .types import ConfigSchema
from .exceptions import ConfigError


class ConfigManager:
    """
    Carga, valida y expone la configuración de la librería.

    Args:
        config_path: ruta al config.json. Si es None, busca en
                     vtool_llama/config/config.json relativo al
                     paquete instalado.
    """

    # Claves obligatorias que deben existir en el JSON
    REQUIRED_KEYS = frozenset({
        "debug", "system_prompt", "n_ctx", "n_batch",
        "gpu_layers", "temperature", "top_p", "top_k",
        "repeat_penalty", "max_tokens",
        "enable_logging", "history_limit",
        "auto_trim_context", "context_reserve_tokens",
    })

    def __init__(self, config_path: Optional[str] = None):
        # Ruta por defecto: dentro del paquete vtool_llama
        if config_path is None:
            self._config_path = Path(__file__).parent / "config" / "config.json"
        else:
            self._config_path = Path(config_path)

        self._raw: dict = {}
        self._schema: Optional[ConfigSchema] = None

    # ------------------------------------------------------------------
    # Carga y validación
    # ------------------------------------------------------------------

    def load(self) -> ConfigSchema:
        """
        Lee el archivo config.json, valida su estructura y retorna
        un ConfigSchema tipado.

        Raises:
            ConfigError: si el archivo no existe, no es JSON válido,
                         o faltan claves obligatorias.
        """
        path = self._config_path

        if not path.exists():
            raise ConfigError(
                f"Archivo de configuración no encontrado: {path}"
            )

        try:
            with open(path, "r", encoding="utf-8") as f:
                self._raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(
                f"Error de sintaxis en {path}: {e}"
            ) from e

        # Validar claves obligatorias
        missing = self.REQUIRED_KEYS - self._raw.keys()
        if missing:
            raise ConfigError(
                f"Faltan claves obligatorias en {path}: {', '.join(sorted(missing))}"
            )

        # Construir ConfigSchema: usar valor del JSON o default del dataclass
        from dataclasses import fields as dc_fields

        default_instance = ConfigSchema()
        field_values = {}
        for dc_field in dc_fields(default_instance):
            if dc_field.name in self._raw:
                field_values[dc_field.name] = self._raw[dc_field.name]
            else:
                field_values[dc_field.name] = getattr(default_instance, dc_field.name)

        self._schema = ConfigSchema(**field_values)

        return self._schema

    # ------------------------------------------------------------------
    # Acceso
    # ------------------------------------------------------------------

    def get(self) -> ConfigSchema:
        """
        Retorna la configuración actual como ConfigSchema.

        Si aún no se ha llamado a load(), lo hace automáticamente.
        """
        if self._schema is None:
            return self.load()
        return self._schema

    def reload(self) -> ConfigSchema:
        """
        Recarga la configuración desde el archivo en caliente.
        Útil si el usuario modifica config.json sin reiniciar.
        """
        self._schema = None
        return self.load()

    # ------------------------------------------------------------------
    # Propiedades de acceso directo
    # ------------------------------------------------------------------

    @property
    def config_path(self) -> Path:
        """Ruta al archivo de configuración."""
        return self._config_path

    def merge_character_config(self, char_dir: Path) -> ConfigSchema:
        """
        Retorna un ConfigSchema mergeado con overrides del personaje.

        Busca <char_dir>/config.json y si existe, sobreescribe las
        propiedades del config base con las del personaje.

        Args:
            char_dir: directorio del personaje (ej: personajes/default/)

        Returns:
            ConfigSchema con overrides aplicados
        """
        # Ensure base config is loaded
        if self._schema is None:
            self.load()

        merged = dict(self._raw)

        char_config_path = char_dir / "config.json"
        if char_config_path.exists():
            try:
                with open(char_config_path, "r", encoding="utf-8") as f:
                    overrides = json.load(f)
                merged.update(overrides)
            except (json.JSONDecodeError, OSError) as e:
                # Si el JSON del personaje está mal, usar base silenciosamente
                pass

        # Construir ConfigSchema desde el dict mergeado
        from dataclasses import fields as dc_fields

        default_instance = ConfigSchema()
        field_values = {}
        for dc_field in dc_fields(default_instance):
            if dc_field.name in merged:
                field_values[dc_field.name] = merged[dc_field.name]
            else:
                field_values[dc_field.name] = getattr(default_instance, dc_field.name)

        return ConfigSchema(**field_values)

    @property
    def raw(self) -> dict:
        """El diccionario crudo del JSON (solo después de load)."""
        return self._raw
