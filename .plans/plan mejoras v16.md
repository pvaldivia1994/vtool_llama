# Plan mejoras v16 — Desambiguación del sistema de tools vs tags semánticos `[]`

## Objetivo

Eliminar la ambigüedad entre el formato `[SECTION HEADER]` usado por `TOOL_USAGE_POLICY` y el sistema de tags semánticos `[]` (scene, state, define) del v15.

## Diagnóstico

### El conflicto

`TOOL_USAGE_POLICY` comienza con:

```python
TOOL_USAGE_POLICY = (
    "[TOOL USAGE POLICY]\n\n"
    "Call tools only when the current user message clearly requires it.\n"
    ...
)
```

El tag semántico `SCENE_PATTERN = r'\[(\w+(?:\s+\w+)+[^\]]*?)\]'` **matchea perfectamente** `[TOOL USAGE POLICY]`.

### No explota hoy (pero es frágil)

| Capa | Contiene `[]`? | Pasa por `_extract_inline_context`? |
|------|---------------|-----------------------------------|
| `TOOL_USAGE_POLICY` (system msg) | `[TOOL USAGE POLICY]` | **No** — se inyecta después |
| `[CORE RULES]`, `[HARD RULES]` (compiler) | `[CORE RULES]` | **No** — son parte del system prompt compilado |
| Input del usuario `[TOOL USAGE POLICY]` | Sí | **Sí** — se pierde como scene context |
| Tags `[SPEAK]`, `[ACT]` (1 palabra) | Sí | **No** — 1 palabra, SCENE_PATTERN exige 2+ |

**No explota** porque `_extract_inline_context` corre antes que `_inject_tool_policy_if_needed`, y el `prompt` del usuario raramente contiene `[TOOL USAGE POLICY]`.

### Problemas reales

1. **Fragilidad de orden**: si alguien reordena el pipeline, `[TOOL USAGE POLICY]` se pierde como scene.
2. **Ambigüedad semántica**: el modelo ve `[TOOL USAGE POLICY]` (tool), `[STATE]` (psych), `[SCENE]` (environment), `[DEFINE]` (personality) — todos con `[...]` pero significados distintos.
3. **Edge case**: si un usuario escribe `[TOOL USAGE POLICY]` en su mensaje, se elimina silenciosamente.
4. **`[CORE RULES]`** en el compilador tiene el mismo patrón — otro `[SECTION HEADER]` que SCENE_PATTERN matchearía si alguna vez pasara por `_extract_inline_context`.

## Cambios propuestos

### 1. Renombrar `TOOL_USAGE_POLICY` — de `[SECTION HEADER]` a `>>> marker`

```python
TOOL_USAGE_POLICY = (
    ">>> TOOL USAGE POLICY\n\n"
    "Call tools only when the current user message clearly requires it.\n"
    ...
)
```

El `>>>` no choca con ningún tag `[]`, no es capturado por `SCENE_PATTERN`, y visualmente se distingue como una directiva de sistema (no un tag semántico).

### 2. Renombrar `[CORE RULES]` y `[HARD RULES]` en el compilador

En `compiler/compiler.py`, los bloques de system prompt que usan `[SECTION HEADER]` para demarcar secciones internas:

```python
# Antes
CORE_RULES_BLOCK = "[CORE RULES]\n..."
HARD_RULES_BLOCK = "[HARD RULES]\n..."

# Después
CORE_RULES_BLOCK = "--- CORE RULES ---\n..."
HARD_RULES_BLOCK = "--- HARD RULES ---\n..."
```

Usar `---` como demarcador de secciones internas del system prompt, dejando `[]` exclusivamente para tags semánticos del orquestador.

### 3. `SCENE_PATTERN` proteger contra `>>>` y `---`

No hace falta — `SCENE_PATTERN` busca `\[...\]`, no matchea `>>>` ni `---`.

### 4. Agregar bloque de exclusión en `SCENE_PATTERN`

Opcional: hacer que `SCENE_PATTERN` ignore contenido que coincida con patrones de secciones conocidas:

```python
# Excluir [TOOL USAGE POLICY], [CORE RULES], [HARD RULES] conocidos
SCENE_PATTERN = re.compile(r'\[(?!(?:TOOL USAGE|CORE|HARD)\b)(\w+(?:\s+\w+)+[^\]]*?)\]')
```

Esto es una red de seguridad, no la solución principal.

### 5. Documentar el orden del pipeline

Agregar un comentario explícito en `chat.py`:

```python
# ORDEN DEL PIPELINE (v16):
# 1. _extract_inline_context — SOLO toca prompt del usuario
# 2. _handle_slash_command — comandos /
# 3. inline_processor.process — #, [], :, * en prompt
# 4. _memory.add_user_message — persiste
# ...
# N. _inject_tool_policy_if_needed — system msg, NO toca prompt
#
# IMPORTANTE: No mover _inject_tool_policy antes de _extract_inline_context
# sin actualizar SCENE_PATTERN, o [TOOL USAGE POLICY] será capturado como scene.
```

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `tools/definitions.py` | Renombrar `[TOOL USAGE POLICY]` → `>>> TOOL USAGE POLICY` |
| `compiler/compiler.py` | Renombrar `[CORE RULES]` → `--- CORE RULES ---`, `[HARD RULES]` → `--- HARD RULES ---` |
| `engine/inline.py` | Agregar negative lookahead en `SCENE_PATTERN` como red de seguridad |
| `engine/chat.py` | Documentar orden del pipeline |
| `engine/chat.py` | Actualizar `_extract_inline_context` inline regex igual que `inline.py` |

## Riesgos

1. **Modelo entrenado con `[SECTION HEADER]`**: algunos modelos pueden estar acostumbrados a ver `[TOOL USAGE POLICY]` y comportarse distinto con `>>>`. Mitigación: el contenido semántico es el mismo, solo cambia el demarcador. `>>>` es igual de visible.
2. **Regresiones en compiler**: `[CORE RULES]` y `[HARD RULES]` son parte del system prompt compilado. Si algún modelo usa esos tags para orientarse, cambiar a `---` podría afectar comportamiento. Mitigación: son secciones internas del prompt, no instrucciones para el modelo. El contenido es lo que importa.
3. **SCENE_PATTERN con negative lookahead**: si se agregan nuevas secciones en el futuro, el lookahead hay que mantenerlo. Mitigación: la solución principal es renombrar las secciones (puntos 1 y 2), el lookahead es solo red de seguridad.

## Resultado esperado

```
Antes (v15):
  system: [TOOL USAGE POLICY]\nCall tools...
  system: [STATE] Currently feeling anxious
  system: [CONTEXT][SCENE] cueva oscura

Después (v16):
  system: >>> TOOL USAGE POLICY\nCall tools...
  system: [STATE] Currently feeling anxious
  system: [CONTEXT][SCENE] cueva oscura

Los `[]` quedan EXCLUSIVAMENTE para tags semánticos del orquestador.
Los `>>>` y `---` son demarcadores de sistema/internos.
```
