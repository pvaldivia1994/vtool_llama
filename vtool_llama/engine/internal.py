"""internal.py — Métodos internos de soporte (stats, extracción, validación)."""

from __future__ import annotations

from typing import Any

from .base import VToolLlama


def _validate_prompt(self: VToolLlama, prompt: str) -> None:
    if not prompt or not prompt.strip():
        from ..exceptions import EmptyPromptError
        raise EmptyPromptError(
            "El prompt no puede estar vacío. Proporciona un texto válido."
        )

VToolLlama._validate_prompt = _validate_prompt


def _extract_response_text(self: VToolLlama, result: Any) -> str:
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        self._log_warning(f"No se pudo extraer texto de la respuesta: {e}")
        return str(result)

VToolLlama._extract_response_text = _extract_response_text


def _extract_token_from_chunk(self: VToolLlama, chunk: Any) -> tuple[str, str]:
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

VToolLlama._extract_token_from_chunk = _extract_token_from_chunk


def _record_stats(self: VToolLlama, result: Any) -> None:
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

VToolLlama._record_stats = _record_stats


def _record_stats_from_stream(
    self: VToolLlama,
    stream: Any,
    full_response: str,
) -> None:
    try:
        if hasattr(stream, "_last_chunk") and stream._last_chunk:
            usage = stream._last_chunk.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
        else:
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

VToolLlama._record_stats_from_stream = _record_stats_from_stream


def _log_generation_stats(self: VToolLlama) -> None:
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

VToolLlama._log_generation_stats = _log_generation_stats
