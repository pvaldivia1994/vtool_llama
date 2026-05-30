# Character System — Arquitectura Detallada

## Visión General

El Character System orquesta la carga, ensamblado, persistencia y evolución runtime de personajes. Cada personaje tiene una estructura de directorios con capas inmutables (DNA), mutables (memoria, estado) y temporales (mods).

```
characters/<nombre>/
├── dna/                        # Inmutable — se crea una vez
│   ├── identity.json           # IdentityDNA
│   ├── personality.json        # PersonalityDNA
│   ├── speech.json             # SpeechDNA
│   └── rules.json              # RulesDNA
├── _memory/
│   ├── long_term.json          # Memorias persistentes (MemoryEntry[])
│   ├── episodes/               # Snapshots episódicos versionados
│   │   ├── episode_001.json
│   │   └── ...
│   └── chat_history/           # ChromaDB — historial de conversación
├── state/                      # Mutable — cambia en runtime
│   ├── state_meta.json         # Hash del prompt para KV Cache
│   ├── runtime_state.json      # RuntimeState
│   ├── personality_state.json  # PersonalityState
│   └── relationship_state.json # RelationshipState
├── mods/
│   └── active_mods.json        # Mods temporales activos
├── config.json                 # Overrides de configuración
├── system_core.yaml            # System prompt (human-like behavior)
└── anti_assistant.yaml   # Anti-assistant constraints
```

## Archivos del Subpackage

### `__init__.py`
Barrel. Exporta `CharacterManager`. Garantiza que todos los métodos se asignen a la clase.

### `base.py` — Clase Base

Define `CharacterManager`, el orquestador central. Responsabilidades:

| Método | Rol |
|--------|-----|
| `__init__()` | Inicializa todas las capas (DNA, memoria, estado, mods, compilador, ChromaDB). Acepta `base_dir` opcional para ruta de personajes |
| `load_character(name) → CharacterLoadResult` | Carga un personaje completo desde disco. Retorna resultado con logs, estados y éxito |
| `create_character(...)` | Crea estructura de directorios + archivos iniciales |
| `build_system_prompt(...)` | Delega en `CharacterCompiler` para ensamblar el prompt final |
| `build_base_system_prompt(...)` | Prompt base para KV Cache (solo DNA) |
| `compile_base_soul_prompt(...)` | Prompt base + Soul System |
| `get_relevant_memories()` | Memorias ordenadas por prioridad |
| `cancel_load()` | Solicita cancelación de la carga en curso (thread-safe, non-blocking) |
| `_check_cancel()` | Lanza `LoadCancelledError` si `_cancel_loading=True`. Llamado entre cada paso de `load_character` |
| I/O utils | `_ensure_dir`, `_read_json_dict`, `_read_json`, `_write_json`, `_log` |

**Propiedades**: `is_loaded`, `character_name`, `loading` (True durante carga), `last_load_result` (último result, incluso si falló), `check_needs_rebuild(prompt)`

**Log capture**: `_log()` acumula mensajes en `_load_logs` cuando `_loading=True`. Al finalizar carga, los logs se copian a `CharacterLoadResult.logs` y se limpia el buffer.

**Cancelación**: Si se llama `cancel_load()` (o un nuevo `load_character` desde `VToolLlama`), se activa `_cancel_loading`. Los checkpoints en `load_character` detectan la bandera y abortan limpiamente, retornando `CharacterLoadResult(success=False)`. La excepción `LoadCancelledError` NO se propaga al usuario.

**Uso**: `CharacterManager` es instanciado por `engine/base.py` y accedido vía `VToolLlama.state_manager`.

### `persistence.py` — Persistencia de Datos

Métodos asignados a `CharacterManager` para carga/guardado de datos:

| Método | Archivo que persiste |
|--------|---------------------|
| `_load_dna()` | `dna/{identity,personality,speech,rules}.json` |
| `_load_memory()` | `_memory/long_term.json` |
| `_load_state()` | `state/{runtime,personality,relationship}_state.json` + `state_meta.json` |
| `_load_mods()` | `mods/active_mods.json` |
| `save_state()` | Todos los anteriores (escritura atómica con `.tmp`) |
| `mark_rebuild_done(prompt)` | Actualiza hash y marca rebuild como completo |
| `add_memory(...)` | Agrega `MemoryEntry`, marca dirty |
| `set_mod(mod)` / `remove_mod(mod_id)` | Mods temporales |

### `episodes.py` — Memoria Episódica

Snapshots versionados de la conversación (nunca se sobreescriben).

| Método | Rol |
|--------|-----|
| `_load_latest_episode()` | Carga el episode_*.json más reciente |
| `save_episode(messages, summary)` | Crea episode_NNN.json incremental |
| `list_episodes()` | Lista metadata de todos los episodios desde SQLite o JSON |
| `load_episode(id)` | Rollback NO destructivo: checkout a summary (SQLite) o carga JSON |
| `delete_episode(id)` | Elimina un episodio |

Los episodios se guardan en la tabla `summaries` de SQLite (cuando hay ChatStore) o en archivos JSON como fallback.

### ~~`chat_history.py` — Eliminado~~

Reemplazado por `db/chat_store.py` (SQLite event store). El historial de chat ahora se guarda en:
- `characters/<name>/chat.db` → tabla `messages` (source of truth)
- ChromaDB ya no guarda turnos de chat, solo memorias semánticas

### `psychology_init.py` — Inicialización de Sistemas Avanzados

Inicializa el Soul System y Psychology Engine v2 cuando existen los datos correspondientes.

| Método | Rol |
|--------|-----|
| `_init_soul_accessor()` | Busca `soul.json` y activa `RuntimeSoulAccessor` si existe |
| `_init_psychology_engine()` | Carga/deriva Genome, inicializa `RuntimeSoulManager` |
| `_load_core_identity()` | Carga CoreIdentity desde disco o lo deriva |
| `_derive_core_identity_from_genome()` | Genera CoreIdentity desde Genome si no hay archivo |
| `save_psychology_state()` | Persiste psychology state + CoreIdentity |

**Dependencias**: `soul.RuntimeSoulAccessor`, `soul.SoulGenerator`, `psychology.PsychologySynthesizer`, `psychology.RuntimeSoulManager`, `psychology.dna_traits_to_genome`.

## Dependencias Externas

| Módulo | Se importa desde |
|--------|-----------------|
| `types/*` | Todos los archivos (dataclasses) |
| `compiler.CharacterCompiler` | `base.py` |
| `soul.RuntimeSoulAccessor` | `psychology_init.py` |
| `soul.SoulGenerator` | `psychology_init.py` |
| `psychology.*` | `psychology_init.py` |

## Sistema de Archivos Compartido

Los personajes viven en `vtool_llama/characters/`. Cada subcarpeta es un personaje.

`CharacterManager` usa escritura atómica (`_write_json` escribe a `.tmp` y renombra) para evitar corrupción ante cortes de energía.
