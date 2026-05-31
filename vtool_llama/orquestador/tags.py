"""
tags.py — Sistema unificado de tags semánticos (v13).

Formato: [IDENTIDAD][TIPO] contenido

Niveles:
  [DEFINE]           → Definición permanente del personaje
  [STATE]            → Estado emocional/relacional actual
  [SCENE]            → Descripción de escena
  [ID][THOUGHT]      → Pensamiento interno del personaje
  [ID][SPEAK]        → Diálogo del personaje
  [ID][ACT]          → Acción narrativa del personaje
"""

TAG_DEFINITIONS = """
[GUÍA DE TAGS]

Each message is tagged to indicate who is speaking and what type of content it is.

[DEFINE] Permanent character definition: identity, rules, history, and behavior.
[STATE] Current emotional, relational, and psychological state.
[SCENE] Current scene, location, environment, time, and world events.

When you see [SPEAK] after a name, that character is speaking dialogue.
When you see [ACT] after a name, that character is performing a physical action.
When you see [THOUGHT] after a name, those are the character's internal thoughts.

[CHARACTER_NAME] is the character you are playing. Your responses are tagged
with [CHARACTER_NAME][SPEAK] (dialogue) or [CHARACTER_NAME][ACT] (actions).
You must ALWAYS respond as this character, never as a generic assistant.

Examples:
  [PLAYER][SPEAK] Hello, how are you?         → The user is speaking
  [LUNA][ACT] *Looks down nervously*           → Luna performs an action
  [LUNA][SPEAK] I am fine, thank you.          → Luna speaks
  [ROBERTO][SPEAK] Get back to work!           → Another character speaks
"""

# Tags de contenido (segundo nivel)
SPEAK = "[SPEAK]"
ACT = "[ACT]"
THOUGHT = "[THOUGHT]"

# Tags de sistema (primer nivel, sin identidad)
DEFINE = "[DEFINE]"
STATE = "[STATE]"
SCENE = "[SCENE]"

CONTENT_TAGS = {
    "speak": SPEAK,
    "act": ACT,
    "thought": THOUGHT,
}

SYSTEM_TAGS = {
    "define": DEFINE,
    "state": STATE,
    "scene": SCENE,
}
