"""
Módulo de herramientas (tools) para vtool_llama.

Define las herramientas internas en formato OpenAI, el parser de
tool calls en texto plano, y las funciones de ejecución.

Exporta:
  - INTERNAL_TOOLS: lista de definiciones de herramientas internas
  - SCENE_PROMPT: system command para descripción de escena
  - TEXT_TOOL_RE: regex para detectar tool calls en texto plano
  - parse_text_tool_calls(): extrae tools del texto
  - strip_text_tool_calls(): elimina patrones de tools del texto
  - execute_text_tool(): ejecuta una tool detectada en texto
"""

from .definitions import INTERNAL_TOOLS, SCENE_PROMPT
from .parser import (
    TEXT_TOOL_RE,
    find_tool_pattern_start,
    parse_text_tool_calls,
    strip_text_tool_calls,
    execute_text_tool,
    is_internal_tool,
)

__all__ = [
    "INTERNAL_TOOLS",
    "SCENE_PROMPT",
    "TEXT_TOOL_RE",
    "find_tool_pattern_start",
    "parse_text_tool_calls",
    "strip_text_tool_calls",
    "execute_text_tool",
    "is_internal_tool",
]
