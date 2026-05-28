"""
Gestor de estadísticas de rendimiento para vtool_llama.

Registra métricas de cada inferencia:
- tokens de entrada/salida
- tokens por segundo
- duración en ms
- modelo utilizado

Permite consultar el historial de generaciones y obtener
promedios para monitoreo de rendimiento.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Optional

from ..types import GenerationStats


class StatsManager:
    """
    Acumula y expone estadísticas de generación.

    Args:
        max_history: cantidad máxima de generaciones a recordar
                     en el historial (para promedios)
    """

    def __init__(self, max_history: int = 100):
        self._current: Optional[GenerationStats] = None
        self._history: deque[GenerationStats] = deque(maxlen=max_history)
        self._start_time: Optional[float] = None

    # ------------------------------------------------------------------
    # Ciclo de vida de una generación
    # ------------------------------------------------------------------

    def begin_generation(self) -> None:
        """
        Marca el inicio de una generación.
        Debe llamarse justo antes de la inferencia.
        """
        self._start_time = time.perf_counter()

    def end_generation(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        model_name: str = "",
    ) -> GenerationStats:
        """
        Finaliza la generación y calcula estadísticas.

        Args:
            prompt_tokens: tokens de entrada
            completion_tokens: tokens generados
            model_name: nombre del modelo usado

        Returns:
            GenerationStats con los datos calculados
        """
        elapsed = time.perf_counter() - self._start_time if self._start_time else 0.0
        duration_ms = elapsed * 1000

        tokens_per_second = 0.0
        if elapsed > 0 and completion_tokens > 0:
            tokens_per_second = completion_tokens / elapsed

        stats = GenerationStats(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            tokens_per_second=round(tokens_per_second, 2),
            duration_ms=round(duration_ms, 2),
            model_name=model_name,
        )

        self._current = stats
        self._history.append(stats)

        return stats

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    @property
    def current(self) -> Optional[GenerationStats]:
        """Última generación registrada."""
        return self._current

    @property
    def history(self) -> list[GenerationStats]:
        """Historial de generaciones."""
        return list(self._history)

    @property
    def average_tokens_per_second(self) -> float:
        """Promedio de tokens/s de todo el historial."""
        if not self._history:
            return 0.0
        speeds = [s.tokens_per_second for s in self._history if s.tokens_per_second > 0]
        if not speeds:
            return 0.0
        return round(sum(speeds) / len(speeds), 2)

    @property
    def total_tokens_generated(self) -> int:
        """Total de tokens generados en esta sesión."""
        return sum(s.completion_tokens for s in self._history)

    @property
    def total_prompt_tokens(self) -> int:
        """Total de tokens de entrada procesados."""
        return sum(s.prompt_tokens for s in self._history)

    @property
    def generation_count(self) -> int:
        """Cantidad de generaciones realizadas."""
        return len(self._history)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Limpia todo el historial de estadísticas."""
        self._current = None
        self._history.clear()
        self._start_time = None
