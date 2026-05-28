# Engine — Arquitectura Detallada

## Visión General

Núcleo del sistema. `VToolLlama` es la clase principal que expone la API pública. Orquesta todos los subsistemas: modelo, personajes, tools, alma, psicología, memoria, configuración y logging.

```
engine/
├── __init__.py            # Barrel: importa submódulos, exporta VToolLlama
├── base.py                # VToolLlama class + __init__ + modelo/config/props/logging
├── chat.py                # chat(), stream_chat(), chat_with_thinking(), stream_chat_with_thinking()
├── character.py           # load_character, create, soul, personality, warmup cache
├── memory.py              # clear/get/export/import memory, trim, episodios
├── slash_commands.py      # VToolLlama slash command handlers
├── slash_registry.py      # SlashCommandRegistry class
├── internal.py            # Stats recording, token extraction, validación
├── chat_memory.py         # ChatMemory: historial de conversación
├── config_manager.py      # ConfigManager: carga/validación de config.json
├── logger_manager.py      # LoggerManager: logging a archivo y debug en consola
├── stats_manager.py       # StatsManager: estadísticas de rendimiento
└── tokenizer_utils.py     # Utilidades de tokenización
```

## Archivos del Subpackage

### `__init__.py`
Barrel. Importa submódulos para registrar métodos en `VToolLlama`. Exporta `VToolLlama`.

### `base.py` — VToolLlama Core

Define `VToolLlama`, la clase principal. Constructor inicializa todos los gestores y orquesta la carga inicial.

| Método | Rol |
|--------|-----|
| `__init__(config_path, auto_load)` | Inicializa ConfigManager → LoggerManager → ChatMemory → StatsManager → ModelManager → CharacterManager → ToolExecutionManager → SoulGenerator → SlashCommandRegistry. Carga modelo si `auto_load=True` |
| `load_model(path)` / `unload_model()` / `switch_model(path)` / `reload_model()` | Delega en `ModelManager` |
| `get_model_info()` / `list_available_models()` / `supports_tools()` | Consultas de capacidad del modelo |
| `get_config()` / `reload_config()` | Configuración |
| `enable_debug()` / `disable_debug()` | Debug toggle |
| `state_manager` (property) | Acceso a `CharacterManager` |
| `slash_commands` (property) | Acceso a `SlashCommandRegistry` |
| `__enter__` / `__exit__` | Context manager: auto-guarda episodio al cerrar |
| `_log_debug/info/warning/error` | Logging helpers |

### `chat.py` — Chat y Streaming

| Método | Rol |
|--------|-----|
| `chat(prompt, ...)` | Chat sincrónico con loop de Auto-Tools (hasta 3 iteraciones): inyecta contexto Soul + ChatMemory, genera, maneja tool calls, coercion retry, drift detection |
| `stream_chat(prompt, ...)` | Streaming con `StreamPostProcessor` para intercepción de tools en vuelo |
| `chat_with_thinking(prompt, ...)` | Soporte `reasoning_content` nativo + parseo de etiquetas `<think>` |
| `stream_chat_with_thinking(prompt, ...)` | Streaming con detección incremental de `<think>`/`</think>` |
| `add_tool_message(content, id)` | Agrega respuesta de herramienta al historial |
| `_inject_soul_context_into_messages(messages, prompt)` | Inyecta recuerdos del Soul System |
| `_inject_chat_memory_into_messages(messages, prompt)` | Inyecta turnos pasados relevantes desde ChromaDB |
| `_apply_emotional_trigger(prompt)` | Trigger emocional Psychology Engine |
| `_feed_response_to_drift_detector(response)` | Feedback loop de deriva |
| `_on_stream_tool_detected(name, args)` | Callback del StreamPostProcessor |
| `_reconstruct_tool_calls(chunks)` | Reconstruye tool calls desde chunks de stream |

**Loop de Auto-Tools (chat):**
```
1. generate() → tool_calls?
2. structured tool_calls → interna → loop / externa → return
3. texto plano tool_calls → interna → loop / externa → return
4. coercion retry si aplica
5. drift detection → add_assistant_message → return
```

### `character.py` — Operaciones de Personaje

| Método | Rol |
|--------|-----|
| `load_character(name)` | Carga personaje + mergea config + warmup KV Cache dual (Base + Full) |
| `create_character(...)` | Crea estructura de directorios |
| `generate_character_with_ai(name, prompt)` | Usa LLM para generar personaje completo |
| `generate_character_soul(...)` | Genera alma (delega en SoulGenerator) |
| `has_character_soul(name)` / `get_character_soul(name)` | Consultas de alma |
| `add_memory(...)` | Agrega memoria persistente |
| `get_state_info()` | Estado actual del agente |
| `rebuild_personality_state()` | Reconstruye personalidad desde historial |
| `_warmup_character_cache(prompt)` | Arquitectura dual de KV Cache: Base (DNA) + Base Soul (DNA+Soul) + Full (DNA+Memoria) |
| `_inject_personality_into_system_prompt()` | Inyecta tool policy + personalidad en system prompt |
| `_check_and_rebuild_if_needed()` | Rebuild automático antes del chat si hay memorias nuevas |

### `memory.py` — Memoria y Episodios

| Método | Rol |
|--------|-----|
| `clear_memory()` / `reset_chat()` | Limpia historial |
| `get_memory()` / `export_memory_json()` / `import_memory_json()` | Acceso y serialización |
| `set_system_prompt(prompt)` | Cambia system prompt |
| `trim_memory()` | Recorte manual de contexto |
| `_auto_trim_if_needed()` | Auto-trim configurable |
| `save_episode()` / `list_episodes()` / `load_episode()` / `delete_episode()` | Gestión de episodios |

### `slash_commands.py` — Handlers de Slash Commands

Métodos `_cmd_*` asignados a `VToolLlama`: `mem`, `rebuild`, `state`, `memories`, `mood`, `rel`, `help`, `scene_view`, `save_episode`, `episodes`.

### `slash_registry.py` — SlashCommandRegistry

| Método | Rol |
|--------|-----|
| `register(name, handler, desc)` | Registra comando |
| `command(name, desc)` | Decorador |
| `is_slash_command(text)` | Verifica si es comando registrado |
| `handle(text)` | Parsea y ejecuta |
| `list_commands()` / `get_help_text()` | Información |

### `internal.py` — Utilidades Internas

| Método | Rol |
|--------|-----|
| `_validate_prompt(prompt)` | Valida prompt no vacío |
| `_extract_response_text(result)` | Extrae texto de respuesta |
| `_extract_token_from_chunk(chunk)` | Extrae reasoning + content de chunk |
| `_record_stats(result)` / `_record_stats_from_stream(stream, text)` | Registro de estadísticas |
| `_log_generation_stats()` | Muestra stats en debug |

### `chat_memory.py` — ChatMemory

Mantiene historial en formato OpenAI con límite configurable y auto-trim.

| Método | Rol |
|--------|-----|
| `add_user_message(text)` / `add_assistant_message(content, tool_calls)` / `add_tool_message(content, id)` | Agrega mensajes |
| `get_context_messages()` | Retorna mensajes para inferencia |
| `trim_to_token_budget(max, reserve, count_fn)` | Recorte por tokens |
| `clear()` / `export_json()` / `import_json()` | Gestión |

### `config_manager.py` — ConfigManager

| Método | Rol |
|--------|-----|
| `load()` | Carga y valida config.json |
| `get()` / `reload()` | Acceso y recarga |
| `merge_character_config(char_dir)` | Mergea config del personaje |

### `logger_manager.py` — LoggerManager

Logging a archivo con rotación diaria + debug en consola con colores.

| Método | Rol |
|--------|-----|
| `debug(tag, msg)` / `info(msg)` / `warning(msg)` / `error(msg)` | Niveles de log |
| `enable_debug()` / `disable_debug()` | Toggle |

### `stats_manager.py` — StatsManager

| Método | Rol |
|--------|-----|
| `begin_generation()` / `end_generation(prompt_tokens, completion_tokens, model_name)` | Marca inicio/fin |
| `current` (property) | Última generación |
| `total_tokens_generated` (property) | Total acumulado |

### `tokenizer_utils.py` — Tokenización

| Función | Rol |
|---------|-----|
| `estimate_tokens(text)` | Estimación (~4 chars/token) |
| `count_tokens_exact(text, tokenize_fn)` | Conteo exacto con tokenizer del modelo |
| `is_context_near_limit(current, max, reserve)` | Determina si el contexto está cerca del límite |

## Dependencias

| Módulo | Importa desde |
|--------|---------------|
| `base.py` | `chat_memory`, `config_manager`, `logger_manager`, `stats_manager`, `slash_registry`, `model`, `character`, `soul`, `tools` |
| `chat.py` | `base`, `tools`, `exceptions` |
| `character.py` | `base`, `tools` |
| `memory.py` | `base`, `tokenizer_utils` |
| `internal.py` | `base` |
| `slash_commands.py` | `base` |

## Flujo de Inicialización

```
VToolLlama.__init__()
├── ConfigManager.load()           → ConfigSchema
├── LoggerManager(...)             → logging
├── ChatMemory(system_prompt, ...) → historial
├── StatsManager()                 → estadísticas
├── ModelManager(config, ...)      → modelo (si auto_load)
├── CharacterManager(logger_fn)    → personajes
├── ToolExecutionManager(...)      → tools
├── SoulGenerator(...)             → alma
├── SlashCommandRegistry()         → slash commands
└── _register_default_slash_commands()
```
