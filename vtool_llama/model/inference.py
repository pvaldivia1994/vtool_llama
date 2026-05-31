"""inference.py — Método generate() de ModelManager."""

from __future__ import annotations

from typing import Any, Optional

from .manager import ModelManager
from ..exceptions import InferenceError, ModelNotLoadedError, OOMError


def generate(
    self: ModelManager,
    messages: list[dict[str, str]],
    stream: bool = False,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    repeat_penalty: Optional[float] = None,
    tools: Optional[list[dict]] = None,
    tool_choice: Optional[Any] = None,
) -> Any:
    with self._lock:
        if self._model is None:
            raise ModelNotLoadedError(
                "No hay modelo cargado. Llama a load_model() primero."
            )

        kwargs = {
            "messages": messages,
            "max_tokens": max_tokens or self._config.max_tokens,
            "temperature": temperature if temperature is not None else self._config.temperature,
            "top_p": top_p if top_p is not None else self._config.top_p,
            "top_k": top_k if top_k is not None else self._config.top_k,
            "repeat_penalty": repeat_penalty if repeat_penalty is not None else self._config.repeat_penalty,
            "stream": stream,
        }

        if tools is not None:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        try:
            reset = getattr(self._model, "reset", None)
            if callable(reset):
                reset()
            result = self._model.create_chat_completion(**kwargs)
            return result
        except Exception as e:
            error_msg = str(e)

            if any(term in error_msg.lower() for term in [
                "out of memory", "cuda out of", "cuda error: out of memory",
            ]):
                raise OOMError(
                    "Memoria insuficiente durante inferencia. "
                    "Reduce n_ctx o usa un modelo más pequeño."
                ) from e

            raise InferenceError(f"Error durante inferencia: {e}") from e

ModelManager.generate = generate
