"""
Parser robusto de tool calls en texto plano para modelos GGUF.

Formatos soportados:
  {{store_long_term_memory{content:"...", category:"..."}}}
  <|tool_call>call:get_scene_state{focus:"complete"}<tool_call|>
  call:store_long_term_memory{content:"..."}
  <tool_call>store_long_term_memory(content="...")</tool_call>
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from .definitions import INTERNAL_TOOLS


# ============================================================
# REGEX
# ============================================================

TEXT_TOOL_RE = re.compile(
    r"""
    \{\{(\w+)\{(.*?)\}\}                                   # {{tool{args}}}
    |
    <\|tool_call\>call:(\w+)\{(.*?)\}<tool_call\|>         # ChatML
    |
    (?:^|\s)call:(\w+)\{(.*?)\}                             # raw call:name{}
    |
    <tool_call>\s*(\w+)\((.*?)\)\s*</tool_call>            # XML-ish
    """,
    re.DOTALL | re.VERBOSE,
)

_TOOL_PATTERN_STARTS = ("{{", "<|tool_call>", "call:", "<tool_call>")


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
        fn_name = match.group(1) or match.group(3) or match.group(5) or match.group(7)
        raw_args = match.group(2) or match.group(4) or match.group(6) or match.group(8) or ""
        parsed = _safe_parse_args(raw_args)
        if fn_name:
            results.append((fn_name, parsed))
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
    get_scene_state_fn: Optional[Callable[..., dict]] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Any:
    log = log_fn or (lambda *_: None)

    try:
        if fn_name in ("store_long_term_memory", "remember_memory"):
            content = fn_args.get("content", "").strip()
            category = fn_args.get("category", "important_event").strip()
            priority = _safe_float(fn_args.get("priority", 0.7), 0.7)
            priority = max(0.0, min(priority, 1.0))

            if not content:
                log(f"[ToolParser] store_long_term_memory rechazada: content vacio")
                return None

            result = add_memory_fn(
                content=content,
                priority=priority,
                tags=[category],
                always_include=priority >= 0.9,
            )
            log(f"[AutoTool] Memoria guardada ({category}, p={priority:.2f}) - {content[:60]}")
            return result

        elif fn_name in ("get_scene_state", "describe_scene"):
            focus = fn_args.get("focus", "complete").strip().lower()
            if get_scene_state_fn:
                scene = get_scene_state_fn(focus=focus)
                log(f"[AutoTool] Scene requested (focus={focus})")
                return scene
            log("[ToolParser] No existe get_scene_state_fn")
            return None

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
