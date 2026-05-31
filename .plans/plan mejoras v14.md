# Plan mejoras v14

## Objetivo

Consolidar y documentar los cambios realizados durante la implementación de v13 que no estaban en el plan original, más las mejoras identificadas durante el uso real con Luna.

## Cambios realizados (post-v13)

### 1. Sistema unificado de tags (`orquestador/tags.py`)

**Qué**: Archivo nuevo con definición centralizada de todos los tags semánticos.

**Por qué**: Antes había 3 sistemas de tags distintos (compilador, orquestador, ChromaDB) que no se alineaban. Ahora hay una fuente única de verdad.

**Tags definidos**:
- `[DEFINE]` — Definición permanente del personaje
- `[STATE]` — Estado emocional/relacional actual
- `[SCENE]` — Descripción de escena
- `[ID][THOUGHT]` — Pensamiento interno
- `[ID][SPEAK]` — Diálogo
- `[ID][ACT]` — Acción narrativa

**[Listo]**

### 2. `speaker_tag` en SQLite y `ChatMessage`

**Qué**: Nueva columna `speaker_tag TEXT DEFAULT ''` en tabla `messages` de SQLite. Nuevo campo en dataclass `ChatMessage`.

**Por qué**: Cada mensaje ahora guarda quién lo dijo (`LIU`, `LUNA`, `ROBERTO`, etc.). Esto permite filtrar por hablante, reconstruir contextos multi-personaje, y persistir la identidad entre sesiones.

**Archivos**: `db/chat_store.py`, `types/chat.py`

**[Listo]**

### 3. `[ID][SPEAK/ACT]` en mensajes del usuario

**Qué**: `_get_inference_messages()` ahora antepone `[PLAYER][SPEAK]` o `[PLAYER][ACT]` según el contenido.

**Por qué**: El modelo necesita saber quién habla y si es diálogo o acción. Además, detecta `[ROBERTO] texto` para multi-personaje.

**Detección multi-personaje**: Si el usuario escribe `[ROBERTO] text`, se convierte en `[ROBERTO][SPEAK] text`.

**Archivo**: `engine/chat.py`

**[Listo]**

### 4. Comando `/tag`

**Qué**: Nuevo comando `/tag <NOMBRE>` que cambia el tag del usuario para la sesión actual.

**Por qué**: El tag por defecto es `PLAYER`. Con `/tag LIU` los mensajes se etiquetan como `[LIU][SPEAK]`. Se persiste en SQLite via `state` table.

**Archivo**: `engine/slash_commands.py`

**[Listo]**

### 5. Tag automático para el personaje

**Qué**: Las respuestas del personaje se etiquetan automáticamente con su nombre en mayúsculas (`[LUNA][SPEAK]`, `[LUNA][ACT]`).

**Por qué**: El modelo ahora sabe que `[LUNA]` son sus propias respuestas. No hay ambigüedad.

**Archivo**: `engine/chat.py`

**[Listo]**

### 6. `[DEFINE]` en lugar de `[CHARACTER]` en ChromaDB

**Qué**: `_index_character_core()` ahora usa `[DEFINE][IDENTITY]`, `[DEFINE][BACKGROUND]`, etc.

**Por qué**: Consistencia con el sistema unificado de tags.

**Archivo**: `engine/character.py`

**[Listo]**

### 7. `[STATE]` en lugar de `[CONTEXT][CHARACTER]`

**Qué**: `compile_dynamic_prompt()` ahora genera `[STATE] Currently feeling {emotion}.`

**Por qué**: El tag `[STATE]` es más semántico y se alinea con el nuevo sistema.

**Archivo**: `compiler/compiler.py`

**[Listo]**

### 8. `TAG_DEFINITIONS` inyectado en base_prompt

**Qué**: Nueva sección `[GUÍA DE TAGS]` al final del prompt compilado, generada por `_resolve_tag_guide()`.

**Por qué**: El modelo necesita saber qué significa cada tag para usarlos correctamente.

**Ejemplo de la guía**:
```
[GUÍA DE TAGS]

[DEFINE] Permanent character definition...
[STATE] Current emotional, relational, and psychological state.
[SCENE] Current scene, location, environment...

[LUNA] is YOUR tag. Messages tagged with [LUNA] are YOUR responses.
When you see [SPEAK] you are speaking dialogue.
When you see [ACT] you are performing a physical action.
```

**Archivo**: `compiler/compiler.py`

**[Listo]**

### 9. `_split_tagged_response()` — separar acción + diálogo

**Qué**: Nueva función que post-procesa la respuesta del modelo. Si el modelo genera `[LUNA][ACT] *acción* diálogo`, lo separa en dos líneas.

**Por qué**: El modelo tiende a mezclar acción y diálogo en una misma línea etiquetada como `[ACT]`. El split garantiza que el frontend pueda renderizar correctamente.

**Antes**:
```
[LUNA][ACT] *Levanta la vista* ¿Q-qué quieres?
```

**Después**:
```
[LUNA][ACT] *Levanta la vista*
[LUNA][SPEAK] ¿Q-qué quieres?
```

**Archivo**: `engine/chat.py`

**[Listo]**

### 10. Tag guide mejorada con ejemplos correctos/incorrectos

**Qué**: Se agregaron ejemplos explícitos de cómo separar acción de diálogo en la guía de tags.

**Por qué**: El modelo necesita ver ejemplos concretos de lo que está bien y lo que está mal.

**Extracto**:
```
IMPORTANT: Always separate action from speech into different tagged lines.
Correct:
  [LUNA][ACT] *Looks down nervously*
  [LUNA][SPEAK] I am fine, thank you.

Incorrect (never mix action and speech in one line):
  [LUNA][ACT] *Looks down* I am fine.    ← WRONG
```

**Archivo**: `compiler/compiler.py`

**[Listo]**

### 11. `[SPEAK]` como tag universal en mensajes archivados

**Qué**: `_archive_to_chroma()` ahora guarda los mensajes como `[PLAYER][SPEAK] contenido` en vez de `[user]: contenido`.

**Por qué**: Consistencia: en runtime el modelo recibe `[PLAYER][SPEAK]`, en ChromaDB se archiva con el mismo formato.

**Metadatos adicionales**: `speaker_tag` en metadata de ChromaDB para filtrar por hablante.

**Archivo**: `engine/memory.py`

**[Listo]**

### 12. `set_state`/`get_state` en ChatStore

**Qué**: Nuevos métodos para guardar/leer estado de sesión en la tabla `state` de SQLite.

**Por qué**: El comando `/tag` necesita persistir el tag del usuario entre turnos y recargas.

**Archivo**: `db/chat_store.py`

**[Listo]**

## Problemas identificados durante el uso

### 1. El modelo mezcla acción y diálogo en una línea

Como se mencionó en el punto 9, el modelo genera `[ACT] *acción* diálogo` en vez de separarlo. La guía de tags mejorada + `_split_tagged_response()` lo resuelven parcialmente, pero el modelo puede necesitar más ejemplos para aprender consistentemente.

### 2. `[THOUGHT]` a veces aparece sin contenido

El modelo genera `[LUNA][THOUGHT]` seguido de `[LUNA][SPEAK]` sin contenido intermedio. Es un comportamiento menor que no afecta la calidad.

### 3. Los tags largos ocupan más tokens

`[LUNA][SPEAK]` son 14 caracteres vs `[USER]` que son 6. En conversaciones largas esto suma. Pero la claridad semántica compensa.

## Resultado final

```
Antes (v12):
  <|turn>user    [USER] Hola
  <|turn>model   Hola... (sin tag)

Después (v13+v14):
  <|turn>user    [LIU][SPEAK] Hola
  <|turn>model   [LUNA][ACT] *Levanta la vista*
                 [LUNA][SPEAK] ¿Q-qué quieres?
```

Cada mensaje tiene:
- **Identidad explícita**: quién habla
- **Tipo de contenido**: diálogo, acción o pensamiento
- **Separación clara**: acción y diálogo nunca mezclados
- **Persistencia**: speaker_tag en SQLite y ChromaDB
- **Multi-personaje**: el usuario puede rolear otros personajes con `[ROBERTO] texto`
