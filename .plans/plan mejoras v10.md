# Plan mejoras v10

## Objetivo

Resolver 3 problemas concretos detectados en el análisis del flujo completo:

1. El estado dinámico inyecta scores técnicos (`Trust: 0.50`, `Apertura=0.4`) que el modelo no entiende
2. Usa un header (`[ESTADO DINÁMICO DEL PERSONAJE]`) que no existe en el sistema de tags del orquestador
3. Mensajes del usuario y contexto no tienen tags semánticos visibles

Sin sobreingeniería — solo corregir lo que está mal y aprovechar lo que ya existe.

## Análisis del flujo actual

### Lo que ya funciona bien

```
compile_dynamic_prompt()  → runtime, en _inject_dynamic_state_into_messages()
  ├─ _resolve_relationship()  → "[RELATIONSHIP] Trust: 0.50 ..."   ← MAL: scores
  ├─ _resolve_state()         → "[EMOTIONAL STATE] emotion: neutral" ← OK, pero header incorrecto
  ├─ _resolve_psychology()    → scores de personalidad             ← MAL: técnica
  ├─ _resolve_persona()       → expresión, verbosidad              ← MAL: contradice DNA
  ├─ _resolve_active_mods()   → solo si hay mods activos           ← OK
  └─ _resolve_memory()        → solo si hay memorias relevantes    ← OK
```

**Problema 1**: `_resolve_psychology()` y `_resolve_persona()` usan datos del `PsychologyManager` (sistema de psicología simulada) que **contradicen** al DNA. Ejemplo concreto: `speech.json` dice `verbosity: Low`, pero el PsychologyManager tiene un default `verbosidad: Alta`.

**Problema 2**: `_resolve_relationship()` muestra `Trust: 0.50`, `Familiarity: 0.20`. El modelo no sabe interpretar estos números.

**Problema 3**: `_resolve_state()` usa header `[EMOTIONAL STATE]` en vez del tag que ya existe en el orquestador: `[CONTEXT][CHARACTER]`.

```
orquestador/context_injector.py tiene:
  CONTEXT_TYPES["character"] = "[CONTEXT][CHARACTER]"
  CONTEXT_DEFINITIONS["character"] = "[CONTEXT][CHARACTER] Current emotional, mental, and physical state..."

base_prompt.yaml incluye en [SECTION REFERENCE]:
  [CONTEXT][CHARACTER] Current emotional, mental, and physical state of the character.
  [CONTEXT][PLAYER] Current action or behavior of the player...
```

### Lo que no agrega valor (descartado para v10)

| Idea del plan anterior | Por qué la descarto |
|-----------------------|---------------------|
| `character_v4.jinja` | Los tags se pueden anteponer desde Python sin modificar el template. `character_v3.jinja` funciona bien. |
| `_tag_messages()` | Sobrediseño. Solo necesito cambiar el header en `compile_dynamic_prompt()` y anteponer `[PLAYER]` en la construcción de mensajes. |
| `llm.get_character_report()` | Baja prioridad. Ya tenemos `get_token_usage()` y `get_prompt_layer_usage()`. |
| Test de integridad de personaje | Primero arreglar los problemas reales. El test se hace después. |

## Cambios propuestos (solo lo que suma)

### 1. Compactar `compile_dynamic_prompt()` — solo 2 capas útiles

```python
def compile_dynamic_prompt(self) -> str:
    if not self.manager.is_loaded:
        return ""
    parts = []

    # Solo emoción actual (con tag del orquestador)
    emotion = self.manager.runtime_state.current_emotion
    if emotion and emotion != "neutral":
        parts.append(f"[CONTEXT][CHARACTER] Currently feeling {emotion}.")

    # Relación solo si hay cambios relevantes
    rel = self.manager.relationship_state
    if rel.dynamics and len(rel.dynamics) > 0:
        dynamics = rel.dynamics[0][:200]
        parts.append(f"[CONTEXT][RELATIONSHIP] {dynamics}")

    # NO incluir:
    # - _resolve_psychology() → scores Big Five, el modelo no los entiende
    # - _resolve_persona()    → contradice al DNA
    # - _resolve_relationship() → Trust: 0.50, Familiarity: 0.20
    # - _resolve_memory()     → ya se inyecta via ContextBuilder si está configurado

    return "\n".join(parts)
```

**Header cambiado**: de `[ESTADO DINÁMICO DEL PERSONAJE]` a usar los tags `[CONTEXT][CHARACTER]` y `[CONTEXT][RELATIONSHIP]` que **ya están definidos** en el orquestador.

**[Pendiente]**

### 2. Anteponer `[PLAYER]` a los mensajes del usuario

En `chat.py`, después de preparar los mensajes y antes de pasarlos a `generate()`:

```python
# En el loop de chat(), antes de generate():
for msg in messages:
    if msg.get("role") == "user":
        msg["content"] = f"[PLAYER] {msg['content']}"
```

El tag `[PLAYER]` ya existe en el orquestador (`CONTEXT_TYPES["player"] = "[CONTEXT][PLAYER]"`), y su definición ya está en el `base_prompt.yaml`. El modelo ya sabe qué significa.

**[Pendiente]**

### 3. Config `inject_dynamic_state: false` (default)

```python
# types/core.py
inject_dynamic_state: bool = False
```

Cuando es `false`, `_inject_dynamic_state_into_messages()` no inyecta nada. El modelo funciona solo con el `base_prompt.yaml`, que ya contiene identidad, reglas, estilo, y la definición de los tags.

Cuando es `true`, inyecta la versión compacta del punto 1.

**[Pendiente]**

### 4. Corregir `_resolve_persona()` para que lea del DNA

Actualmente `_resolve_persona()` usa valores del `PsychologyManager` que no coinciden con el DNA. La corrección: si `inject_dynamic_state` está desactivado, `_resolve_persona()` y `_resolve_psychology()` retornan `""` directamente. Si está activado, usan los valores del DNA como fallback.

```python
def _resolve_persona(self: CharacterCompiler) -> str:
    if not getattr(self.manager, '_psychology_manager', None):
        return ""
    if not self.manager._config.inject_dynamic_state:
        return ""
    # Usar DNA en vez de defaults del psychology manager
    ...
```

**[Pendiente]**

## Archivos afectados

| Archivo | Cambio | Líneas aproximadas |
|---------|--------|-------------------|
| `compiler/compiler.py` | Compactar `compile_dynamic_prompt()` a solo emoción + relación | ~20 líneas |
| `compiler/dna_layers.py` | `_resolve_persona()` y `_resolve_psychology()` condicionales por config | ~10 líneas |
| `engine/chat.py` | Anteponer `[PLAYER]` a mensajes user + estado dinámico condicional | ~10 líneas |
| `types/core.py` | Nueva config: `inject_dynamic_state: bool = False` | 1 línea |

## Orden de implementación

```
1. types/core.py        → agregar inject_dynamic_state: bool = False
2. compiler/compiler.py  → compactar compile_dynamic_prompt()
3. compiler/dna_layers.py → condicionar _resolve_persona() y _resolve_psychology()
4. engine/chat.py        → [PLAYER] tag + condicional inject_dynamic_state
```

## Resultado esperado

```
Antes (v9):
  <|turn>system
  [SECTION REFERENCE]
  [CONTEXT][CHARACTER] Current emotional, mental, and physical state...
  <|turn>system
  [ESTADO DINÁMICO DEL PERSONAJE]     ← tag inventado
  Trust: 0.50, Apertura=0.4...         ← scores que el modelo no entiende
  Verbosidad: Alta                      ← contradice speech.json (Low)
  <|turn>user
  Hola                                  ← sin tag

Después (v10, inject_dynamic_state: false — default):
  <|turn>system
  [SECTION REFERENCE]
  [CONTEXT][CHARACTER] Current emotional, mental, and physical state...
  <|turn>user
  [PLAYER] Hola                         ← tag consistente
  → El modelo usa SOLO el base_prompt, no hay estado dinámico redundante

Después (v10, inject_dynamic_state: true):
  <|turn>system
  [SECTION REFERENCE]
  [CONTEXT][CHARACTER] Current emotional, mental, and physical state...
  <|turn>system
  [CONTEXT][CHARACTER] Currently feeling nervous.  ← tag consistente, texto narrativo
  <|turn>user
  [PLAYER] Hola
  → Sin scores, sin contradicciones, tags que el modelo ya conoce
```
