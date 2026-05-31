"""
Tool Execution Manager para vtool_llama.

Centraliza toda la logica de ejecucion de herramientas:
  - Manejo de tool_calls estructurados (OpenAI format)
  - Fallback de tool_calls en texto plano (<tool_call>{json}</tool_call>)
  - Reasoning loop (continue/break logic)
  - Coercion retry (re-prompt si el modelo ignora la tool)
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from .definitions import INTERNAL_TOOLS
from .parser import (
    parse_text_tool_calls,
    strip_text_tool_calls,
    execute_text_tool,
)

# ============================================================
# TRIGGER DETECTION
# ============================================================

_MEMORY_TRIGGERS = (
    "recuerda", "recuerde", "recuerden",
    "guarda", "guardar", "memoriza", "memorize",
    "no olvides", "no olvide", "no olviden",
    "ten en cuenta", "tengas en cuenta",
    "para que sepas", "para tu informacion",
    "#mem", "remember", "store this", "save this",
    "don't forget", "keep in mind",
)

def has_memory_trigger(text: str) -> bool:
    """Detecta si el texto del usuario pide guardar un recuerdo."""
    lower = text.lower()
    return any(t in lower for t in _MEMORY_TRIGGERS)


def get_active_internal_tools(user_prompt: str, config: Any = None) -> list[dict]:
    """Retorna las tools internas que deben exponerse en este turno."""
    always = bool(getattr(config, "always_enable_internal_tools", False))
    if always:
        return list(INTERNAL_TOOLS)

    active_names = set()
    if has_memory_trigger(user_prompt):
        active_names.add("store_long_term_memory")

    return [
        tool for tool in INTERNAL_TOOLS
        if tool.get("function", {}).get("name") in active_names
    ]


# ============================================================
# TOOL EXECUTION MANAGER
# ============================================================

class ToolExecutionManager:
    """
    Gestiona la ejecucion de herramientas internas.

    Separa la logica de tools del bucle principal de chat(),
    permitiendo reutilizacion y testeabilidad.
    """

    def __init__(
        self,
        *,
        add_memory_fn: Callable[..., Any],
        log_info_fn: Optional[Callable[[str], None]] = None,
        log_debug_fn: Optional[Callable[[str, str], None]] = None,
        rebuild_fn: Optional[Callable[[], None]] = None,
    ):
        self._add_memory = add_memory_fn
        self._log_info = log_info_fn or (lambda *_: None)
        self._log_debug = log_debug_fn or (lambda *_: None)
        self._rebuild = rebuild_fn

    # ----------------------------------------------------------
    # Structured tool_calls (OpenAI format)
    # ----------------------------------------------------------

    def handle_structured_calls(
        self,
        tool_calls: list[dict],
        scene_prompt: str,
        user_tools: Optional[list[dict]] = None,
    ) -> dict:
        """Procesa tool_calls estructurados (OpenAI format).

        Returns:
            dict con:
              - internal_found: bool
              - memory_saved: bool
              - external_calls: list[dict]
        """
        result: dict[str, Any] = {
            "internal_found": False,
            "memory_saved": False,
            "external_calls": [],
        }

        for tc in tool_calls:
            fn_name = tc.get("function", {}).get("name", "")
            fn_args_raw = tc.get("function", {}).get("arguments", "{}")
            fn_args = self._safe_json_parse(fn_args_raw)

            if fn_name == "store_long_term_memory":
                execute_text_tool(
                    fn_name, fn_args,
                    add_memory_fn=self._add_memory,
                    log_fn=self._log_info,
                )
                result["memory_saved"] = True
                result["internal_found"] = True

            elif user_tools:
                # Tool externa — validar
                valid = self._validate_external_call(tc, user_tools)
                if valid:
                    result["external_calls"].append(tc)

        return result

    # ----------------------------------------------------------
    # Text-based tool_calls (fallback <tool_call>{json}</tool_call>)
    # ----------------------------------------------------------

    def handle_text_calls(
        self,
        response_text: str,
        scene_prompt: str,
        user_tools: Optional[list[dict]] = None,
    ) -> dict:
        """
        Procesa tool_calls escritas como texto <tool_call>{json}</tool_call>.

        Returns:
            dict con:
              - internal_found: bool
              - memory_saved: bool
              - external_calls: list
              - cleaned_text: str (texto sin los patrones)
        """
        result = {
            "internal_found": False,
            "memory_saved": False,
            "external_calls": [],
            "cleaned_text": response_text,
        }

        text_tools = parse_text_tool_calls(response_text)
        if not text_tools:
            return result

        for fn_name, fn_args in text_tools:
            if fn_name == "store_long_term_memory":
                execute_text_tool(
                    fn_name, fn_args,
                    add_memory_fn=self._add_memory,
                    log_fn=self._log_info,
                )
                result["memory_saved"] = True
                result["internal_found"] = True

            elif user_tools:
                tc = {
                    "function": {
                        "name": fn_name,
                        "arguments": json.dumps(fn_args),
                    }
                }
                valid = self._validate_external_call(tc, user_tools)
                if valid:
                    result["external_calls"].append(tc)

        result["cleaned_text"] = strip_text_tool_calls(response_text)
        return result

    # ----------------------------------------------------------
    # Coercion Retry
    # ----------------------------------------------------------

    def needs_tool_coercion(
        self,
        user_prompt: str,
        response_text: str,
        had_tool_calls: bool,
        had_text_tools: bool,
    ) -> bool:
        """
        Determina si el modelo debio usar una tool pero no lo hizo.

        Returns:
            True si hay que forzar re-prompt con la tool.
        """
        if had_tool_calls or had_text_tools:
            return False

        return has_memory_trigger(user_prompt)

    def build_coercion_prompt(self, user_prompt: str) -> str:
        """
        Construye un re-prompt de coercion para forzar tool calling.

        Se usa con temperature=0.2 y max_tokens=100.
        """
        if has_memory_trigger(user_prompt):
            return (
                "SYSTEM OVERRIDE: The user asked you to remember something. "
                "You MUST call store_long_term_memory now. "
                "Analyze what they said and extract the key information. "
                "Respond with the tool call only."
            )

        return ""

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _safe_json_parse(self, text: str) -> dict:
        try:
            return json.loads(text)
        except Exception:
            return {}

    def _validate_external_call(
        self,
        tool_call: dict,
        user_tools: list[dict],
    ) -> bool:
        """Valida que la tool_call corresponda a una tool definida por el usuario."""
        fn_name = tool_call.get("function", {}).get("name", "")
        valid_names = {
            t.get("function", {}).get("name", "")
            for t in (user_tools or [])
        }
        if fn_name in valid_names:
            return True
        self._log_debug("TOOL", f"Tool call '{fn_name}' no valida (alucinacion)")
        return False
