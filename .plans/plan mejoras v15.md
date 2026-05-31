# Plan mejoras v15 — Sistema de comandos inline para roleplay

## Objetivo

Tres mecanismos inline dentro del mensaje de chat que permitan al usuario manipular escena, personaje y acciones sin salir del flujo de roleplay.

---

## Diagnóstico

### Mecanismos actuales

| Mecanismo | Estado | Problema |
|-----------|--------|----------|
| Slash commands `/` | ✅ Funcional | No llegan al LLM, son admin |
| `[context tipo texto]` inline | ✅ Funcional | Verboso, `_extract_inline_context` en `chat.py:110` |
| `#mem texto` | ✅ Funcional | Hardcodeado en `chat.py:384`, no extensible |
| `_user_tag` | ⚠️ Existe pero **no se usa** | Definido en `base.py:153` pero ignorado en todo el flujo de chat |
| Multi-personaje `[ROBERTO] texto` | ❌ Documentado pero **no implementado** | Solo existe en `DETA.md`, `_get_inference_messages()` usa `[USER]` hardcodeado |

### Bugs existentes que v15 debe corregir

1. **`_get_inference_messages()` (`chat.py:17-26`) usa `[USER]` hardcodeado** — ignora `self._user_tag`. Si el usuario hace `/tag LIU`, sus mensajes siguen etiquetándose `[USER]`.
2. **`add_user_message()` (`chat_memory.py:205`) acepta `speaker_tag` pero nunca se pasa desde `chat()`** — el tag no persiste en SQLite.
3. **Detección multi-personaje `[ROBERTO]` no existe** — documentado en v14 pero jamás implementado.
4. **`_archive_to_chroma()` usa `"PLAYER"` fijo** — no respeta `_user_tag`.
5. **No hay detección de `*acción*` en input del usuario** — solo existe `_split_tagged_response()` para output del modelo.

---

## Cambios propuestos

### 1. Los 3 motores inline

| Motor | Sintaxis | Acción | Tag destino |
|-------|----------|--------|-------------|
| Hash commands | `#comando args#` | Ejecuta comando registrado | Según comando |
| Scene context | `[texto]` | Inyecta contexto de **escena ambiental** (lugar, clima, objetos, entorno). Acumula. | `[CONTEXT][SCENE]` via `add()` |
| Player action | `*texto*` | Marca como acción del jugador | `[PLAYER][ACT]` |
| Player thought | `:texto:` | Marca como pensamiento del jugador (sin los `:`) | `[PLAYER][THOUGHT]` |

Los 4 pueden convivir en el mismo mensaje y se procesan en orden: **Hash → Scene → Action/Thought**.

> ⚠️ `[texto]` es exclusivamente para contexto **ambiental** (entorno, clima, objetos, escenario). El estado interno del personaje (emociones, pensamientos, reacciones) va por `#char`, no por `[]`.

### 2. Pipeline completo (`chat.py`)

```
Input crudo:  *Entro sigilosamente* [CUECA OSCURA] hay alguien ahi
              #world hay estalactitas# :esto es peligroso: *Miro alrededor*

──── Paso 1: PROCESAR HASH (#comando#) ────
  → extrae #world hay estalactitas#
  → ContextInjector.add("world", "hay estalactitas")
  → segmentos temporales:
      [0] "*Entro sigilosamente* [cueva oscura] hay alguien ahi"
      [1] ":esto es peligroso: *Miro alrededor*"

──── Paso 2: PROCESAR SCENE ([texto]) ────
  → extrae [CUECA OSCURA] (multi-word → scene)
  → ContextInjector.add("scene", "CUECA OSCURA")
  → segmentos temporales:
      [0] "*Entro sigilosamente*"
      [1] "hay alguien ahi"
      [2] ":esto es peligroso: *Miro alrededor*"

──── Paso 3: SEGMENTAR POR ACCIÓN/THOUGHT ────
  → cada segmento con *acción* → [PLAYER][ACT] (preserva *)
  → cada segmento con :pensamiento: → [PLAYER][THOUGHT] (limpia :)
  → segmentos sin marcador → [PLAYER][SPEAK]
  → segmentos mixtos (*acción y texto*) → [PLAYER][ACT]
  → segmentos mixtos (:pensamiento y texto:) → [PLAYER][THOUGHT]

──── Paso 4: GENERAR MENSAJES ────
  system: [CONTEXT][WORLD] hay estalactitas
  user:   [PLAYER][ACT] *Entro sigilosamente*
  user:   [PLAYER][SPEAK] hay alguien ahi
  system: [CONTEXT][SCENE] CUECA OSCURA
  user:   [PLAYER][THOUGHT] esto es peligroso        ← sin los :
  user:   [PLAYER][ACT] *Miro alrededor*

──── Paso 5: INYECTAR AL PIPELINE ────
  Se agregan como N mensajes user separados (no concatenados)
  Emotional trigger corre sobre el texto ORIGINAL combinado
  Soul context se inyecta en CADA user message (no solo el último)
```

### 3. `InlineProcessor` — módulo unificado

Archivo nuevo: `engine/inline.py`

```python
HASH_PATTERN = re.compile(r'#(\w+)\s+(.*?)#', re.DOTALL)
SCENE_PATTERN = re.compile(r'\[([^\]]{2,}?)\]')    # multi-word → scene
THOUGHT_PATTERN = re.compile(r':([^:]+?):')         # :texto: → pensamiento (se limpian los :)
ACTION_PATTERN = re.compile(r'\*(.*?)\*')           # *texto* → acción

class InlineProcessor:
    def __init__(self):
        self._hash_commands: dict[str, Callable] = {}

    def register(self, name, handler, desc):
        self._hash_commands[name] = {"handler": handler, "desc": desc}

    def process(self, text: str, llm) -> list[dict]:
        """Retorna lista de mensajes [(role, tag, content), ...]"""
        segments = self._extract_hash_commands(text, llm)
        segments = self._extract_scene_contexts(segments, llm)
        messages = self._build_tagged_messages(segments)
        return messages

    def _extract_hash_commands(self, text, llm) -> list[str]:
        ...

    def _extract_scene_contexts(self, segments, llm) -> list[str]:
        ...

    def _tag_segment(self, segment: str) -> tuple[str, str]:
        """Retorna (tag, content) para un segmento.
        *acción* → [ACT] preserva *
        :pensamiento: → [THOUGHT] limpia :
        sin marcador → [SPEAK]"""
        has_action = bool(ACTION_PATTERN.search(segment))
        has_thought = bool(THOUGHT_PATTERN.search(segment))
        if has_action:
            return ("ACT", segment)
        if has_thought:
            content = THOUGHT_PATTERN.sub(r'\1', segment)
            return ("THOUGHT", content.strip())
        return ("SPEAK", segment)

    def _build_tagged_messages(self, segments) -> list[dict]:
        messages = []
        for seg in segments:
            tag, content = self._tag_segment(seg)
            messages.append({
                "role": "user",
                "speaker_tag": "PLAYER",  # se reemplaza por _user_tag luego
                "tag": tag,
                "content": content,
            })
        return messages
```

### 4. Cambios en `chat.py`

El flujo de `chat()` se modifica para:

1. **Antes** de `_extract_inline_context`:
   - Procesar `#comando#` y `[texto]` via `InlineProcessor`
   - Reemplazar el manejo hardcodeado de `#mem`

2. **Reemplazar** `_get_inference_messages()`:
   - Usar `self._user_tag` en vez de `[USER]` hardcodeado
   - Implementar multi-personaje: `[ROBERTO] texto` → `[ROBERTO][SPEAK]` (solo si el contenido entre `[]` es UPPERCASE y single-word)

3. **En el loop de inferencia**:
   - Cada segmento se agrega como `add_user_message(content, speaker_tag=_user_tag)`
   - El `speaker_tag` se persiste en SQLite
   - `emotional_trigger` corre sobre el texto combinado original, no por segmento
   - `soul_context` se inyecta en cada user message

### 5. Comandos `#` planificados

| Comando | Descripción | Tag destino | Implementación |
|---------|-------------|-------------|----------------|
| `#time <desc>` | Avanza o describe el tiempo | `[CONTEXT][TIME]` | `ContextInjector.add("time", desc)` |
| `#scene <desc>` | Reemplaza la escena completa | `[CONTEXT][SCENE]` | `ContextInjector.save_scene(desc)` |
| `#char <thought>` | Pensamiento interno del personaje | `[NAME][THOUGHT]` | System message efímero |
| `#world <desc>` | Lore/evento del mundo | `[CONTEXT][WORLD]` | `ContextInjector.add("world", desc)` |
| `#goal <desc>` | Objetivo activo del personaje | `[CONTEXT][GOALS]` | `ContextInjector.add("goals", desc)` |
| `#player <state>` | Estado del jugador | `[CONTEXT][PLAYER]` | `ContextInjector.add("player", state)` |
| `#thought <content>` | Pensamiento narrativo externo | `[CONTEXT][THOUGHTS]` | `ContextInjector.add("thoughts", content)` |
| `#mood <emotion>` | Fuerza estado emocional | `[STATE]` | Modifica `emotional_state` |
| `#recall <topic>` | Recuperación forzada de memoria | — | Búsqueda ChromaDB |
| `#emote <feeling>` | Ajusta valence/arousal | — | EmotionalState directo |

### 6. Correcciones de bugs inherentes

v15 incluye estas correcciones indispensables:

| Bug | Archivo | Fix |
|-----|---------|-----|
| `_user_tag` ignorado en chat | `chat.py:17-26` | `_get_inference_messages()` usa `self._user_tag` |
| `speaker_tag` no persiste | `chat.py:398` | Pasar `speaker_tag=_user_tag` a `add_user_message()` |
| Multi-personaje no implementado | `chat.py:17-26` | Detectar `[UPPERCASE] texto` → `[NAME][SPEAK]` |
| `_archive_to_chroma` usa PLAYER fijo | `memory.py:138` | Usar `_user_tag` desde metadata de la conversación |

---

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `engine/inline.py` | **NUEVO** — `InlineProcessor` con parsers y HashCommandRegistry |
| `engine/chat.py` | Reemplazar `_get_inference_messages()`, `_extract_inline_context()`, y sección `#mem` |
| `engine/base.py` | Inicializar `_inline_processor` |
| `engine/__init__.py` | Import inline |
| `engine/memory.py` | `_archive_to_chroma()` usa `_user_tag` en vez de PLAYER fijo |
| `orquestador/context_injector.py` | Sin cambios |

---

## Riesgos y mitigaciones

1. **`*` vs markdown**: si el usuario usa `*cursiva*` sin intención narrativa, se etiqueta como `[ACT]`. Mitigación: documentar que en roleplay `*` = acción narrativa, no énfasis.

2. **`:` vs uso normal de dos puntos**: `:texto:` podría confundirse con notación normal (ej: `una lista: item1, item2`). Mitigación: el detector requiere que el contenido entre `:` sea de 2+ caracteres y que los `:` estén balanceados. Un solo `:` no dispara el patrón.

3. **`[UNA PALABRA]` vs `[DOS O MAS]`**: la distinción solo existe para el multi-personaje no implementado (`[ROBERTO]` → personaje). `[texto]` SIEMPRE es contexto de escena ambiental (escenario, clima, objetos, entorno). El **estado interno del personaje** va por `#char`, no por `[]`. `[LUNA ESTA TRISTE]` es un error semántico — eso sería `#char estoy muy triste#`.

4. **Multi-segmento largo**: 3 comandos `#` + 2 `[scene]` + 2 `*acción*` = 7 segmentos. El LLM ve 7 user messages en secuencia. Contexto extra pero cronología perfecta.

5. **`#comando#` no registrado**: si el usuario escribe `#foo#` y `foo` no existe, NO se extrae (se deja como texto literal).

6. **Soul context**: `inject_soul_context` appendaba al último user message. Con multi-segmento, debe inyectar en CADA user message.

---

## Decisiones tomadas

| # | Pregunta | Decisión |
|---|----------|----------|
| 1 | Convención pensamiento jugador | `:texto:` (colon) — no choca con markdown |
| 2 | Desambiguación `[texto]` vs `[ROBERTO]` | `[UNA PALABRA]` = personaje, `[DOS O MAS]` = scene |
| 3 | Emotional trigger | Sobre el texto combinado original |
| 4 | `[texto]` acumula o reemplaza | `[texto]` = add (acumula), `#scene#` = save_scene (reemplaza) |
| 5 | `:texto:` incluye los `:` | NO — se limpian, queda solo el contenido |

## Próximos pasos

1. Implementar `engine/inline.py` con `InlineProcessor`
2. Modificar `chat.py`: reemplazar `_get_inference_messages()`, `_extract_inline_context()`, `#mem`
3. Corregir `_user_tag` no usado y `speaker_tag` no persistido
4. Implementar multi-personaje `[ROBERTO] texto` real
5. Tests: verificar segmentación, tags, acciones, pensamientos, escenas
6. Documentar la nueva sintaxis inline en README.md
