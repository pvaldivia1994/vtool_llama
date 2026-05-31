"""
Parser de tool calls en texto plano para modelos GGUF.

Formato soportado:
  <tool_call>
  {"name":"store_long_term_memory","arguments":{"content":"...","category":"..."}}
  </tool_call>
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from .definitions import INTERNAL_TOOLS


# ============================================================
# REGEX
# ============================================================

TEXT_TOOL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)

_TOOL_PATTERN_STARTS = ("<tool_call>",)


# ============================================================
# PUBLIC API
# ============================================================

def find_tool_pattern_start(text: str) -> Optional[str]:
    for prefix in _TOOL_PATTERN_STARTS:
        if prefix in text:
            return prefix
    return None


def parse_text_tool_calls(text: str) -> list[tuple[str, dict]]:
    results: list[tuple[str, dict]] = []
    for match in TEXT_TOOL_RE.finditer(text):
        parsed = _safe_parse_tool_object(match.group(1) or "")
        if parsed:
            results.append(parsed)
    return results


def strip_text_tool_calls(text: str) -> str:
    cleaned = TEXT_TOOL_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def is_internal_tool(fn_name: str) -> bool:
    return any(t["function"]["name"] == fn_name for t in INTERNAL_TOOLS)


# ============================================================
# EXECUTOR
# ============================================================

def execute_text_tool(
    fn_name: str,
    fn_args: dict,
    *,
    add_memory_fn: Callable[..., Any],
    log_fn: Optional[Callable[[str], None]] = None,
) -> Any:
    log = log_fn or (lambda *_: None)

    try:
        if fn_name == "store_long_term_memory":
            content = fn_args.get("content", "").strip()
            category = fn_args.get("category", "important_event").strip()
            priority = _safe_float(fn_args.get("priority", 0.7), 0.7)
            priority = max(0.0, min(priority, 1.0))

            if not content:
                log("[ToolParser] store_long_term_memory rechazada: content vacio")
                return None

            result = add_memory_fn(
                content=content,
                priority=priority,
                tags=[category],
                always_include=priority >= 0.9,
            )
            log(f"[AutoTool] Memoria guardada ({category}, p={priority:.2f}) - {content[:60]}")
            return result

        else:
            log(f"[ToolParser] Tool ignorada: {fn_name}")
            return None

    except Exception as e:
        log(f"[ToolParser] Error en {fn_name}: {e}")
        return None


# ============================================================
# HELPERS
# ============================================================

def _safe_parse_args(args_text: str) -> dict:
    """Parser tolerante a errores. Soporta JSON parcial, key:value, key=value."""
    args_text = args_text.strip()
    if not args_text:
        return {}

    # 1. Try JSON
    try:
        fake_json = "{" + args_text + "}"
        fake_json = re.sub(r'(\w+)\s*:', r'"\1":', fake_json)
        parsed = json.loads(fake_json)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # 2. Try regex fallback
    parsed = {}
    kv_pairs = re.findall(r'(\w+)\s*[:=]\s*(".*?"|\'.*?\'|[^,]+)', args_text, re.DOTALL)
    for key, value in kv_pairs:
        parsed[key] = _clean_value(value)
    return parsed


def _safe_parse_tool_object(tool_text: str) -> Optional[tuple[str, dict]]:
    try:
        payload = json.loads(tool_text.strip())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    args = payload.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return name.strip(), args


def _clean_value(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    value = value.replace('<|"|>', "").replace("<|'|>", "")

    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None

    try:
        return float(value) if "." in value else int(value)
    except Exception:
        return value


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default
