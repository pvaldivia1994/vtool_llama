# vtool_llama — Arquitectura del Proyecto

SDD para agentes. Librería de IA conversacional local para Windows que usa modelos GGUF via `llama-cpp-python`. Organizada en 11 subpackages por dominio, cada uno con su propio `AGENT.md` (resumen + trigger) y `DETA.md` (arquitectura detallada).

```
vtool_llama/
├── engine/           # Núcleo: VToolLlama, chat, streaming, configuración, logging
├── model/            # ModelManager: carga, inferencia, GPU, KV Cache
├── soul/             # Soul System: generación de vida simulada
├── psychology/       # Psychology Engine v2: psicología runtime emergente
├── character/        # CharacterManager: carga, persistencia, episodios
├── compiler/         # CharacterCompiler: ensamblado del system prompt
├── orquestador/      # ContextInjector: contexto dinámico inyectable ([CONTEXT][...])
├── tools/            # Tool system: function calling, parseo, ejecución
├── types/            # Dataclasses compartidas (core, character, chat, psychology)
├── db/               # ChatStore (SQLite event store) + ChromaDB wrapper + file I/O
├── utils/            # Utilidades: TokenCounter
├── exceptions.py     # Jerarquía de errores
└── __init__.py       # Public API barrel
```

## Navegación

Cada subpackage contiene:

| Archivo | Propósito |
|---------|-----------|
| `AGENT.md` | Resumen de 2-3 líneas + **trigger**: cuándo leer `DETA.md` |
| `DETA.md` | Arquitectura detallada: clases, métodos, dependencias, flujos |
| `__init__.py` | Barrel + exports |

## Índice de Subpackages

### `engine/` — `vtool_llama/engine/AGENT.md`
**Trigger**: El usuario pregunta sobre `VToolLlama`, chat, streaming, carga de modelo, configuración, logging, estadísticas, memoria de conversación, o el entry point de la librería.

Contenido: `base.py` (VToolLlama class), `chat.py`, `character.py`, `memory.py`, `slash_commands.py`, `slash_registry.py`, `internal.py`, `chat_memory.py`, `config_manager.py`, `logger_manager.py`, `stats_manager.py`, `tokenizer_utils.py`, `context_builder.py` (orquestador de contexto), `retrieval.py` (estrategias de recuperación).

### `model/` — `vtool_llama/model/AGENT.md`
**Trigger**: El usuario pregunta sobre carga/descarga de modelos GGUF, generación de texto, detección CUDA, warmup de KV Cache, conteo de tokens, o soporte de tool calling.

Contenido: `manager.py` (ModelManager), `model_ops.py`, `inference.py`, `kv_cache.py`, `capacity.py`.

### `soul/` — `vtool_llama/soul/AGENT.md`
**Trigger**: El usuario pregunta sobre generación de alma/vida simulada, eventos de vida, Life Director, Character Mind, reflexión psicológica, deriva de identidad, compresión semántica, checkpoints, o búsqueda semántica de recuerdos.

Contenido: `soul_generator.py` (SoulGenerator), `initialization.py`, `events.py`, `simulation.py`, `reflection.py`, `compression.py`, `accessor.py` (RuntimeSoulAccessor).

### `psychology/` — `vtool_llama/psychology/AGENT.md`
**Trigger**: El usuario pregunta sobre psicología runtime, emociones (valence/arousal), personalidad Big Five, apego, deriva de comportamiento, creencias, o síntesis de persona.

Contenido: `emotional_dynamics.py` (EmotionalDynamics), `synthesizer.py` (PsychologySynthesizer), `drift_detector.py` (DriftDetector), `belief_manager.py` (BeliefManager), `runtime_manager.py` (RuntimeSoulManager), `dna_adapter.py`.

### `character/` — `vtool_llama/character/AGENT.md`
**Trigger**: El usuario pregunta sobre personajes, DNA, memoria persistente, episodios, estados runtime, psychology engine, o modificadores (mods).

Contenido: `base.py` (CharacterManager), `persistence.py`, `episodes.py`, `psychology_init.py`.

### `compiler/` — `vtool_llama/compiler/AGENT.md`
**Trigger**: El usuario pregunta sobre el system prompt del personaje, capas del prompt, archivos YAML/ templates `.md` de personaje, resolución de conflictos entre capas, o modificación de cómo se ensambla el prompt.

Contenido: `compiler.py` (CharacterCompiler), `yaml_loader.py`, `dna_layers.py` (templates `.md` + `_render_template()`).

### `tools/` — `vtool_llama/tools/AGENT.md`
**Trigger**: El usuario pregunta sobre tools, function calling, tool calls en texto plano o estructurado, parseo, ejecución de herramientas internas (memoria, escena), o procesamiento streaming con tools.

Contenido: `definitions.py`, `parser.py`, `manager.py` (ToolExecutionManager), `stream_processor.py` (StreamPostProcessor).

### `types/` — `vtool_llama/types/AGENT.md`
**Trigger**: El usuario pregunta sobre tipos de datos, dataclasses, esquemas de configuración, estructura del DNA, Genome, o estado psicológico.

Contenido: `core.py`, `character.py`, `psychology.py`.

### `db/` — `vtool_llama/db/AGENT.md`
**Trigger**: El usuario pregunta sobre almacenamiento vectorial, ChromaDB, SQLite event store, historial de chat, branching, búsqueda semántica, lectura/escritura de archivos JSON, escritura atómica, o persistencia de datos.

Contenido: `chat_store.py` (ChatStore — SQLite event store con branching), `chroma_store.py` (ChromaStore — solo memorias semánticas), `io.py`.

## Flujo de Decisión para Agentes

Cuando el usuario hace una consulta:

1. Identificar el dominio por palabras clave
2. Leer el `AGENT.md` del subpackage correspondiente
3. Si el AGENT.md dice "LEER PRIMERO DETA.md", abrir `DETA.md`
4. Si abarca múltiples dominios, leer los AGENT.md de todos los involucrados
5. Si es una pregunta general sobre el proyecto, leer este archivo

### Ejemplos de mapeo consulta → subpackage

| Consulta del usuario | Subpackage a leer |
|---------------------|-------------------|
| "El chat no responde" / "cómo uso VToolLlama" | `engine/` |
| "El modelo no carga" / "cómo cambio de modelo" | `model/` |
| "Generar alma para un personaje" | `soul/` |
| "La personalidad del personaje no se nota" | `psychology/` + `compiler/` |
| "Crear un personaje nuevo" / "guardar memoria" | `character/` |
| "El prompt del personaje está mal" / "cómo se ensambla" | `compiler/` |
| "Las tools no funcionan" / "function calling" | `tools/` |
| "Error de tipo" / "dónde se define X" | `types/` |
| "ChromaDB no disponible" / "dónde se guardan los datos" | `db/` |

## Arquitectura General

```
                    ┌──────────────┐
                    │  vtool_llama │
                    │  __init__.py │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────────┐
              ▼            ▼                ▼
        ┌──────────┐ ┌──────────┐ ┌──────────────────┐
        │  engine  │ │  model   │ │ tools  db  types  │
        │ VToolLlama│ │ModelMgr │ │(infraestructura) │
        └────┬─────┘ └──────────┘ └──────────────────┘
             │
      ┌──────┼──────────┐
      ▼      ▼          ▼
 ┌────────┐ ┌────────┐ ┌──────────┐
 │character│ │compiler│ │psychology│
 │CharMgr │ │Compiler│ │  Engine  │
 └────────┘ └────────┘ └────┬─────┘
      │                     │
      └─────────┬───────────┘
                ▼
          ┌──────────┐
          │   soul   │
          │ SoulGen  │
          └──────────┘
```

### Capas

1. **Infraestructura** (`db/`, `types/`, `tools/`): servicios base sin lógica de dominio
2. **Core** (`engine/`, `model/`): orquestación y ciclo de vida del LLM
3. **Personaje** (`character/`, `compiler/`): gestión de personajes y ensamblado de prompts
4. **Psicología** (`psychology/`, `soul/`): simulación de vida y psicología emergente

### Dependencias entre subpackages

```
engine → model, character, soul, psychology, tools, db, types
model → types
character → compiler, soul, psychology, db, types
soul → db, psychology, types
psychology → types
compiler → types, character
tools → types
```

## Convenciones del Proyecto

- **Monkey-patching**: `engine/`, `model/`, `soul/`, `character/`, `compiler/` usan el patrón de definir funciones que reciben `self` y asignarlas a la clase. Esto permite dividir clases grandes en múltiples archivos.
- **Clases independientes**: `psychology/`, `tools/`, `db/` tienen cada clase en su propio archivo sin monkey-patching.
- **Types**: todas las dataclasses en `types/`, organizadas por dominio. Nunca definir dataclasses fuera de `types/`.
- **Imports**: siempre relativos dentro del paquete (`from ..types import X`). La raíz `__init__.py` es el único punto de entrada público.
- **Escritura atómica**: `db.io.write_json()` usa `.tmp` + `os.replace` para evitar corrupción.
