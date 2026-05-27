"""
Parser de tool calls en texto plano.

Detecta y procesa tool calls que los modelos GGUF escriben como texto
en vez de usar el formato OpenAI estructurado.

Formatos detectados:
  {{remember_memory{content: "..."}}}
  <|tool_call>call:describe_scene{focus: "..."}<tool_call|>
"""

from __future__ import annotations

import re
from typing import Optional

from .definitions import INTERNAL_TOOLS


# Regex que captura ambos formatos de tool call en texto plano
TEXT_TOOL_RE = re.compile(
    r'\{\{(\w+)\{([^}]+)\}\}'        # {{name{args}}}
    r'|<\|tool_call>call:(\w+)\{([^}]+)\}<tool_call\|>'   # <|tool_call>call:name{args}<tool_call|>
)

# Posibles prefijos de inicio de un patron de tool call
_TOOL_PATTERN_STARTS = ("{{", "<|tool_call>")


def find_tool_pattern_start(text: str) -> Optional[str]:
    """
    Busca si el texto contiene algun inicio de patron de tool call.

    Args:
        text: texto a inspeccionar

    Returns:
        el prefijo encontrado ('{{' o '<|tool_call>'), o None
    """
    for prefix in _TOOL_PATTERN_STARTS:
        if prefix in text:
            return prefix
    return None


def _clean_value(val: str) -> str:
    """Limpia un valor extraido de un tool call: remueve comillas y marcadores <|\"|>."""
    val = val.strip()
    val = val.strip('"').strip("'")
    val = val.replace('<|"|>', "").replace("<|'|>", "")
    return val


def _parse_args(args_text: str) -> dict[str, str]:
    """Parsea el texto crudo de argumentos en un diccionario key: value."""
    args = {}
    for kv in args_text.split(","):
        kv = kv.strip()
        if ":" in kv:
            key, _, val = kv.partition(":")
            key = key.strip()
            if key:
                args[key] = _clean_value(val)
    return args


def parse_text_tool_calls(text: str) -> list[tuple[str, dict]]:
    """
    Busca patrones de tool call en el texto y retorna lista de (nombre, args_dict).

    Args:
        text: texto donde buscar

    Returns:
        [(nombre, {args_dict}), ...] o lista vacia
    """
    results = []
    for match in TEXT_TOOL_RE.finditer(text):
        fn_name = match.group(1) or match.group(3)
        args_text = match.group(2) or match.group(4)
        results.append((fn_name, _parse_args(args_text)))
    return results


def strip_text_tool_calls(text: str) -> str:
    """
    Elimina del texto los patrones de tool calls.

    Args:
        text: texto original

    Returns:
        texto sin los patrones {{...}} o <|tool_call>...<tool_call|>
    """
    return TEXT_TOOL_RE.sub("", text).strip()


def execute_text_tool(
    fn_name: str,
    fn_args: dict,
    add_memory_fn: callable,
    log_fn: callable,
) -> None:
    """
    Ejecuta una tool detectada en texto plano.

    Args:
        fn_name: nombre de la tool ('remember_memory', 'describe_scene', etc.)
        fn_args: dict con los argumentos parseados
        add_memory_fn: callable para guardar memoria (ej: llm.add_memory)
        log_fn: callable para logging (ej: llm._log_info)
    """
    if fn_name == "remember_memory":
        mem_content = fn_args.get("content", "")
        if mem_content:
            add_memory_fn(mem_content, priority=1.0)
            log_fn(f"🧠 [Auto-Tool/Texto] Memoria guardada: {mem_content}")

    elif fn_name == "describe_scene":
        log_fn("🎬 [Auto-Tool/Texto] Descripcion de escena solicitada")


def is_internal_tool(fn_name: str) -> bool:
    """Verifica si un nombre de tool pertenece a una herramienta interna."""
    return any(
        t["function"]["name"] == fn_name
        for t in INTERNAL_TOOLS
    )
