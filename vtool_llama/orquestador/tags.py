"""
tags.py — Sistema de tags literales (DEPRECATED en v18).

V18 migró a prosa natural. Este archivo se mantiene para compatibilidad
con código legacy que aún importe estas constantes.
"""

# Mantenido para compatibilidad legacy
SAYS = "[SAYS]"
DOES = "[DOES]"
THINKS = "[THINKS]"
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
