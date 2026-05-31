"""
Definiciones de herramientas internas para el Character System.

Disenadas para modelos open-source (Qwen, Llama, Kimi, Mistral, Gemma)
usando tool-calling estilo OpenAI.
"""

INTERNAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "store_long_term_memory",
            "description": (
                "Store an important long-term memory about the user, "
                "relationship, preferences, projects, or significant events."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": (
                            "Internal reformulated memory written in third person. "
                            "Never quote the user verbatim. "
                            "Convert first-person statements into remembered facts."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "identity",
                            "preference",
                            "relationship",
                            "goal",
                            "project",
                            "important_event",
                            "warning",
                        ],
                        "description": "Semantic category of the memory.",
                    },
                    "priority": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Importance score. 0.0 = trivial, 1.0 = critical.",
                    },
                },
                "required": ["content", "category"],
                "additionalProperties": False,
            },
        },
    },
]


TOOL_USAGE_POLICY = (
    "[TOOL USAGE POLICY]\n\n"
    "Call tools only when the current user message clearly requires it.\n"
    "Use `store_long_term_memory` only for stable, useful long-term facts "
    "or explicit requests to remember/save something.\n"
    "Do not store temporary emotions, casual chat, or trivial details.\n"
    "Never copy the user verbatim; rewrite memories in concise third person.\n"
    "If native tool calling is unavailable, use exactly: "
    '<tool_call>{"name":"store_long_term_memory","arguments":{"content":"...","category":"..."}}</tool_call>'
)

SCENE_SYSTEM_COMMAND = (
    "SYSTEM COMMAND: The user requested a scene description. "
    "Describe the current environment, your actions, what you see, "
    "hear and feel. Narrate immersively. Stay in character."
)
