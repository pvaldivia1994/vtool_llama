# Plan mejoras v18 — Migración a prosa natural roleplay

## Objetivo

Reemplazar el sistema de tags bracket (`[ASSISTANT=X][SAYS/DOES/THINKS]`) por el formato de prosa natural que es el estándar de la comunidad roleplay (~90% de adopción en SillyTavern, RisuAI, Agnai).

## Diagnóstico

### Problema actual

El sistema v17 usa tags bracket en cada mensaje:

```
[USER=LiuniK][SAYS] Hola
[ASSISTANT=Luna][DOES] *sonríe*
[ASSISTANT=Luna][SAYS] Hola, ¿cómo estás?
[ASSISTANT=Luna][THINKS] *Es amable*
```

**Problemas:**

1. **Formato antinatural**: Ningún modelo fue entrenado con `[ROLE=X][TYPE]`. El modelo tiene que "aprender" el formato desde cero en cada generación, gastando capacidad del system prompt.
2. **Separación forzada acción/diálogo**: El sistema fuerza líneas separadas para `[DOES]` y `[SAYS]`, mientras que el estándar roleplay las combina: `*sonríe* Hola, ¿cómo estás?`
3. **~25 tokens de overhead por línea**: `[ASSISTANT=Luna][SAYS]` vs `Luna: ` — el formato bracket triplica el overhead del prefijo.
4. **Múltiples regex frágiles**: `_split_tagged_response()` usa 5 patrones regex para re-ensamblar acciones y diálogo que el modelo nunca debió separar.
5. **Aislamiento del ecosistema**: Ninguna otra herramienta roleplay usa este formato. Impide interoperabilidad.
6. **Los pensamientos como `[THINKS]` se pierden**: Al ser una línea separada, el modelo los trata como un mensaje independiente en vez de parte de su flujo narrativo.

### Investigación: el estándar comunitario

Fuentes: Ali:Chat v1.5 (145k+ views, rentry.co/alichat), kingbri's MinimALIstic (103k+ views), SillyTavern docs, Trappu's PLists.

| Elemento | Formato estándar | Ejemplo |
|----------|-----------------|---------|
| Acción | `*asteriscos*` | `*Ella sonríe cálidamente*` |
| Diálogo | Texto plano (sin comillas) | `Hola, ¿cómo estás?` |
| Pensamiento | `<Nombre piensa: ...>` | `<Luna piensa: Espero que le guste.>` |
| Combinado inline | `*acción* diálogo` | `*Sonríe* Estoy bien, gracias` |
| Prefijo (chat) | `Nombre: ` | `Luna: *Sonríe* Hola` |
| Varias acciones | `*acción1* *acción2*` o separado por `.` | `*Camina lentamente y suspira.*` |
| Narración | Mismo `*asteriscos*` que acción | `*El castillo se alza imponente.*` |

El resultado en una conversación real se ve así:

```
LiuniK: Hola Luna, ¿cómo estás hoy?

Luna: *Levanta la vista y sonríe con calidez* ¡Hola! Estoy bien, estaba leyendo un libro interesante. *Cierra el libro y se inclina hacia adelante* ¿Y tú? <Luna piensa: Se ve cansado, espero que esté bien.>
```

## Cambios propuestos

### 1. Nuevo formato de conversación en prosa

**Antes (v17):**
```
[USER=LiuniK][SAYS] Hola Luna
[ASSISTANT=Luna][DOES] *Sonríe*
[ASSISTANT=Luna][SAYS] ¡Hola! ¿Cómo estás?
[ASSISTANT=Luna][THINKS] *Qué alegría verlo*
```

**Después (v18):**
```
LiuniK: Hola Luna

Luna: *Sonríe con calidez* ¡Hola! ¿Cómo estás? <Luna piensa: Qué alegría verlo.>
```

### 2. Nueva guía de formato en el system prompt

Reemplazar `TAG_DEFINITIONS` y `_resolve_tag_guide()` por una guía de prosa natural:

```
[ROLEPLAY FORMAT]

Write as your character using natural roleplay prose:

- *asterisks* for actions and narration
- Plain text for dialogue (no quotation marks)
- <Character's thoughts: ...> for internal thoughts
- Combine action + dialogue inline: *action* dialogue
- Prefix each response with your name

Example:
Luna: *Looks up and smiles warmly* Hello! How are you? <Luna thinks: I hope he's doing well.>
```

### 3. Eliminar taggeo de user messages

`_get_inference_messages()` ya no envuelve en `[USER=X][SAYS]`:

- Antes: `[USER=LiuniK][SAYS] Hola`
- Después: `LiuniK: Hola`

El nombre del user se obtiene de `self._memory._user_tag` y se usa como prefijo directo. El multi-personaje (`[ROBERTO] texto`) se convierte a `Roberto: texto`.

### 4. Eliminar `_split_tagged_response()` y su parser

Ya no se necesita separar `[DOES]` de `[SAYS]` porque el modelo genera prosa natural directamente. Se reemplaza por un validador mínimo que:

- Elimina whitespace extremo
- Verifica que el nombre del personaje esté como prefijo (si no, lo añade)
- Pasa el texto sin transformación

### 5. Pensamientos como `<label: ...>` en línea

Los pensamientos (`[ASSISTANT=X][THINKS]`) se renderizan como `<Character's thoughts: ...>` y se inyectan **dentro** del mismo mensaje del asistente, no como un mensaje aparte.

- Antes: mensaje system separado con `[ASSISTANT=Luna][THINKS] *texto*`
- Después: `Luna: *acción* diálogo <Luna piensa: texto>` — todo en el mismo assistant message

`_inject_char_thoughts()` cambia a añadir el pensamiento inline al último mensaje assistant o al próximo que se genere.

### 6. Simplificar el InlineProcessor

- `InlineProcessor._tag_segment()` ya no produce tags bracket. Produce directamente el texto formateado.
- `#comandos` se mantienen igual (son procesamiento previo, no formato de salida).
- `*acción*` y `texto normal` del usuario se renderizan como `LiuniK: *acción* texto normal`.

### 7. Actualizar fuentes de formato en system prompt

| Archivo | Cambio |
|---------|--------|
| `roleplay_mode.yaml` | Reemplazar ejemplos de tags bracket por prosa |
| `anti_assistant.yaml` | Actualizar referencias a formato de tags |
| `compiler/yaml_loader.py` `_resolve_roleplay_interaction()` | Cambiar ejemplos hardcodeados |
| `compiler/compiler.py` `_resolve_tag_guide()` | Nueva guía de prosa natural |
| `orquestador/tags.py` | Mantener como referencia/compat (deprecar) |

### 8. Mensajes históricos en SQLite

Los mensajes existentes con tags bracket se renderizan correctamente porque son texto plano. Los nuevos mensajes se guardan en prosa. No hay migración de datos necesaria — el contenido de SQLite es opaco al formato.

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `engine/chat.py` (`_get_inference_messages`) | Eliminar taggeo `[USER=X][SAYS]`, usar `Nombre: texto` |
| `engine/chat.py` (`_split_tagged_response`) | Reemplazar por `_validate_prose_response()` — sin regex |
| `engine/chat.py` (`_inject_char_thoughts`) | Pensamientos inline `<X piensa: ...>` en assistant message |
| `engine/chat.py` (`chat`) | Simplificar flujo de post-procesamiento |
| `engine/inline.py` | `_tag_segment()` y `_build_messages()` a prosa |
| `orquestador/tags.py` | Deprecar. Mantener constantes para compat |
| `compiler/compiler.py` (`_resolve_tag_guide`) | Nueva guía de prosa natural |
| `compiler/yaml_loader.py` (`_resolve_roleplay_interaction`) | Ejemplos en prosa |
| `characters/default/roleplay_mode.yaml` | Formato en prosa |
| `characters/default/anti_assistant.yaml` | Actualizar referencias |

## Archivos que NO cambian

- `db/chat_store.py` — almacena content raw, no necesita cambios
- `engine/chat_memory.py` — el deque es agnóstico al formato
- `config/*.jinja` — los templates son wrappers de tokenización, no les importa el contenido
- `config/prompts/*.md` — los headers `[IDENTITY]`, `[TRAITS]`, etc. son seccionales, no formato de respuesta
- `model/` — el motor de inferencia es agnóstico al formato
- `tools/` — tool calling usa JSON nativo (OpenAI format), independiente
- `types/` — dataclasses internas

## Riesgos

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|---------|------------|
| Modelo mezcla narración en 3a persona | Baja | Bajo | Instruct en system prompt: "you are the character, act as them" |
| Modelo usa `"comillas"` en vez de texto plano | Media | Bajo | No es error, solo menos óptimo. Se acepta como variante válida |
| Modelo no usa `<>` para pensamientos | Media | Bajo | Los pensamientos se pierden pero la respuesta sigue siendo válida |
| Multi-personaje sin tags bracket se confunde | Baja | Medio | El prefijo `Nombre:` resuelve quién habla |
| Pensamientos en `< >` se renderizan como HTML | Media | Bajo | Escapar o filtrar en la UI |
| Tests existentes fallan por cambio de formato | Alta | Alto | Actualizar fixtures de tests |

## Resultado esperado

- El modelo responde en prosa natural como cualquier personaje roleplay:
  ```
  Luna: *Sonríe* ¡Hola! ¿Cómo estás? <Luna piensa: Qué bonito día.>
  ```
- Se eliminan ~50+ líneas de regex y lógica de post-procesamiento
- El system prompt se simplifica (menos instrucciones de formato)
- El modelo puede expresarse con fluidez natural sin restricciones de tags
- Los pensamientos fluyen naturalmente como parte de la respuesta
- Compatibilidad con el ecosistema roleplay (SillyTavern, etc.)
- El InlineProcessor y comandos `#` del usuario funcionan igual
