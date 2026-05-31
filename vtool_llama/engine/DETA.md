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
| `__init__(config_path, auto_load)` | Inicializa ConfigManager → LoggerManager → ChatMemory → StatsManager → ModelManager → CharacterManager (con `characters_directory` de config si existe) → ToolExecutionManager → SoulGenerator → SlashCommandRegistry. Carga modelo si `auto_load=True` |
| `load_model(path)` / `unload_model()` / `switch_model(path)` / `reload_model()` | Delega en `ModelManager` |
| `get_model_info()` / `list_available_models()` / `supports_tools()` | Consultas de capacidad del modelo |
| `generate_raw(messages, **kwargs) → Any` | Genera respuesta sin system prompt ni inyección de personalidad. Ideal para procesar DNA con IA |
| `get_config()` / `reload_config()` | Configuración |
| `enable_debug()` / `disable_debug()` | Debug toggle |
| `model_loading` (property) | `True` si el modelo se está cargando |
| `state_manager` (property) | Acceso a `CharacterManager` |
| `slash_commands` (property) | Acceso a `SlashCommandRegistry` |
| `chat_store` (property) | Acceso a `ChatStore` (SQLite event store) |
| `token_counter` (property) | Acceso a `TokenCounter` |
| `semantic_saving` (property) | `True` si se está indexando en ChromaDB |
| `loading` (property) | `True` si hay una carga de personaje en curso |
| `get_tool_stats() → dict` | Métricas de tools del `ToolExecutionManager` |
| `checkout(branch_id, leaf_message_id)` | Rollback no destructivo a un punto del historial |
| `delete_message(message_id)` | Soft-delete de un mensaje |
| `regenerate_response(message_id, label="") → str` | Crea branch desde un mensaje y checkout |
| `get_conversation_tree() → list[Branch]` | Lista todas las ramas de la conversación |
| `get_message_path(leaf_id) → list[ChatMessage]` | Reconstruye camino desde raíz hasta leaf |
| `get_chat_history(limit=100) → list[dict]` | Historial de la conversación activa |
| `index_conversation(incremental=True) → int` | Indexa conversación en ChromaDB |
| `rebuild_semantic_memory() → int` | Forza rebuild completo del índice semántico |
| `mark_semantic_dirty()` | Marca para rebuild en próximo index |
| `active_auto_save_at(interval)` | Activa auto-guardado cada N mensajes ### `chat.py` — Chat y Streaming
 
| Método | Rol |
|--------|-----|
| `chat(prompt, ...)` | Chat sincrónico con loop de Auto-Tools (hasta 3 iteraciones): inyecta contexto Soul + ChatMemory, inyecta estado dinámico actual, genera, maneja tool calls, coercion retry, drift detection y ejecuta auto-indexado incremental |
| `stream_chat(prompt, ...)` | Streaming con `StreamPostProcessor` para intercepción de tools en vuelo e indexado incremental al final |
| `chat_with_thinking(prompt, ...)` | Soporte `reasoning_content` nativo + parseo de `<think>`. Si `disable_thinking=true` en config, delega a `chat()` |
| `stream_chat_with_thinking(prompt, ...)` | Streaming con detección de `<think>`. Si `disable_thinking=true`, delega a `stream_chat()` |
| `add_tool_message(content, id)` | Agrega respuesta de herramienta al historial y la persiste en SQLite |
| `_inject_dynamic_state_into_messages(messages)` | Inyecta un mensaje system temporal con emociones, relaciones y mods dinámicos justo antes del mensaje del usuario |
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
 5. drift detection → add_assistant_message → auto-indexado semántico → return
 ```

Las tools internas se activan de forma condicional con `get_active_internal_tools(prompt, config)`. Por defecto `store_long_term_memory` solo se expone si el turno contiene un trigger de memoria; `always_enable_internal_tools=true` restaura el comportamiento anterior.

El fallback textual se controla con `enable_text_tool_fallback`. La ejecucion inmediata durante streaming esta desactivada por defecto con `enable_stream_tool_execution=false`.
 
 ### `character.py` — Operaciones de Personaje
 
 | Método | Rol |
 |--------|-----|
 | `load_character(name, semantic_memory=False) → CharacterLoadResult` | Cancela carga previa, carga personaje + mergea config + init ChatStore/ContextBuilder + warmup KV Cache. Retorna resultado con logs, soul_active, psychology_active |
 | `create_character(...)` | Crea estructura de directorios |
 | `generate_character_with_ai(name, prompt)` | Usa LLM para generar personaje completo (con doble intento + captura de reasoning_content si el modelo lo soporta) |
 | `generate_character_soul(...)` | Genera alma (delega en SoulGenerator) |
 | `has_character_soul(name)` / `get_character_soul(name)` | Consultas de alma |
 | `add_memory(...)` | Agrega memoria persistente |
 | `get_state_info()` | Estado actual del agente |
 | `get_character_dna(name=None) → dict` | Retorna DNA del personaje (lee de disco si se pasa name, sin cargar) |
 | `update_character_dna(dna_type, data, character_name=None)` | Actualiza DNA y persiste a disco. Si se pasa character_name, no carga el personaje |
 | `get_character_prompt(name) → str` | Retorna system prompt compilado desde base_prompt.yaml o construido desde DNA |
 | `get_system_layer(layer, character_name) → str` | Lee system_core.yaml o anti_assistant.yaml |
 | `update_system_layer(layer, content, character_name)` | Escribe system_core.yaml o anti_assistant.yaml |
 | `get_states() → dict` | Retorna runtime_state, personality_state, relationship_state |
 | `update_state(state_type, data)` | Actualiza y persiste un estado runtime |
 | `get_mods() → list[dict]` | Retorna mods activos |
 | `set_mod(id, target_layer, override_value, intensity)` | Aplica un mod temporal |
 | `remove_mod(mod_id)` | Elimina un mod |
 | `rebuild_personality_state()` | Reconstruye personalidad desde historial + guarda base_prompt.yaml |
 | `_warmup_character_cache(prompt)` | Compila prompt estático completo → guarda `base_prompt.yaml` → warmup total → mide `n_keep` (tokens del core) → guarda `base.state` + `n_keep` en meta. Al cargar, restaura `_n_keep` desde meta para que `reset_keep()` proteja el core (v6) |
 | `_inject_personality_into_system_prompt()` | Inyecta únicamente el prompt de sistema ESTABLE del personaje (sin TOOL_USAGE_POLICY). Se llama solo en load_character() y cuando se restaura el prompt tras trim/episode. El core del KV cache se mantiene estable entre turnos (v6+v7) |
| `_inject_tool_policy_if_needed(messages, user_prompt)` | Inyecta `TOOL_USAGE_POLICY` como mensaje `system` dinámico antes del último `user` solo si hay tools activas. NO modifica el core del KV cache (v7) |
 | `_check_and_rebuild_if_needed()` | Rebuild automático antes del chat si hay memorias nuevas |
 
 ### `memory.py` — Memoria y Episodios
 
 | Método | Rol |
 |--------|-----|
 | `clear_memory()` / `reset_chat()` | Limpia historial |
 | `get_memory()` / `export_memory_json()` / `import_memory_json()` | Acceso y serialización |
 | `set_system_prompt(prompt)` | Cambia system prompt |
| `trim_memory()` | Recorte manual de contexto |
| `_auto_trim_if_needed()` | Trunca el contexto por lotes hasta ~60% del `effective_limit` usando conteo preciso de tokens de plantilla. Genera un resumen previo inyectado como mensaje de sistema en posición 1, previniendo acumulación repetitiva. Ya no hace save/restore del KV cache (v6): `reset_keep()` mantiene el core intacto durante la generación del digest. |
 | `save_episode()` / `list_episodes()` / `load_episode()` / `delete_episode()` | Gestión de episodios |
 | `get_token_usage()` | Retorna desglose de tokens del prompt: `prompt_tokens`/`total_tokens`, `system_tokens`, `history_tokens`, `effective_context_limit`, `prompt_budget_available`, `response_capacity`, `safe_max_response_tokens`, `usage_pct`. Además (v6): `n_keep` (core protegido en KV cache), `kv_cache_tokens` (tokens reales en el KV cache del modelo), `kv_cache_usage_pct` (% real de uso del KV cache) |
 | `get_prompt_layer_usage()` | Retorna diagnostico de tokens por capa del prompt del personaje y presupuesto restante tras el bloque estatico |
 | `_extract_inline_context()` | Parsea `[context tipo texto]` del prompt del usuario |
 
 ### `slash_commands.py` — Handlers de Slash Commands
 
 Métodos `_cmd_*` asignados a `VToolLlama`: `mem`, `rebuild`, `state`, `memories`, `mood`, `rel`, `help`, `scene_view`, `save_episode`, `episodes`, `history`, `semantic`, `clean`, `config`, `context`, `tick`, `resume`.
 
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

Ring buffer en RAM con `deque(maxlen=chat_memory_limit+1)`. Cada `append()` verifica que el system prompt no haya sido descartado via `_ensure_system_prompt()`.
 
 | Método | Rol |
 |--------|-----|
 | `add_user_message(text)` | Agrega mensaje user + sync SQLite + `_ensure_system_prompt()` |
 | `add_assistant_message(content, tool_calls)` | Agrega respuesta + sync SQLite + `_ensure_system_prompt()` |
 | `add_tool_message(content, id)` | Agrega respuesta de herramienta + sync SQLite + `_ensure_system_prompt()` |
 | `get_context_messages()` | Retorna mensajes para inferencia |
| `clear()` | Preserva system prompt, elimina el resto |
| `_ensure_system_prompt()` | Reinserta system prompt si fue descartado por el deque |

### `memory.py` — Trim y Context Digest

El trim automatico es una proteccion obligatoria del pipeline. La clave `auto_trim_context` puede seguir existiendo en config por compatibilidad, pero `_auto_trim_if_needed()` no debe depender de ella para decidir si protege el contexto.

Cuando el contexto se acerca al limite efectivo (`n_ctx - context_reserve_tokens`), el flujo actual:

1. Cuenta tokens sobre `ChatMemory.get_context_messages()` usando `ModelManager.count_messages_tokens()` si esta disponible.
2. Protege siempre el ultimo mensaje `user`.
3. Toma como candidatos solo mensajes no-system que pueden salir del contexto.
4. Genera un `context digest` estructurado con `ModelManager.generate(...)`.
5. Guarda/restaura KV cache con `save_state/load_state` si el backend lo soporta.
6. Inserta un unico bloque system `[RESUMEN DE CONVERSACION PREVIA]` y elimina digests anteriores.
7. Guarda el digest en SQLite con `ChatStore.add_summary(..., reason="trim")`.
8. Recorta mensajes antiguos hasta volver al presupuesto.

El digest no es un resumen narrativo; es memoria operacional en secciones fijas: hechos estables, estado actual, preferencias, relacion y tono, hilos abiertos y descarte.

Los prompts tecnicos del digest se cargan desde `config/prompts/helpers/`:

| Archivo | Rol |
|---|---|
| `context_digest_system.md` | Instrucciones tecnicas del compresor, escritas en ingles |
| `context_digest_user.md` | Template del mensaje user con placeholder `#SOURCE` |

La salida del digest debe permanecer en espanol aunque las instrucciones tecnicas internas esten en ingles.

`get_token_usage()` separa dos presupuestos que antes podian confundirse:

- `prompt_budget_available`: espacio restante para mas prompt/contexto manteniendo `context_reserve_tokens` libres.
- `response_capacity`: tokens que aun caben para una respuesta antes de tocar `n_ctx`.
- `safe_max_response_tokens`: capacidad de respuesta limitada por `config.max_tokens`.
- `budget_available`: alias legacy de `prompt_budget_available`.

Si `compact_system_prompt=true`, `CharacterManager.build_system_prompt()` retorna una `[CHARACTER CAPSULE]` compacta para runtime. El prompt completo sigue disponible mediante `build_full_system_prompt()` para auditoria y rebuild.

Durante `_warmup_character_cache()` se escriben:

- `_memory/base_prompt.yaml`: prompt runtime usado para el KV cache.
- `_memory/base_prompt_full.yaml`: prompt completo.
- `_memory/base_prompt_compact.yaml`: prompt compacto.

La metadata de `base.state` incluye `full_prompt_hash`, `compact_prompt_hash` y el flag `compact_system_prompt`.
 
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
 | `is_context_near_limit(current, max, reserve)` | Determina si el contexto está cerca del límite (compara contra el `effective_limit`) |
 
 ### `retrieval.py` — Estrategias de Recuperación
 
 Estrategias independientes que implementan `RetrievalStrategy.retrieve()`. Usadas por ContextBuilder.
 
 | Estrategia | Prioridad | Qué trae |
 |---|---|---|
 | `RecentMessagesStrategy` | 50 | Mensajes activos de la conversación actual hasta el presupuesto configurado |
 | `SemanticRetrievalStrategy` | 20 | Búsqueda semántica en ChromaDB utilizando los últimos 3 turnos como query. Filtra con similitud mínima cosine (`min_similarity`). |
 | `SceneContextStrategy` | 15 | Inyecta el texto descriptivo de la última escena activa. (Definida en `orquestador/strategies.py`) |
 | `ContextInjectionStrategy` | 10 | Inyecta las entradas de contexto activas recopiladas por el orquestador. (Definida en `orquestador/strategies.py`) |

### `context_builder.py` — Orquestador de Contexto

Coordina las estrategias de retrieval para ensamblar el prompt final. NO implementa retrieval directamente.

```python
ContextBuilder
├── build(conv_id, branch, leaf, token_budget, system_prompt) → list[PromptSection]
├── build_messages(...) → list[dict]  # wrapper directo para el LLM
└── get_section_breakdown(...) → list[dict]  # debug: tokens por sección
```

**Flujo:**
1. System prompt → PromptSection priority=0
2. Cada estrategia en orden de priority
3. Consolidar en list[dict]
4. Guardar context_snapshot si debug

### `chat_memory.py` — ChatMemory (actualizado)

Sigue siendo un ring buffer en RAM, pero ahora puede sincronizar con SQLite:

| Método nuevo | Rol |
|---|---|
| `bind_store(store, builder, counter, conv_id, branch, leaf)` | Vincula al SQLite event store |
| `load_context(token_budget)` | Reconstruye el buffer desde ContextBuilder |
| `add_user_message(content)` | También persiste en SQLite + actualiza active_leaf |
| `add_assistant_message(content, tool_calls)` | También persiste en SQLite + actualiza active_leaf |

## Dependencias

| Módulo | Importa desde |
|--------|---------------|
| `base.py` | `chat_memory`, `config_manager`, `logger_manager`, `stats_manager`, `slash_registry`, `model`, `character`, `soul`, `tools`, `db`, `utils` |
| `chat.py` | `base`, `tools`, `exceptions` |
| `character.py` | `base`, `tools`, `db`, `utils`, `context_builder`, `retrieval` |
| `memory.py` | `base`, `types`, `config/prompts/helpers` |
| `internal.py` | `base` |
| `slash_commands.py` | `base` |
| `context_builder.py` | `retrieval` |
| `retrieval.py` | `db`, `utils` |

## Flujo de Inicialización

```
VToolLlama.__init__()
├── ConfigManager.load()           → ConfigSchema
├── LoggerManager(...)             → logging
├── ChatMemory(system_prompt, ...) → historial
├── StatsManager()                 → estadísticas
├── ModelManager(config, ...)      → modelo (si auto_load)
├── CharacterManager(base_dir, logger_fn) → personajes
├── ToolExecutionManager(...)      → tools
├── SoulGenerator(...)             → alma
├── SlashCommandRegistry()         → slash commands
└── _register_default_slash_commands()

VToolLlama.load_character(name)
├── CharacterManager.load()
├── ChatStore(db_path)             → SQLite event store
├── TokenCounter(tokenize_fn)      → contador centralizado
├── ContextBuilder(store, counter, strategies) → orquestador
├── ChatMemory.bind_store()        → vincula al store
├── Config merge
├── _warmup_character_cache():
│   ├── build_system_prompt()      → prompt runtime (full o compact segun config)
│   ├── guarda base_prompt*.yaml   → runtime/full/compact para debug
│   └── warmup + save base.state   → KV Cache inicial del prompt runtime
├── ChatMemory.load_context()      → reconstruye desde SQLite vía ContextBuilder
└── Personality injection

VToolLlama.chat(prompt)
├── ChatMemory.add_user_message()  → escribe a SQLite + RAM
├── _auto_trim_if_needed()          → context digest + recorte obligatorio si hace falta
├── ModelManager.generate(messages) → infiere
├── ChatMemory.add_assistant_message() → escribe a SQLite + RAM
├── Auto-summary cada N turnos     → SQLite summaries
└── Memory extraction (opt-in)     → SQLite memories
```
