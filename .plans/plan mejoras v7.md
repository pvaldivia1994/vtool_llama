# Plan mejoras v7

## Objetivo

Resolver la contradicción entre v6 (KV cache core persistente) y `_inject_personality_into_system_prompt()` (muta el system prompt en cada turno, invalidando el core). De paso, simplificar el pipeline de tools y agregar métricas.

## Diagnóstico

### El problema fundamental: `_inject_personality_into_system_prompt()` invalida el core

Con v6, implementamos `reset_keep()` para mantener el core del system prompt en el KV cache entre turnos. **Pero** `_inject_personality_into_system_prompt()` muta `self._memory.system_prompt` en cada turno:

```python
def _inject_personality_into_system_prompt(self):
    enriched_prompt = self._character_manager.build_system_prompt(...)
    # Agrega TOOL_USAGE_POLICY si hay tools activas
    if get_active_internal_tools(last_user, self._config):
        enriched_prompt += "\n\n" + TOOL_USAGE_POLICY
    # MUTA el system prompt → el core del KV cache queda desactualizado
    self._memory.system_prompt = enriched_prompt
```

Cada vez que se agrega la política, el system prompt cambia → `create_chat_completion()` re-evalúa todo → el speedup de `reset_keep()` se pierde.

### Mapa de llamadas a `_inject_personality_into_system_prompt()`

| Lugar | Frecuencia | Problema |
|-------|-----------|----------|
| `load_character()` | 1 vez por carga | Necesario, establece prompt inicial |
| `chat()` | Cada turno | **Invalida core v6** |
| `stream_chat()` | Cada turno | **Invalida core v6** |
| `chat_with_thinking()` | Cada turno | **Invalida core v6** |
| `slash_commands.py` (x2) | Por comando | Innecesario, el prompt ya está |

**8+ llamadas por sesión, cada una muta el system prompt y obliga a re-evaluar.**

### La política de tools no debería estar en el system prompt fijo

`TOOL_USAGE_POLICY` es instrucción para el modelo sobre CUÁNDO usar tools. Pero:
- Si el modelo soporta tool calling nativo (como este modelo), las schemas vía OpenAI format ya definen cuándo y cómo llamar
- La política textual es redundante con las schemas
- Agregarla al system prompt cambia el core e invalida el KV cache

### Arquitectura actual de tools en el flujo de chat

```
chat("recordá esto")
  │
  ├─ get_active_internal_tools(prompt)
  │    → detecta trigger "recordá"
  │    → activa store_long_term_memory
  │
  ├─ _inject_personality_into_system_prompt()
  │    → como hay tools activas, agrega TOOL_USAGE_POLICY
  │    → MUTA system prompt → core invalidado
  │
  ├─ generate(tools=active_tools)
  │    └─ reset_keep() → core se limpia igual (porque cambió)
  │    └─ create_chat_completion() → re-evalúa TODO
  │
  ├─ ¿El modelo llamó la tool?
  │    ├─ Sí → handle_structured_calls() → guarda memoria
  │    └─ No → needs_tool_coercion() → OTRA inferencia forzada
  │
  └─ Fin
```

El core se invalida en el paso 2. `reset_keep()` no puede protegerlo porque cambió el contenido.

## Problemas detectados

### 1. `_inject_personality_into_system_prompt()` es un anti-patrón con v6

Modifica `self._memory.system_prompt` en cada turno. Con v6, el system prompt debería ser **estable** para que el KV cache core sea útil. Las instrucciones variables (tools, contexto dinámico) deberían ir como mensajes `system` adicionales, no mutando el core.

**Impacto**: el speedup de `reset_keep()` se pierde en cada turno donde hay tools activas (que es cuando más se necesita).

### 2. `TOOL_USAGE_POLICY` es redundante con el tool calling nativo

El modelo tiene un chat template con `format_function_declaration` y soporta OpenAI-style tool schemas. La política textual es instrucción adicional que:
- Ocupa ~200 tokens en el core
- Cambia en cada turno (porque se inyecta condicionalmente)
- Es redundante: las schemas ya definen `description` de cada tool

### 3. `_inject_personality_into_system_prompt()` se llama sin necesidad

En `slash_commands.py` línea 188 y 428, y en `chat_with_thinking()` línea 652. En estos casos el system prompt ya está establecido desde `load_character()`. Llamarlo de nuevo es ruido.

### 4. No hay métricas de tools

No se trackea:
- Cuántas tool calls estructuradas recibe el modelo vs cuántas ejecuta
- Cuántas alucinaciones (tools inválidas) se filtran
- Cuántos coercion retries se disparan
- Ratio de memoria guardada vs triggers detectados

### 5. El fallback textual en streaming tiene un doble parseo

En `stream_chat()`, los patrones de tool se capturan en `pending_tool_patterns` y luego se parsean de nuevo en `handle_text_calls()`. Hay parseo redundante del mismo JSON.

## Estrategia propuesta

### 1. Separar el system prompt estable del contexto variable

**Principio**: el system prompt del personaje (identidad, reglas, estilo) es **estable**. Las instrucciones variables (política de tools, contexto dinámico, inyecciones) son **mensajes system adicionales** que se agregan antes del último user, no mutaciones del core.

```python
# ANTES (invalida core):
self._memory.system_prompt = enriched_prompt  # cambia el core

# DESPUÉS (core estable):
# El system prompt NUNCA se modifica después de load_character()
# Las instrucciones variables van como mensajes system antes del último user:
messages.insert(-1, {"role": "system", "content": TOOL_USAGE_POLICY})
```

Esto implica:
- `_inject_personality_into_system_prompt()` solo se llama en `load_character()` (1 vez)
- En los turnos siguientes, el core NO cambia
- `TOOL_USAGE_POLICY` se inyecta como mensaje system antes del último user si hay tools activas (como ya hace `_inject_dynamic_state_into_messages`)

### 2. Mover `TOOL_USAGE_POLICY` a inyección dinámica

En vez de mutar el system prompt, agregar `TOOL_USAGE_POLICY` como mensaje system en `_inject_dynamic_state_into_messages()` o en un nuevo helper.

Esto:
- Mantiene el core estable
- La política solo aparece cuando hay tools activas
- No invalida el KV cache

### 3. Eliminar llamadas redundantes a `_inject_personality_into_system_prompt()`

Las llamadas en `chat()`, `stream_chat()`, `chat_with_thinking()` y `slash_commands.py` que NO son la primera carga deben eliminarse.

La única llamada necesaria es en `load_character()` (ya existe, línea 155).

### 4. Agregar métricas de tools

En `ToolExecutionManager`:

```python
@property
def stats(self) -> dict:
    return {
        "structured_calls": self._structured_count,
        "text_calls": self._text_count,
        "memory_saved": self._memory_saved_count,
        "hallucinations": self._hallucination_count,
        "coercion_retries": self._coercion_count,
    }
```

Y exponerlo via `VToolLlama.get_tool_stats()`.

### 5. Simplificar el pipeline de herramientas

Unificar `handle_structured_calls()` y `handle_text_calls()` bajo un mismo método que acepte ambos formatos, evitando el doble dispatch en `chat()` y `stream_chat()`.

## Cambios propuestos

1. **`engine/character.py`** — `_inject_personality_into_system_prompt()`:
   - No inyecta `TOOL_USAGE_POLICY` (pasa a ser dinámico): [Listo]
   - El system prompt ahora es ESTABLE (no cambia entre turnos): [Listo]

2. **`engine/chat.py`** — nuevas funciones + eliminación de redundantes:
   - Nueva `_inject_tool_policy_if_needed(messages, prompt)`: [Listo]
   - `chat()`: reemplazado `_inject_personality` por `_inject_tool_policy_if_needed`: [Listo]
   - `stream_chat()`: ídem: [Listo]
   - `chat_with_thinking()`: ídem: [Listo]
   - `stream_chat_with_thinking()`: ídem: [Listo]

3. **`engine/slash_commands.py`** — las llamadas existentes son legítimas:
   - Tras modificar el personaje (mood) o limpiar contexto, el prompt estable se reasigna. Con v7 ya no inyecta TOOL_USAGE_POLICY, así que no contamina el core: [Listo]

4. **`tools/manager.py`** — métricas agregadas a `ToolExecutionManager`:
   - Contadores: structured_calls, text_calls, memory_saved, hallucinations, coercion_retries: [Listo]
   - Property `stats` que los expone: [Listo]

5. **`engine/base.py`** — nuevo método `get_tool_stats()`:
   - Delega a `ToolExecutionManager.stats`: [Listo]

6. **`engine/memory.py`** — las llamadas existentes son legítimas:
   - Tras trim (restaurar system prompt perdido) o load_episode, se reasigna el prompt estable. No contamina el core porque ya no inyecta TOOL_USAGE_POLICY: [Listo]

7. **Unificar pipeline `handle_all_calls()`**: [Pendiente — para v8]

8. **Tests actualizados**: [Pendiente — para v8]

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `engine/character.py` | Desacoplar `_inject_personality_into_system_prompt()` del core |
| `engine/chat.py` | Inyectar política como mensaje dinámico, no mutar core |
| `engine/memory.py` | Igual que chat() |
| `engine/slash_commands.py` | Eliminar llamadas redundantes |
| `engine/base.py` | Nuevo `get_tool_stats()` |
| `tools/manager.py` | Métricas + unificación pipeline |
| `tests/test_tools.py` | Tests de métricas y core estable |

## Riesgos

1. **Mover la política de tools a mensaje dinámico puede cambiar el comportamiento del modelo**: el modelo puede responder diferente si la política está en el system prompt vs como mensaje system antes del user.
   - Mitigación: probar A/B con y sin el cambio, verificar que las tool calls siguen funcionando.

2. **Eliminar llamadas a `_inject_personality_into_system_prompt()` puede romper slashes**: algunos comandos dependen de que el system prompt esté "fresco".
   - Mitigación: verificar que cada slash command funciona sin la llamada extra.

3. **Las métricas agregan overhead mínimo**: son contadores en memoria, sin IO.

## Resultado esperado

- El core del system prompt se mantiene **estable** entre turnos
- `reset_keep()` protege el core y el speedup se mantiene incluso con tools activas
- `TOOL_USAGE_POLICY` aparece solo cuando es necesaria, sin contaminar el core
- 8+ llamadas a `_inject_personality_into_system_prompt()` → 1 (solo en load)
- Métricas de tools visibles via API pública
- Pipeline de herramientas simplificado
- Tests verifican que el core no se muta
