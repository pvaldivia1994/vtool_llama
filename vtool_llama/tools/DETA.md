# Tools — Arquitectura Detallada

## Visión General

Sistema completo de function calling: define herramientas internas, parsea tool calls (tanto en formato OpenAI estructurado como en texto plano), las ejecuta, y procesa streaming con intercepción de herramientas en vuelo.

```
tools/
├── __init__.py            # Barrel: exporta ~14 símbolos
├── definitions.py         # INTERNAL_TOOLS, TOOL_USAGE_POLICY, SCENE_SYSTEM_COMMAND
├── parser.py              # Parseo de tool calls en texto plano
├── manager.py             # ToolExecutionManager: orquestación de ejecución
└── stream_processor.py    # StreamPostProcessor: intercepción en streaming
```

## Archivos del Subpackage

### `__init__.py`
Barrel. Exporta todas las funciones y clases del sistema de tools.

### `definitions.py` — Definiciones

Constantes del sistema de tools.

| Símbolo | Tipo | Descripción |
|---------|------|-------------|
| `INTERNAL_TOOLS` | `list[dict]` | Definiciones de herramientas internas en formato OpenAI: `store_long_term_memory` (guarda memoria), `remember_memory` (alias), `get_scene_state` (estado de escena), `describe_scene` (alias) |
| `TOOL_USAGE_POLICY` | `str` | Bloque de prompt que instruye al modelo sobre cuándo y cómo usar las herramientas internas |
| `SCENE_SYSTEM_COMMAND` | `str` | System command para forzar descripción de escena inmersiva |

### `parser.py` — Parseo de Tool Calls en Texto Plano

Parsea llamadas a herramientas incrustadas en el texto de respuesta del modelo (formato `{{tool_name(args)}}`).

| Símbolo | Rol |
|---------|-----|
| `TEXT_TOOL_RE` | Expresión regular compilada para detectar patrones `{{tool_name(args)}}` |
| `find_tool_pattern_start(text)` | Encuentra el inicio del primer patrón de tool call en el texto |
| `parse_text_tool_calls(text)` | Extrae todas las tool calls del texto, retorna `[(name, args, full_match, start, end), ...]` |
| `strip_text_tool_calls(text)` | Elimina todos los patrones `{{...}}` del texto |
| `execute_text_tool(name, args, ...)` | Ejecuta una herramienta por nombre: `store_long_term_memory`/`remember_memory` guarda memoria, `get_scene_state`/`describe_scene` retorna prompt de escena |
| `is_internal_tool(name)` | Verifica si el nombre corresponde a una herramienta interna |

**Formato de tool calls en texto**: `{{store_long_term_memory(content="...")}}` o `{{get_scene_state()}}`.

### `manager.py` — ToolExecutionManager

Orquestador que maneja tool calls estructuradas (OpenAI format) y en texto plano.

| Símbolo | Rol |
|---------|-----|
| `ToolExecutionManager.__init__(add_memory_fn, log_info_fn, log_debug_fn)` | Recibe callbacks del CharacterManager |
| `handle_structured_calls(tool_calls, scene_prompt, user_tools)` | Procesa tool calls estructuradas. Retorna `{"internal_found": bool, "external_calls": list, "memory_saved": bool}` |
| `handle_text_calls(text, scene_prompt, user_tools)` | Procesa tool calls en texto plano. Retorna `{"internal_found": bool, "cleaned_text": str, "external_calls": list, "memory_saved": bool}` |
| `needs_tool_coercion(prompt, response, has_tools, is_stream)` | Determina si el modelo debió usar una tool y no lo hizo |
| `build_coercion_prompt(prompt)` | Genera prompt de re-intento forzando el uso de la tool |

**Resolución**: Las herramientas internas se ejecutan directamente. Las herramientas externas (del usuario) se devuelven para que el engine las maneje.

### `stream_processor.py` — StreamPostProcessor

Intercepta tool calls en streaming para que el usuario NO vea `{{...}}` ni `|tool_call|...|` en la salida.

| Símbolo | Rol |
|---------|-----|
| `StreamPostProcessor.__init__(on_tool_executed, log_fn)` | Recibe callback cuando se detecta una tool |
| `feed(delta)` | Procesa un delta del stream. Acumula texto en buffer. Cuando detecta un patrón de tool call, ejecuta la herramienta vía callback y no yield el texto de la tool. Yield eventos `{"type": "text" | "tool_executed"}` |
| `flush()` | Vacía el buffer restante |

**Detección**: Usa `TEXT_TOOL_RE` para encontrar patrones `{{...}}` en el flujo de tokens. Cuando encuentra uno completo, ejecuta la herramienta y continúa.

## Flujo de Ejecución

### Chat sincrónico (`chat()`)
```
generate() → structured tool_calls?
├── Sí → ToolExecutionManager.handle_structured_calls()
│   ├── Interna → ejecuta, continúa loop
│   └── Externa → retorna al usuario
└── No → parse_text_tool_calls() en response_text
    ├── Interna → ejecuta, continúa loop
    └── Externa → retorna al usuario
```

### Chat streaming (`stream_chat()`)
```
generate(stream=True) → StreamPostProcessor.feed(delta)
├── Texto normal → yield al usuario
├── Tool call detectada → execute via callback
│   ├── store_long_term_memory → guarda, yield confirmación
│   └── get_scene_state → marca scene_requested, continúa loop
└── Al final del stream → handle_structured_calls() si hay tool_calls residuales
```

## Dependencias

| Archivo | Importa desde |
|---------|---------------|
| `definitions.py` | Solo constantes, sin imports internos |
| `parser.py` | `re`, sin imports internos |
| `manager.py` | `definitions.*`, `parser.*` |
| `stream_processor.py` | `parser.*` |
