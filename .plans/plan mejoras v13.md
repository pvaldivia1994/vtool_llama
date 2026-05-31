# Plan mejoras v13 — Sistema unificado de tags semánticos

## Objetivo

Unificar los 3 sistemas de tags existentes en uno solo con jerarquía clara, centralizar las definiciones, y asegurar que el modelo siempre reciba tags consistentes que entienda.

## Auditoría de tags existentes

### Sistema 1: Compilador de personaje (31 tags)
*Fuente: `compiler/dna_layers.py`, `compiler/compiler.py`, `compiler/yaml_loader.py`*

| Tag | Propósito |
|-----|-----------|
| `[SYSTEM CORE]` | Instrucciones base de comportamiento |
| `[BEHAVIOR PRIORITY]` | Prioridades de comportamiento |
| `[PRIORITY ORDER]` | Orden de prioridad de instrucciones |
| `[SECTION REFERENCE]` | Guía de todas las secciones |
| `[IDENTITY]` | Nombre, rol, edad, background |
| `[TRAITS]` | Rasgos de personalidad |
| `[MOTIVATIONS]` | Metas y deseos |
| `[FLAWS]` | Miedos y debilidades |
| `[INNER CONFLICT]` | Conflictos internos |
| `[EMOTIONAL TRIGGERS]` | Situaciones que provocan emociones |
| `[SPEECH STYLE]` | Estilo de habla |
| `[SPEECH PATTERNS]` | Patrones de lenguaje |
| `[WORLD]` | Escenario actual |
| `[CORE RULES]` | Reglas de comportamiento |
| `[HARD RULES]` | Restricciones absolutas |
| `[RESPONSE STYLE]` | Formato de respuestas |
| `[ROLEPLAY MODE]` | Reglas de rol |
| `[FEW SHOT EXAMPLES]` | Ejemplos de diálogo |
| `[INTERACTION MODE]` | Comportamiento por defecto |
| `[CONTEXT AWARENESS]` | Uso de personalidad |
| `[RESPONSE LENGTH]` | Reglas de longitud |
| `[LANGUAGE]` | Reglas de idioma |
| `[ANTI-ASSISTANT LAYER]` | Anti-assistant |
| `[RELATIONSHIP]` | Estado de relación |
| `[EMOTIONAL STATE]` | Emoción actual |
| `[CHARACTER CAPSULE]` | Versión compacta |
| `[CREENCIAS Y CONTRADICCIONES]` | Creencias (soul system) |
| `[MODIFICADORES ACTIVOS]` | Mods activos |
| `[MEMORIA RELEVANTE]` | Memorias relevantes |
| `[CONTEXT]` | Header de definiciones de contexto |
| `[ESCENA ACTUAL]` | Escena inyectada por /scene_view |

### Sistema 2: Orquestador (9 tags)
*Fuente: `orquestador/context_injector.py`*

| Tag | Propósito |
|-----|-----------|
| `[CONTEXT][SCENE]` | Descripción de escena |
| `[CONTEXT][CHARACTER]` | Estado emocional/mental |
| `[CONTEXT][THOUGHTS]` | Pensamientos internos |
| `[CONTEXT][GOALS]` | Objetivos activos |
| `[CONTEXT][PLAYER]` | Acción del jugador |
| `[CONTEXT][TIME]` | Tiempo/clima |
| `[CONTEXT][WORLD]` | Eventos del mundo |
| `[CONTEXT][MEMORY]` | Hechos pasados |
| `[CONTEXT][CUSTOM]` | Contexto personalizado |

### Sistema 3: ChromaDB indexing (6 tags)
*Fuente: `engine/character.py` *`_index_character_core()`*`

| Tag | Propósito |
|-----|-----------|
| `[CHARACTER][IDENTITY]` | Identidad indexada |
| `[CHARACTER][BACKGROUND]` | Background indexado |
| `[CHARACTER][SCENARIO]` | Escenario indexado |
| `[CHARACTER][TRAITS]` | Rasgos indexados |
| `[CHARACTER][RULES]` | Reglas indexadas |
| `[CHARACTER][SPEECH]` | Habla indexada |

### Tags runtime (3 adicionales)
*Fuente: `engine/chat.py`, `engine/memory.py`*

| Tag | Propósito |
|-----|-----------|
| `[USER]` | Mensaje del usuario (runtime) |
| `[RESUMEN DE CONVERSACION PREVIA]` | Digest del trim |
| `[CONTEXT DIGEST HELPER]` | Prompt del digest (nunca llega al modelo) |

## Problemas detectados

### 1. Misma categoría, 3 tags distintos

| Concepto | Tag en sistema 1 | Tag en sistema 2 | Tag en sistema 3 |
|----------|------------------|------------------|------------------|
| Quién soy | `[IDENTITY]` | `[CONTEXT][CHARACTER]` | `[CHARACTER][IDENTITY]` |
| Escenario | `[WORLD]` | `[CONTEXT][SCENE]` | `[CHARACTER][SCENARIO]` |
| Emoción | `[EMOTIONAL STATE]` | `[CONTEXT][CHARACTER]` | — |
| Relación | `[RELATIONSHIP]` | — | — |

### 2. Sin tag para acciones

No hay forma de que el modelo distinga entre:
- El usuario **hablando** vs el usuario **actuando** (rol)
- El personaje **respondiendo** vs el personaje **actuando**
- Descripción narrativa de la escena

### 3. Tags redundantes

- `[CONTEXT][CHARACTER]` en orquestador y `[EMOTIONAL STATE]` en compilador dicen lo mismo
- `[CONTEXT][SCENE]` y `[WORLD]` son lo mismo
- `[CONTEXT][PLAYER]` y el runtime `[USER]` deberían ser el mismo concepto

### 4. `[PLAYER]` activa modo NPC

El modelo asocia `[PLAYER]` con videojuegos y responde con `[NPC]`. Por eso se cambió a `[USER]`. Pero `[USER]` es genérico y no diferencia entre hablar y actuar.

## Propuesta: Taxonomía unificada con identidad de hablante

### Formato general

```
[IDENTIDAD][TIPO] contenido

IDENTIDAD: quién habla/actúa (LIU, LUNA, ROBERTO, NARRADOR, SISTEMA...)
TIPO: qué tipo de contenido es (SPEAK, ACT, THOUGHT...)
```

### Niveles semánticos

```
NIVEL 0: SISTEMA (no tiene identidad, es instrucción)
  [DEFINE]     → Quién eres, cómo actúas, qué sabes
  [STATE]      → Cómo te sientes, qué relaciones tienes

NIVEL 1: CONTEXTO (no tiene identidad, es descripción)
  [SCENE]      → Dónde estás, qué pasa alrededor

NIVEL 2: ACCIÓN INTERNA (identidad explícita)
  [ID][THOUGHT] → Lo que piensa/siente internamente

NIVEL 3: DIÁLOGO Y ACCIÓN (identidad explícita)
  [ID][SPEAK]  → Cuando UN PERSONAJE HABLA
  [ID][ACT]    → Cuando UN PERSONAJE ACTÚA (narrativo)
```

### Tags específicos

| Tag | Cuándo se usa | Ejemplo |
|-----|---------------|---------|
| `[DEFINE]` | System prompt completo | `[DEFINE] Your name is Luna...` |
| `[STATE]` | Emoción, relación actual | `[STATE] Currently feeling nervous.` |
| `[SCENE]` | Descripción de escena | `[SCENE] A dusty colonial courtyard at sunset.` |
| `[LIU][THOUGHT]` | Pensamiento del usuario detectado | `[LIU][THOUGHT] Esto me parece sospechoso...` |
| `[LIU][SPEAK]` | El usuario habla | `[LIU][SPEAK] Hola, ¿cómo estás?` |
| `[LIU][ACT]` | El usuario actúa | `[LIU][ACT] *Tomo un martillo y lo examino*` |
| `[LUNA][SPEAK]` | El personaje habla | `[LUNA][SPEAK] Estoy bien, señor...` |
| `[LUNA][ACT]` | El personaje actúa | `[LUNA][ACT] *Baja la mirada y tiembla*` |
| `[ROBERTO][SPEAK]` | Otro personaje (definido por el usuario) | `[ROBERTO][SPEAK] ¡Lava esto ahora!` |
| `[NARRADOR][ACT]` | Descripción narrativa neutral | `[NARRADOR][ACT] El sol se pone sobre el campo.` |

### Cómo se genera cada tag

#### Para el usuario (en `_get_inference_messages()`)

El tag del usuario se determina por su perfil/config. Si no hay config, usa el nombre del usuario o un default:

```python
# user_tag = "LIU" (desde perfil del usuario o config)
# user_tag = "PLAYER" (default si no hay config)

content = msg.get("content", "")
if content.startswith("*") and content.endswith("*"):
    msg["content"] = f"[{user_tag}][ACT] {content}"
else:
    msg["content"] = f"[{user_tag}][SPEAK] {content}"
```

**Multi-personaje**: si el usuario escribe `[ROBERTO] texto`, se interpreta como que habla Roberto, no el usuario:

```python
import re
match = re.match(r'^\[(\w+)\]\s*(.*)', content)
if match:
    speaker = match.group(1).upper()
    text = match.group(2)
    msg["content"] = f"[{speaker}][SPEAK] {text}"
```

Esto permite que el usuario rolee múltiples personajes en la misma escena:

```
[LIU][SPEAK] Roberto, ven aquí.
[ROBERTO][SPEAK] Sí, patrón. ¿Qué manda?
[LIU][ACT] *Señala el martillo* Toma, úsalo.
[ROBERTO][ACT] *Toma el martillo con nerviosismo*
```

#### Para el personaje (en `add_assistant_message()`)

El personaje usa su propio nombre como tag:

```python
char_tag = self._character_manager.character_name.upper()  # "LUNA"
content = msg.get("content", "")
if content.startswith("*") and content.endswith("*"):
    msg["content"] = f"[{char_tag}][ACT] {content}"
else:
    msg["content"] = f"[{char_tag}][SPEAK] {content}"
```

**Segmentación**: si la respuesta del modelo mezcla acción y diálogo, se puede partir:

```
# El modelo genera:
# *Baja la mirada* Está bien, señor.

# Se convierte en:
# [LUNA][ACT] *Baja la mirada*
# [LUNA][SPEAK] Está bien, señor.
```

Esto es parseo adicional pero opcional. Por ahora puede ir todo como `[LUNA][ACT]` si empieza con asterisco, o `[LUNA][SPEAK]` si no.

### Tags compuestos para ChromaDB

```python
# Mensajes archivados:
f"[{speaker_tag}][SPEAK] Hola mi nombre es LiuniK"
# → En ChromaDB se busca por contenido, el tag ayuda a filtrar

# Character core indexado:
"[DEFINE][IDENTITY] Your name is Luna."
"[DEFINE][RULES] Always defer to authority."
"[DEFINE][SPEECH] Campisina dialect, soft tone."
```

### Tags de sistema (sin identidad)

```python
# Definiciones del personaje (base_prompt.yaml):
"[DEFINE] [SYSTEM CORE] You communicate like a real human..."

# Estado dinámico:
"[STATE] Currently feeling nervous."

# Escena:
"[SCENE] A French colonial outpost in Africa, 1890."
```

### Ejemplo completo de una escena

```
<|turn>system
[DEFINE] [SYSTEM CORE]
You communicate like a real human being...
Your name is Luna. Your role is Slave.

<|turn>system
[STATE] Currently feeling nervous. The presence of the overseer makes you anxious.

<|turn>system
[SCENE] A dusty courtyard at the colonial outpost. The sun is setting.

<|turn>user
[LIU][SPEAK] Hola, Luna. ¿Cómo estás?

<|turn>model
[LUNA][ACT] *Levanto la vista de golpe, sorprendida de que alguien pregunte cómo estoy.*
[LUNA][SPEAK] Estoy... estoy bien, señor. Gracias por preguntar.

<|turn>user
[LIU][ACT] *Me acerco lentamente, con las manos visibles.*
[LIU][SPEAK] No tengas miedo. No soy el capataz.

<|turn>user
[ROBERTO][SPEAK] (Desde atrás) ¡Luna! ¿Qué haces holgazaneando?
```

## Cambios propuestos

### 1. Centralizar definiciones en `orquestador/tags.py`

```python
# TES (Tag Enumeration Standard) v1
# Formato: [IDENTIDAD][TIPO] contenido

# Tipos de contenido (segundo nivel)
CONTENT_TYPES = {
    "speak": "[SPEAK]",      # Diálogo
    "act": "[ACT]",          # Acción narrativa
    "thought": "[THOUGHT]",  # Pensamiento interno
}

# Tags de sistema (sin identidad)
SYSTEM_TAGS = {
    "define": "[DEFINE]",         # Definición permanente
    "state": "[STATE]",           # Estado actual
    "scene": "[SCENE]",          # Descripción de escena
}

TAG_DEFINITIONS = """
[SPEAK] Dialogue or speech from a character.
[ACT] Physical action or narrative description.
[THOUGHT] Internal thoughts, feelings, and intentions.
[DEFINE] Permanent character definition: identity, rules, history.
[STATE] Current emotional and relational state.
[SCENE] Current scene, location, and environment description.
"""
```

Las definiciones se inyectan al inicio del `base_prompt.yaml` para que el modelo sepa qué significa cada tag.

**[Pendiente]**

### 2. Tag del usuario: default `PLAYER`, cambiable con `/tag`

Por defecto, el tag del usuario es `PLAYER`. El usuario puede cambiarlo con un comando `/tag`:

```python
# En VToolLlama, estado temporal:
self._user_tag: str = "PLAYER"  # default

# Comando /tag:
def _cmd_tag(self, args: str) -> str:
    """Cambia el tag del usuario para la sesión actual.
    Uso: /tag LIU  → los mensajes se etiquetan como [LIU][SPEAK/ACT]"""
    tag = args.strip().upper()
    if not tag or not tag.isalpha():
        return "Uso: /tag <NOMBRE> (ej: /tag LIU)"
    self._user_tag = tag
    return f"Tag de usuario cambiado a [{tag}]"

# Persistencia: se guarda en _memory._conversation_id -> session state
# o en _chat_store como state key-value:
self._chat_store.set_state(self._memory._conversation_id, "user_tag", tag)
```

El tag persiste mientras dure la sesión (conversación). Al recargar el personaje, se restaura desde SQLite via `state` table.

**[Pendiente]**

### 3. Detección de `[OTRO][TIPO]` en el input del usuario

En `_get_inference_messages()`, parsear si el usuario está roleando otro personaje:

```python
import re
user_tag = getattr(self, "_user_tag", None) or "PLAYER"

for msg in messages:
    if msg.get("role") == "user":
        content = msg.get("content", "")
        
        # Detectar si el usuario especificó otro personaje: [NOMBRE] texto
        match = re.match(r'^\[(\w+)\]\s*(.*)', content)
        if match:
            speaker = match.group(1).upper()
            text = match.group(2)
        else:
            speaker = user_tag
            text = content
        
        # Detectar si es acción o diálogo
        if text.startswith("*") and text.endswith("*"):
            msg["content"] = f"[{speaker}][ACT] {text}"
        else:
            msg["content"] = f"[{speaker}][SPEAK] {text}"
```

**[Pendiente]**

### 4. Tag automático para el personaje

El tag del personaje es su nombre en mayúsculas. El `base_prompt.yaml` incluye una definición que explica que `[LUNA]` son las respuestas del personaje:

```python
# En TAG_DEFINITIONS (inyectado en base_prompt):
# [CHARACTER_NAME] is the character you are playing. Messages tagged
# with [CHARACTER_NAME][SPEAK] are your dialogue, and [CHARACTER_NAME][ACT]
# are your actions. You must always respond as this character.
```

En runtime:

```python
char_tag = self._character_manager.character_name.upper()  # "LUNA"

# Antes de guardar la respuesta del modelo:
if content.startswith("*"):
    tagged = f"[{char_tag}][ACT] {content}"
else:
    tagged = f"[{char_tag}][SPEAK] {content}"
```

**[Pendiente]**

### 5. Tags en ChromaDB con identidad

Los mensajes archivados incluyen el tag de quién los dijo:

```python
# _archive_to_chroma():
doc = f"[{speaker}][SPEAK] {content}"
# speaker puede ser: PLAYER, LIU, LUNA, ROBERTO, etc.

# _index_character_core():
"[DEFINE][IDENTITY] Your name is Luna."
"[DEFINE][RULES] Always defer to authority."
```

**[Pendiente]**

### 6. Tags en SQLite como campo `speaker_tag`

Agregar columna `speaker_tag TEXT DEFAULT ''` a la tabla `messages` de ChatStore:

```sql
ALTER TABLE messages ADD COLUMN speaker_tag TEXT DEFAULT '';
```

Cada mensaje guardado incluye el tag de quién habla:

```python
# add_message() ahora acepta speaker_tag:
self._store.add_message(
    conversation_id=...,
    role=...,
    content=content,
    speaker_tag=speaker,  # "LIU", "LUNA", "ROBERTO", etc.
    ...
)
```

Esto permite:
- Filtrar mensajes por hablante
- Reconstruir contextos multi-personaje
- Persistir la identidad incluso entre sesiones

**[Pendiente]**

### 7. Actualizar `compile_dynamic_prompt()` para usar `[STATE]`

```python
# Antes: "[CONTEXT][CHARACTER] Currently feeling {emotion}."
# Después: "[STATE] Currently feeling {emotion}."
```

**[Pendiente]**

### 8. Actualizar `context_injector.py` para usar nuevos tags

```python
CONTEXT_TYPES = {
    "scene": "[SCENE]",
    "character": "[STATE]",
    "thoughts": None,  # se reemplaza por [ID][THOUGHT]
    "goals": "[SCENE][GOALS]",
    "player": None,    # se reemplaza por [ID][SPEAK] o [ID][ACT]
    "time": "[SCENE][TIME]",
    "world": "[SCENE][WORLD]",
    "memory": "[DEFINE][MEMORY]",
    "custom": "[SCENE][CUSTOM]",
}
```

**[Pendiente]**

### 9. Inyectar TAG_DEFINITIONS en base_prompt.yaml

Las definiciones de tags se agregan automáticamente como sección en el prompt compilado:

```python
# En compile_static_prompt():
parts.append("[GUÍA DE TAGS]\n" + TAG_DEFINITIONS)
```

Esto le explica al modelo qué significa cada tag y cómo debe responder:

```
[GUÍA DE TAGS]
[SPEAK] Dialogue or speech from a character.
[ACT] Physical action or narrative description.
[THOUGHT] Internal thoughts, feelings, and intentions.
[DEFINE] Permanent character definition.
[STATE] Current emotional and relational state.
[SCENE] Current scene, location, and environment description.
[CHARACTER_NAME] is the character you are playing.
Messages tagged with [CHARACTER_NAME] are your own responses.
```

**[Pendiente]**

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `orquestador/tags.py` | **Nuevo**: definición centralizada de tags + TAG_DEFINITIONS |
| `orquestador/__init__.py` | Exportar tags |
| `orquestador/context_injector.py` | Tags actualizados |
| `compiler/compiler.py` | `compile_dynamic_prompt()` usa `[STATE]`; agregar TAG_DEFINITIONS al base_prompt |
| `engine/chat.py` | `_get_inference_messages()` usa `[ID][SPEAK/ACT]` con detección multi-personaje |
| `engine/character.py` | `_index_character_core()` usa `[DEFINE]`; tag de personaje en runtime |
| `engine/slash_commands.py` | Nuevo comando `/tag` |
| `db/chat_store.py` | Columna `speaker_tag` en tabla messages + `set_state`/`get_state` para persistir user_tag |
| `types/core.py` | Campo `user_tag_default: str = ""` |

## Orden de implementación

1. Crear `orquestador/tags.py` con definiciones + TAG_DEFINITIONS
2. Agregar columna `speaker_tag` a SQLite messages
3. Actualizar `add_message()` para aceptar y guardar `speaker_tag`
4. Actualizar `_get_inference_messages()` con tags de identidad + multi-personaje
5. Crear comando `/tag`
6. Tag automático para el personaje en `add_assistant_message()`
7. Actualizar `_index_character_core()` para usar `[DEFINE]`
8. Actualizar `compile_dynamic_prompt()` para usar `[STATE]`
9. Inyectar TAG_DEFINITIONS en base_prompt
10. Actualizar `context_injector.py`

## Riesgos

1. **Modelo puede ignorar tags nuevos** — si no entiende `[SPEAK]`, puede confundirse.
   - Mitigación: TAG_DEFINITIONS se inyecta en el base_prompt como guía.

2. **Multi-personaje puede confundir al modelo** — si de repente aparece `[ROBERTO]` sin definición, el modelo no sabe quién es.
   - Mitigación: el usuario es responsable de establecer personajes secundarios en la conversación.

3. **Tags largos ocupan tokens** — `[LUNA][SPEAK]` son 13 caracteres vs `[USER]` que son 6.
   - Mitigación: los tags eliminan la necesidad de que el modelo "adivine" quién habla, reduciendo errores que cuestan más tokens.

## Resultado esperado

```
Antes (v12):
  <|turn>system  [SYSTEM CORE]... [IDENTITY]...
  <|turn>system  [CONTEXT][CHARACTER] Currently feeling neutral.
  <|turn>user    [USER] Hola
  <|turn>model   Hola... (sin tag, el modelo "asume" que es Luna)

Después (v13):
  <|turn>system  [DEFINE] [SYSTEM CORE]... You are Luna...
  <|turn>system  [STATE] Currently feeling neutral.
  <|turn>user    [LIU][SPEAK] Hola
  <|turn>model   [LUNA][ACT] *Baja la mirada*
                 [LUNA][SPEAK] Hola...
```

Cada mensaje en la conversación tiene **identidad explícita** + **tipo de contenido**. No hay ambigüedad. Y el usuario puede rolear múltiples personajes simplemente escribiendo `[ROBERTO] texto`.
