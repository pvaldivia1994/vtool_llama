# Plan mejoras v17 — Tags literales `[USER=]` / `[ASSISTANT=]` + `[SAYS]` / `[DOES]` / `[THINKS]`

## Objetivo

Reemplazar todos los tags por nombres literales que el modelo entienda sin ambigüedad: `[USER=]` / `[ASSISTANT=]` para la identidad, y verbos concretos (`[SAYS]`, `[DOES]`, `[THINKS]`) para la acción.

## Diagnóstico

### Problema actual

El modelo confunde `[LUNA]`, `[LIUNIK]`, `[ROBERTO]` porque todos son `[NOMBRE][TIPO]` sin jerarquía:

```
user: [LIUNIK][SPEAK] Hola
assistant: [LUNA][ACT] *mira*
assistant: [LUNA][SPEAK] Hola
user: [ROBERTO][SPEAK] Vete
```

Además:
- `[SPEAK]` es técnico (to speak), no describe el acto de decir algo
- `[ACT]` es ambiguo (actuar/acción teatral)
- `[THOUGHT]` es sustantivo, el modelo responde mejor a verbos en presente

### Filosofía: tags como inglés literal

Cada tag debe poder leerse como una oración en inglés:

| Tag | Se lee | Significa |
|-----|--------|----------|
| `[USER=X][SAYS]` | "User X says" | El humano X dice |
| `[ASSISTANT=X][SAYS]` | "Assistant X says" | El personaje X dice |
| `[ASSISTANT=X][DOES]` | "Assistant X does" | X realiza una acción |
| `[ASSISTANT=X][THINKS]` | "Assistant X thinks" | X piensa internamente |

Sin ambigüedad. Sin necesidad de consultar una guía.

## Mapeo completo de sintaxis a tags

### Tags de identidad

| Tag actual | Nuevo | Se lee |
|------------|-------|--------|
| `[LUNA]` | `[ASSISTANT=Luna]` | "Assistant Luna" |
| `[LIUNIK]` | `[USER=LIUNIK]` | "User LIUNIK" |
| `[PLAYER]` | `[USER=PLAYER]` | "User PLAYER" (default) |
| `[ROBERTO]` | `[USER=Roberto]` | "User Roberto" (multi-personaje) |

### Tags de acción

| Tag actual | Nuevo | Se lee |
|------------|-------|--------|
| `[SPEAK]` | `[SAYS]` | "says" |
| `[ACT]` | `[DOES]` | "does" |
| `[THOUGHT]` | `[THINKS]` | "thinks" |

### Tags de sistema (contexto)

| Sintaxis | Contexto inyectado | Se lee |
|----------|-------------------|--------|
| `[TEXTO]` | `[CONTEXT][SCENE] texto` | "Scene: texto" |
| `(texto)` | `[CONTEXT][TIME] texto` | "Time: texto" |
| `#char / -texto-` | `[ASSISTANT=Luna][THINKS] *texto*` | "Assistant Luna thinks: texto" |
| `#time` | `[CONTEXT][TIME] texto` | "Time: texto" |
| `#world` | `[CONTEXT][WORLD] texto` | "World: texto" |
| `#goal` | `[CONTEXT][GOALS] texto` | "Goals: texto" |

### Tags de output del modelo

El modelo genera sus respuestas usando:

```
[ASSISTANT=Luna][DOES] *acción narrativa*
[ASSISTANT=Luna][SAYS] diálogo
[ASSISTANT=Luna][THINKS] *pensamiento interno*
```

### Tags de inline del usuario

| Marcador | Tag que recibe el segmento |
|----------|---------------------------|
| `*acción*` | `[USER=Tag][DOES] *acción*` |
| `:pensamiento:` | `[USER=Tag][THINKS] pensamiento` (sin `:`) |
| texto normal | `[USER=Tag][SAYS] texto` |
| `[ROBERTO] texto` | `[USER=Roberto][SAYS] texto` |

### Ejemplo completo

```
Usuario escribe:  *Entro sigilosamente* [CUECA OSCURA] :esto es peligroso: hay alguien #world hay estalactitas#

Pipeline:
  [CUECA OSCURA] → [CONTEXT][SCENE] CUECA OSCURA (se elimina del texto)
  #world → [CONTEXT][WORLD] hay estalactitas (se elimina del texto)
  *Entro sigilosamente* → se etiqueta [USER=LIUNIK][DOES]
  :esto es peligroso: → se etiqueta [USER=LIUNIK][THINKS] (sin :)
  hay alguien → se etiqueta [USER=LIUNIK][SAYS]

Lo que ve el modelo:
  system: [CONTEXT][SCENE] CUECA OSCURA
  system: [CONTEXT][WORLD] hay estalactitas
  user: [USER=LIUNIK][DOES] *Entro sigilosamente*
  user: [USER=LIUNIK][THINKS] esto es peligroso
  user: [USER=LIUNIK][SAYS] hay alguien

El modelo lee:
  "Scene is CUECA OSCURA. World has stalactites."
  "User LIUNIK does: enters silently."
  "User LIUNIK thinks: this is dangerous."
  "User LIUNIK says: someone there."
```

## Cambios propuestos

### 1. `orquestador/tags.py` — Tag definitions

```python
TAG_DEFINITIONS = """
[GUÍA DE TAGS]

[USER=Name][SAYS]    → The human player named "Name" speaks.
[USER=Name][DOES]    → The human player named "Name" performs an action.
[USER=Name][THINKS]  → The human player named "Name" has an internal thought.

[ASSISTANT=Name][SAYS]    → The character "Name" speaks. This is you.
[ASSISTANT=Name][DOES]    → The character "Name" performs an action. This is you.
[ASSISTANT=Name][THINKS]  → The character "Name" has an internal thought. This is you.

You are [ASSISTANT=Luna]. All your responses MUST use [ASSISTANT=Luna][...] tags.

[DEFINE] Permanent character definition.
[STATE] Current emotional, relational, and psychological state.
[SCENE] Current scene, location, environment.
[CONTINUE] Continue the scene without player input.
"""
```

### 2. `engine/inline.py` — Tags actualizados

```python
# En _tag_segment:
# *acción* → ("DOES", contenido)   preserva *
# :pensamiento: → ("THINKS", contenido)  limpia :
# normal → ("SAYS", contenido)

# En chat() al armar:
tagged = f"[USER={user_tag}][{msg['tag']}] {msg['content']}"
# Ej: → "[USER=LIUNIK][DOES] *mira*"
```

### 3. `engine/chat.py` — `_get_inference_messages()`

```python
def _get_inference_messages(self: VToolLlama) -> list[dict]:
    messages = self._memory.get_context_messages()
    user = self._user_tag or "PLAYER"

    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not content:
            continue

        # Ya pre-tagueado por InlineProcessor
        if re.match(r'^\[(?:USER|ASSISTANT)=\w+\]\[(?:SAYS|DOES|THINKS)\]', content):
            continue

        # Multi-personaje: [ROBERTO] texto → [USER=Roberto][SAYS]
        m = re.match(r'^\[(\w+)\]\s+(.*)', content)
        if m and m.group(1).isupper() and len(m.group(1)) <= 12:
            msg["content"] = f"[USER={m.group(1).capitalize()}][SAYS] {m.group(2)}"
            continue

        # Default → [USER=Tag][SAYS]
        msg["content"] = f"[USER={user}][SAYS] {content}"

    return messages
```

### 4. `engine/chat.py` — `_split_tagged_response()`

Actualizar regex para nuevo formato:

```python
# [ASSISTANT=Luna][DOES] *accion* texto_extra
m = re.match(r'^\[ASSISTANT=(\w+)\]\[DOES\]\s+(\*[^*]+\*)\s*(.*)', line)
# [ASSISTANT=Luna][SAYS] con asteriscos al inicio
m = re.match(r'^\[ASSISTANT=(\w+)\]\[SAYS\]\s+(\*[^*]+\*)\s*(.*)', line)
```

### 5. `engine/memory.py` — `_archive_to_chroma()`

```python
prefix = f"[USER={speaker_tag}]" if msg.role == "user" else f"[ASSISTANT={speaker_tag}]"
document = f"{prefix}[SAYS] {msg.content}"
```

### 6. `compiler/compiler.py` — Tag guide

Actualizar ejemplos y descripciones a `[USER=]`, `[ASSISTANT=]`, `[SAYS]`, `[DOES]`, `[THINKS]`.

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `orquestador/tags.py` | TAG_DEFINITIONS + constantes SAYS/DOES/THINKS |
| `engine/inline.py` | `_tag_segment()` retorna SAYS/DOES/THINKS |
| `engine/chat.py` | `_get_inference_messages()`, `_split_tagged_response()`, armado `[USER=]` |
| `engine/memory.py` | `_archive_to_chroma()` prefix |
| `compiler/compiler.py` | `_resolve_tag_guide()` ejemplos |

## Riesgos

1. **Chat history existente**: mensajes en SQLite/ChromaDB con formato antiguo. Al recargar, `_get_inference_messages()` los detecta como "ya pre-tagueados" y no los modifica. Convivirán ambos formatos hasta que se purge el historial.

2. **Modelo no familiarizado con `[DOES]`**: `[ACT]` existe en muchos fine-tunes. `[DOES]` es más raro pero más literal. La guía de tags se inyecta en el system prompt para que el modelo aprenda en caliente.

3. **`[SAYS]` en inglés mezclado con español**: los tags están en inglés (estándar en LLM), el contenido en español. Es la práctica recomendada.

## Resultado esperado

```
Antes:
  user: [LIUNIK][SPEAK] Hola
  assistant: [LUNA][ACT] *mira*
  assistant: [LUNA][SPEAK] Hola
  user: [ROBERTO][SPEAK] Vete

Después:
  user: [USER=LIUNIK][SAYS] Hola
  assistant: [ASSISTANT=Luna][DOES] *mira*
  assistant: [ASSISTANT=Luna][SAYS] Hola
  user: [USER=Roberto][SAYS] Vete

Con #char:
  Usuario:  Hola -quiero que venga- como estas?

  system: [ASSISTANT=Luna][THINKS] *quiero que venga*
  user: [USER=LIUNIK][SAYS] Hola
  user: [USER=LIUNIK][SAYS] como estas?

Lectura literal:
  "Assistant Luna thinks: quiero que venga"  ← pensamiento actual del personaje
  "User LIUNIK says: Hola"
  "User LIUNIK says: como estas?"
  → El modelo NO puede confundir quién es quién.
```
