"""manager.py — ModelManager: clase base, constructor y propiedades."""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from ..types import ConfigSchema, ModelInfo


class ModelManager:
    def __init__(
        self,
        config: ConfigSchema,
        logger_fn: Callable[[str, str], None],
        error_fn: Callable[[str], None],
    ):
        self._config = config
        self._log = logger_fn
        self._error = error_fn

        self._model: Any = None
        self._model_info: ModelInfo = ModelInfo()
        self._lock = threading.RLock()
        self._tokenize_fn: Optional[Callable] = None
        self._loading = False

    @property
    def model(self) -> Any:
        return self._model

    @property
    def model_info(self) -> ModelInfo:
        return self._model_info

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def tokenize_fn(self) -> Optional[Callable]:
        return self._tokenize_fn
