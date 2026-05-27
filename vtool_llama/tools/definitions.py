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
    {
        "type": "function",
        "function": {
            "name": "get_scene_state",
            "description": (
                "Retrieve the current environmental and emotional "
                "scene state for immersive narration."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "enum": [
                            "complete",
                            "environment",
                            "action",
                            "emotion",
                        ],
                        "description": "What aspect of the scene should be emphasized.",
                    }
                },
                "required": [],
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
    "BAD:  'User said he's tired' (temporary)\n\n"
    "---\n"
    "TOOL: get_scene_state\n"
    "---\n"
    "PURPOSE: Retrieve scene state before narrating.\n\n"
    "USE WHEN: user asks 'what do you see?', 'where are you?', "
    "'what are you doing?', 'describe the scene', '/scene_view'\n\n"
    "AFTER CALLING: narrate immersively in character. "
    "Never output raw JSON."
)

SCENE_SYSTEM_COMMAND = (
    "SYSTEM COMMAND: The user requested a scene description. "
    "Call get_scene_state first, then narrate immersively "
    "with sensory details. Stay in character."
)
