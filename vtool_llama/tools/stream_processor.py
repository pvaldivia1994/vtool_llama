"""
StreamPostProcessor — middleware de streaming incremental.

Intercepta tokens del modelo en tiempo real, detecta patrones
de tool calls (<|tool_call|>, {{...}}, etc.) y separa el output
visible del output interno (tool execution).

Esto evita que el usuario vea texto crudo como:
  <|tool_call>call:store_long_term_memory{...}<tool_call|>

Modos:
  - content: yield texto seguro al usuario
  - tool: acumula texto de tool call, no lo muestra
"""

from __future__ import annotations

import re
from typing import Any, Callable, Generator, Optional

from .parser import (
    TEXT_TOOL_RE,
    parse_text_tool_calls,
    execute_text_tool,
)


# ============================================================
# PATRONES DE TOOL CALLS EN STREAMING
# ============================================================

# Tags de apertura y cierre para cada formato
_TOOL_OPENERS = ("{{", "<|tool_call>", "<tool_call>")
_TOOL_CLOSERS = ("}}", "<tool_call|>", "</tool_call>")


def _find_opener(buffer: str) -> tuple[Optional[str], int]:
    """Busca el primer opener en el buffer. Retorna (opener, indice)."""
    best_idx = len(buffer)
    best_opener = None
    for opener in _TOOL_OPENERS:
        idx = buffer.find(opener)
        if idx != -1 and idx < best_idx:
            best_idx = idx
            best_opener = opener
    return best_opener, best_idx


def _find_closer_for(buffer: str, opener: str) -> Optional[str]:
    """Dado un opener, busca su closer correspondiente."""
    closer_map = {
        "{{": "}}",
        "<|tool_call>": "<tool_call|>",
        "<tool_call>": "</tool_call>",
    }
    expected = closer_map.get(opener)
    if expected and expected in buffer:
        return expected
    return None


# ============================================================
# STREAM POST PROCESSOR
# ============================================================

class StreamPostProcessor:
    """
    Procesa tokens del stream incrementalmente, separando texto
    visible de tool calls internas.

    Uso:
        processor = StreamPostProcessor(
            on_tool_executed=my_callback,
            log_fn=print,
        )
        for chunk in stream:
            for event in processor.feed(chunk):
                if event["type"] == "text":
                    yield event["content"]
    """

    def __init__(
        self,
        on_tool_executed: Optional[Callable[[str, dict], None]] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self._on_tool = on_tool_executed
        self._log = log_fn or (lambda *_: None)

        # Estado interno
        self._mode = "content"  # "content" | "tool"
        self._buffer = ""
        self._current_opener: Optional[str] = None

    # ----------------------------------------------------------
    # API pública
    # ----------------------------------------------------------

    def feed(self, delta: dict) -> Generator[dict, None, None]:
        """
        Procesa un delta chunk del stream.

        Args:
            delta: dict con "content" key (token del modelo)

        Yields:
            dict con:
              - type: "text" | "tool_executed"
              - content: str (texto visible o mensaje de confirmacion)
        """
        token = delta.get("content", "")
        if not token:
            return

        self._buffer += token

        while True:
            if self._mode == "content":
                result = self._process_content_mode()
                if result is None:
                    break
                yield result

            elif self._mode == "tool":
                result = self._process_tool_mode()
                if result is None:
                    break
                if result:
                    yield result

    def flush(self) -> Generator[dict, None, None]:
        """
        Procesa lo que quede en el buffer al final del stream.
        """
        if self._mode == "tool":
            # Tool call truncada al final del stream — ignorar
            self._log("[StreamPP] Tool call truncada al final del stream")
            self._mode = "content"
            self._buffer = ""
            return

        if self._buffer:
            # Verificar si hay opener sin cerrar
            opener, idx = _find_opener(self._buffer)
            if opener is not None and idx >= 0:
                # Yieldear solo el texto antes del opener
                before = self._buffer[:idx]
                if before:
                    yield {"type": "text", "content": before}
            else:
                yield {"type": "text", "content": self._buffer}
            self._buffer = ""

    # ----------------------------------------------------------
    # Modos internos
    # ----------------------------------------------------------

    def _process_content_mode(self) -> Optional[dict]:
        """Busca openers en el buffer. Si encuentra, cambia a tool mode."""
        opener, idx = _find_opener(self._buffer)
        if opener is None:
            # No hay opener — el buffer es texto seguro
            # Pero hay que tener cuidado con fragmentos parciales
            safe_text = self._get_safe_content()
            if safe_text:
                self._buffer = self._buffer[len(safe_text):]
                return {"type": "text", "content": safe_text}
            return None

        # Hay un opener — yieldear el texto anterior
        before = self._buffer[:idx]
        self._buffer = self._buffer[idx + len(opener):]
        self._current_opener = opener
        self._mode = "tool"

        if before:
            return {"type": "text", "content": before}
        return None

    def _process_tool_mode(self) -> Optional[dict]:
        """Busca el closer correspondiente al opener."""
        closer = _find_closer_for(self._buffer, self._current_opener or "")
        if closer is None:
            # Aun no tenemos el cierre completo
            return None

        # Extraer el texto de la tool
        closer_idx = self._buffer.find(closer)
        tool_text = self._buffer[:closer_idx]
        self._buffer = self._buffer[closer_idx + len(closer):]
        self._mode = "content"

        # Ejecutar la tool detectada
        self._execute_tool(tool_text)

        return {"type": "tool_executed", "content": ""}

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _get_safe_content(self) -> str:
        """
        Determina cuanto texto del buffer es seguro para yieldear.

        No puede incluir el inicio de un patron de tool call.
        Ej: si el buffer termina en '<|to', no yieldemos '<|to'.
        """
        # Buscar el opener mas cercano desde el final
        best_partial = -1
        for opener in _TOOL_OPENERS:
            for i in range(1, min(len(opener), len(self._buffer)) + 1):
                partial = opener[:i]
                if self._buffer.endswith(partial):
                    # Verificar que no sea coincidencia casual
                    idx = self._buffer.rfind(partial)
                    if idx == len(self._buffer) - i:
                        best_partial = max(best_partial, len(self._buffer) - i)

        if best_partial > 0:
            return self._buffer[:best_partial]
        elif best_partial == 0:
            # El buffer entero es un posible inicio de tool
            return ""

        # Sin opener parcial — todo es seguro
        return self._buffer

    def _execute_tool(self, tool_text: str) -> None:
        """
        Ejecuta una tool call detectada en el stream.
        """
        # Reconstruir el patron completo para el parser
        opener = self._current_opener or ""
        closer = ""
        for o, c in zip(_TOOL_OPENERS, _TOOL_CLOSERS):
            if o == opener:
                closer = c
                break

        full_pattern = opener + tool_text + closer

        # Parsear y ejecutar
        calls = parse_text_tool_calls(full_pattern)
        for fn_name, fn_args in calls:
            self._log(f"[StreamPP] Tool detectada: {fn_name}")
            if self._on_tool:
                self._on_tool(fn_name, fn_args)
