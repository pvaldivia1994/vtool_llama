# Orquestador — Arquitectura Detallada

## Visión General

El orquestador gestiona entradas de contexto dinámico que se inyectan en el prompt del personaje. Cada entrada tiene un estado: **activa** (end_message_id=0) o **entregada** (end_message_id>0).

Las activas se inyectan en el próximo turno. Las entregadas pasan al historial como mensajes `role="context"` y no se vuelven a inyectar.

```
orquestador/
├── __init__.py              # Barrel
├── context_injector.py      # CRUD de entradas de contexto
├── strategies.py            # ContextInjectionStrategy para ContextBuilder
└── tags.py                  # Sistema unificado de tags semánticos (v13)
```

## Archivos

### `tags.py` — Sistema de Tags (v13)

Define la taxonomía unificada de tags semánticos.

| Tag | Nivel | Uso |
|-----|-------|-----|
| `[DEFINE]` | Sistema | Definición permanente del personaje |
| `[STATE]` | Sistema | Estado emocional/relacional actual |
| `[SCENE]` | Sistema | Descripción de escena |
| `[ID][SPEAK]` | Diálogo | Cuando un personaje HABLA |
| `[ID][ACT]` | Acción | Cuando un personaje ACTÚA |
| `[ID][THOUGHT]` | Pensamiento | Pensamiento interno del personaje |

`TAG_DEFINITIONS` contiene la guía completa que se inyecta en `base_prompt.yaml`.

### `context_injector.py` — ContextInjector

```
ContextInjector
├── __init__(store, conversation_id, branch_id)
├── add(tipo, contenido, order?) → id
├── list(only_active=True) → list[ContextEntry]
├── remove(id) → bool
├── clear() → int
├── mark_delivered(ids)     # marca como entregadas + inserta en historial como role="context"
├── save_scene(texto) → id  # reemplaza la escena anterior
├── get_scene() → str|None
├── get_active_contexts() → list[str]
└── get_history_contexts() → list[str]
```

**Entry (dataclass):**

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | `int` | ID en SQLite |
| `ctx_type` | `str` | `scene`, `character`, `thoughts`, `goals`, `time`, `world`, `memory`, `custom` |
| `content` | `str` | Texto descriptivo |
| `tag` | `str` | `[CONTEXT][TIPO]` |
| `order` | `int` | Orden de inserción |
| `created_at` | `str` | Timestamp |

### `strategies.py` — Estrategias de Retrieval

**ContextInjectionStrategy** (priority=10): inyecta solo entradas activas (no entregadas) como `{"role": "system", "content": "[CONTEXT][TIPO] valor"}`.

## Tags disponibles

| Tag | Propósito | Comando |
|-----|-----------|---------|
| `[CONTEXT][SCENE]` | Escena actual, ubicación, personajes presentes | `/scene_view` |
| `[CONTEXT][CHARACTER]` | Estado emocional/mental/físico | `/context character ...` |
| `[CONTEXT][THOUGHTS]` | Pensamientos, intenciones, motivaciones | `/context thoughts ...` |
| `[CONTEXT][GOALS]` | Objetivos activos, misiones, deseos | `/context goals ...` |
| `[CONTEXT][TIME]` | Momento del día, clima, estación | `/context time ...` |
| `[CONTEXT][WORLD]` | Eventos del entorno, ambiente | `/context world ...` |
| `[CONTEXT][MEMORY]` | Hechos importantes, relaciones | `/context memory ...` |
| `[CONTEXT][PLAYER]` | Acción actual del jugador (el personaje reacciona a esto) | `/context player ...` |
| `[CONTEXT][CUSTOM]` | Contexto definido por el usuario | `/context custom ...` |

## Flujo de estado

```
/context character Está triste → end_message_id=0 (activa)
/context list → muestra solo activas
/tick → inyecta activas → mark_delivered() → end_message_id>0 + inserta en messages como role="context"
/context debug → (vacío, ya no hay activas)
/history → muestra el context como 📌 en medio del historial
```

## Dependencias

| Módulo | Lo usa |
|--------|--------|
| `db.chat_store` | Tabla `summaries` y `messages` |
| `engine.character.py` | `ContextInjectionStrategy` en ContextBuilder |
| `engine.slash_commands.py` | `/context`, `/scene_view`, `/tick` |
