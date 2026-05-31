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
| `INTERNAL_TOOLS` | `list[dict]` | Definiciones de herramientas internas en formato OpenAI. Actualmente declara `store_long_term_memory` |
| `TOOL_USAGE_POLICY` | `str` | Bloque de prompt que instruye al modelo sobre cuándo y cómo usar las herramientas internas |
| `SCENE_SYSTEM_COMMAND` | `str` | System command para forzar descripción de escena inmersiva |

### `parser.py` — Parseo de Tool Calls en Texto Plano

Parsea llamadas a herramientas incrustadas en el texto de respuesta del modelo.

Formato textual oficial:

```text
<tool_call>
{"name":"store_long_term_memory","arguments":{"content":"...","category":"..."}}
</tool_call>
```

| Símbolo | Rol |
|---------|-----|
| `TEXT_TOOL_RE` | Expresión regular compilada para detectar bloques `<tool_call>{json}</tool_call>` |
| `find_tool_pattern_start(text)` | Encuentra el inicio del primer patrón de tool call en el texto |
| `parse_text_tool_calls(text)` | Extrae tool calls oficiales y retorna `[(name, args), ...]` |
| `strip_text_tool_calls(text)` | Elimina bloques `<tool_call>...</tool_call>` del texto visible |
| `execute_text_tool(name, args, ...)` | Ejecuta una herramienta interna por nombre. Actualmente solo `store_long_term_memory` |
| `is_internal_tool(name)` | Verifica si el nombre corresponde a una herramienta interna |

### `manager.py` — ToolExecutionManager

Orquestador que maneja tool calls estructuradas (OpenAI format) y en texto plano.

| Símbolo | Rol |
|---------|-----|
| `ToolExecutionManager.__init__(add_memory_fn, log_info_fn, log_debug_fn)` | Recibe callbacks del CharacterManager |
| `get_active_internal_tools(prompt, config)` | Activa tools internas por trigger o por config |
| `handle_structured_calls(tool_calls, scene_prompt, user_tools)` | Procesa tool calls estructuradas. Retorna `{"internal_found": bool, "external_calls": list, "memory_saved": bool}` |
| `handle_text_calls(text, scene_prompt, user_tools)` | Procesa tool calls en texto plano. Retorna `{"internal_found": bool, "cleaned_text": str, "external_calls": list, "memory_saved": bool}` |
| `needs_tool_coercion(prompt, response, has_tools, is_stream)` | Determina si el modelo debió usar una tool y no lo hizo |
| `build_coercion_prompt(prompt)` | Genera prompt de re-intento forzando el uso de la tool |

**Resolución**: Las herramientas internas se ejecutan directamente. Las herramientas externas (del usuario) se devuelven para que el engine las maneje.

Las tools internas ya no tienen que exponerse siempre al modelo. Por defecto `store_long_term_memory` se activa cuando el prompt del usuario contiene un trigger de memoria (`recuerda`, `no olvides`, `remember`, etc.). Puede forzarse con `always_enable_internal_tools=true`.

Config relacionada:

| Clave | Default | Rol |
|-------|---------|-----|
| `always_enable_internal_tools` | `false` | Pasa siempre las tools internas al modelo |
| `enable_text_tool_fallback` | `true` | Permite parsear tool calls en texto plano |
| `enable_stream_tool_execution` | `false` | Permite ejecutar tools detectadas durante streaming |

### `stream_processor.py` — StreamPostProcessor

Intercepta tool calls en streaming para que el usuario NO vea `<tool_call>...</tool_call>` en la salida.

| Símbolo | Rol |
|---------|-----|
| `StreamPostProcessor.__init__(on_tool_executed, log_fn)` | Recibe callback cuando se detecta una tool |
| `feed(delta)` | Procesa un delta del stream. Acumula texto en buffer. Cuando detecta un patrón de tool call, lo oculta, lo guarda como pendiente y solo lo ejecuta si hay callback activo. Yield eventos `{"type": "text" | "tool_executed"}` |
| `pending_tool_patterns` | Lista de bloques `<tool_call>...</tool_call>` detectados para validacion/ejecucion diferida |
| `flush()` | Vacía el buffer restante |

**Detección**: Usa `TEXT_TOOL_RE` para encontrar bloques `<tool_call>...</tool_call>` en el flujo de tokens. Por defecto el engine no ejecuta tools durante streaming (`enable_stream_tool_execution=false`); el processor oculta el markup, conserva candidatos y el engine los valida al final.

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
├── Tool call textual detectada → ocultar y guardar en `pending_tool_patterns`
├── Tool call estructurada por chunks → reconstruir al final
└── Al final del stream → validar/ejecutar tool calls detectadas
```

## Dependencias

| Archivo | Importa desde |
|---------|---------------|
| `definitions.py` | Solo constantes, sin imports internos |
| `parser.py` | `json`, `re`, `definitions` |
| `manager.py` | `definitions.*`, `parser.*` |
| `stream_processor.py` | `parser.*` |
