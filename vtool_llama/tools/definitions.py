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
    "You may call tools when appropriate.\n\n"
    "---\n"
    "TOOL: store_long_term_memory\n"
    "---\n"
    "PURPOSE: Store important long-term information that persists across conversations.\n\n"
    "USE WHEN:\n"
    "- User says: 'remember this', 'save this', 'don't forget', 'keep in mind', "
    "'memorize', '#mem'\n"
    "- User reveals stable info: name, age, occupation, goals, "
    "preferences, dislikes, projects\n"
    "- A major long-term event happens\n\n"
    "DO NOT USE FOR: temporary emotions, casual chat, trivial facts\n\n"
    "RULES:\n"
    "- Never copy verbatim. Reformulate in third person.\n"
    "- Keep concise. Store only useful information.\n\n"
    "GOOD: 'The user is named John.' (identity)\n"
    "BAD:  'User said he's tired' (temporary)"
)

SCENE_SYSTEM_COMMAND = (
    "SYSTEM COMMAND: The user requested a scene description. "
    "Describe the current environment, your actions, what you see, "
    "hear and feel. Narrate immersively. Stay in character."
)
