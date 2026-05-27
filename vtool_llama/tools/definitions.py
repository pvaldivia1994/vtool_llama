"""
Definiciones de herramientas internas en formato OpenAI.

Contiene:
  - INTERNAL_TOOLS: lista con remember_memory y describe_scene
  - SCENE_PROMPT: system command para /scene_view
"""

INTERNAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember_memory",
            "description": (
                "Guarda un recuerdo en tu memoria a largo plazo. "
                "Escribe TU el contenido en tus propias palabras, como si lo recordaras internamente"
                " - reformula, resume o interpreta lo que dijo el usuario.\n\n"
                "TRIGGERS (debes llamar esto cuando):\n"
                "- El usuario dice 'recuerda que...', 'guarda esto...', 'memoriza...', "
                "'no olvides...', 'ten en cuenta que...', 'para que sepas...'\n"
                "- El usuario comparte informacion personal sobre si mismo "
                "(nombre, gustos, preferencias, datos importantes)\n"
                "- Ocurre un evento importante en la conversacion que deberias recordar para siempre\n"
                "- El usuario te pide explicitamente que guardes algo\n\n"
                "NO uses esta herramienta para:\n"
                "- Responder preguntas o conversar normalmente\n"
                "- Repetir lo que el usuario dijo sin reformularlo\n\n"
                "Ejemplos de contenido que DEBES escribir tu (reformulado):\n"
                "- Usuario: 'Me llamo Juan' -> content: 'El usuario se llama Juan.'\n"
                "- Usuario: 'Odio el cafe con azucar' -> content: 'Al usuario no le gusta "
                "el cafe con azucar, prefiere sin endulzar.'\n"
                "- Usuario: 'Tengo 30 anos' -> content: 'El usuario tiene 30 anos.'\n"
                "- Usuario: 'Trabajo en una cafeteria' -> content: 'El usuario trabaja "
                "como barista en una cafeteria.'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": (
                            "El recuerdo escrito en TUS propias palabras, como si lo pensaras"
                            " internamente. Reformula, no copies textual. Ej: en vez de"
                            " 'me llamo Juan' escribe 'El usuario se llama Juan'."
                        ),
                    }
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_scene",
            "description": (
                "Describe INMERSIVAMENTE la escena actual en tercera persona,"
                " como si narraras una novela. Escribe TU descripcion con tus propias"
                " palabras sensoriales (vista, oido, olfato, tacto).\n\n"
                "TRIGGERS (debes llamar esto cuando):\n"
                "- El usuario te pide EXPLICITAMENTE 'describe la escena',"
                " 'donde estas?', 'que ves?', 'que pasa a mi alrededor?',"
                " 'como es el lugar?'\n"
                "- El usuario dice '/scene_view'\n"
                "- El usuario pregunta 'que estas haciendo?'\n\n"
                "FORMATO de respuesta:\n"
                "- Usa DOBLES ASTERISCOS para la descripcion: ** texto **\n"
                "- Describe en tercera persona: ** [TuNombre] hace algo... **\n"
                "- Incluye: entorno, iluminacion, sonidos, olores, tu accion actual\n"
                "- Narrativo e inmersivo, NO uses bullet points ni listas\n\n"
                "Ejemplos:\n"
                "- focus='completo': ** Elara camina por el bosque oscuro... **\n"
                "- focus='entorno': ** El salon del castillo es inmenso... **\n"
                "- focus='accion': ** [Nombre] se arrodilla junto al rio... **"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": (
                            "Que aspecto enfocar: 'completo' (todo, por defecto),"
                            " 'entorno' (solo el lugar), 'accion' (lo que haces),"
                            " 'emocion' (lo que sientes)."
                        ),
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]

SCENE_PROMPT = (
    "(SYSTEM COMMAND: El usuario ha solicitado una vista de escena."
    " Describe detalladamente la escena actual, el entorno, la iluminacion"
    " y exactamente lo que estas haciendo en este preciso instante en tercera"
    " persona de forma inmersiva, usando dobles asteriscos. Ejemplo:"
    " ** [Nombre] barre el patio con melancolia... **)"
)
