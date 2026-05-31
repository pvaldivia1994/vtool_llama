"""
tags.py — Sistema de tags literales (v17).

Formato: [USER=Nombre][TIPO] o [ASSISTANT=Nombre][TIPO]

Niveles:
  [USER=X][SAYS]       → El usuario X dice
  [USER=X][DOES]       → El usuario X realiza una accion
  [USER=X][THINKS]     → El usuario X piensa
  [ASSISTANT=X][SAYS]  → El personaje X dice
  [ASSISTANT=X][DOES]  → El personaje X realiza una accion
  [ASSISTANT=X][THINKS] → El personaje X piensa internamente
  [DEFINE]             → Definicion permanente del personaje
  [STATE]              → Estado emocional/relacional actual
  [SCENE]              → Descripcion de escena
"""

TAG_DEFINITIONS = """
[GUIA DE TAGS]

[USER=Name][SAYS]    → The human player named "Name" speaks.
[USER=Name][DOES]    → The human player named "Name" performs an action.
[USER=Name][THINKS]  → The human player named "Name" has an internal thought.

[ASSISTANT=Name][SAYS]    → The character "Name" speaks. This is you.
[ASSISTANT=Name][DOES]    → The character "Name" performs an action. This is you.
[ASSISTANT=Name][THINKS]  → The character "Name" has an internal thought. This is you.

You are [ASSISTANT=<CHARACTER_NAME>]. Your responses MUST use [ASSISTANT=<CHARACTER_NAME>][...] tags.

[DEFINE] Permanent character definition: identity, rules, history, and behavior.
[STATE] Current emotional, relational, and psychological state.
[SCENE] Current scene, location, environment, time, and world events.

[CONTINUE] Advance time, scene, or situation without player input.
When you see [CONTINUE] as a user message, the player is not speaking —
continue the scene naturally based on the current context.

Examples:
  [USER=LiuniK][SAYS] Hello, how are you?       → The user is speaking
  [ASSISTANT=Luna][DOES] *Looks down nervously*  → Luna performs an action
  [ASSISTANT=Luna][SAYS] I am fine.              → Luna speaks
  [ASSISTANT=Luna][THINKS] *He is handsome*      → Luna has an internal thought
  [USER=Roberto][SAYS] Get back to work!         → Another character (user-controlled)
"""

# Tags de contenido (segundo nivel)
SAYS = "[SAYS]"
DOES = "[DOES]"
THINKS = "[THINKS]"

# Tags de sistema (primer nivel, sin identidad)
DEFINE = "[DEFINE]"
STATE = "[STATE]"
SCENE = "[SCENE]"

CONTENT_TAGS = {
    "says": SAYS,
    "does": DOES,
    "thinks": THINKS,
}

SYSTEM_TAGS = {
    "define": DEFINE,
    "state": STATE,
    "scene": SCENE,
}
