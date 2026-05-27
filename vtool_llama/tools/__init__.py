"""
Modulo de herramientas (tools) para vtool_llama.

Exporta:
  - INTERNAL_TOOLS, TOOL_USAGE_POLICY, SCENE_SYSTEM_COMMAND
  - TEXT_TOOL_RE, find_tool_pattern_start
  - parse_text_tool_calls, strip_text_tool_calls
  - execute_text_tool, is_internal_tool
"""

from .definitions import INTERNAL_TOOLS, TOOL_USAGE_POLICY, SCENE_SYSTEM_COMMAND
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
    "TOOL_USAGE_POLICY",
    "SCENE_SYSTEM_COMMAND",
    "TEXT_TOOL_RE",
    "find_tool_pattern_start",
    "parse_text_tool_calls",
    "strip_text_tool_calls",
    "execute_text_tool",
    "is_internal_tool",
]
