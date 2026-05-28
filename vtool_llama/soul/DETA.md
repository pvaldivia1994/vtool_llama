# Soul System — Arquitectura Detallada

## Visión General

Genera una vida simulada persistente para personajes usando un pipeline de 10 fases. Cada fase se implementa en su propio archivo y se asigna a `SoulGenerator` vía monkey-patching.

```
soul/
├── __init__.py            # Barrel: exporta SoulGenerator, RuntimeSoulAccessor
├── soul_generator.py      # SoulGenerator class + __init__ + API pública + _SoulState + constantes
├── initialization.py      # Fase 1: Inicialización desde DNA/Genome
├── events.py              # Fase 2-5: Life Director, Character Mind, eventos aleatorios
├── simulation.py          # Simulación mes a mes, caos, modo interactivo
├── reflection.py          # Fase 6+8: Reflection Engine + Identity Drift
├── compression.py         # Fase 9: Compresión semántica + Checkpoints + Persistencia
└── accessor.py            # RuntimeSoulAccessor: acceso runtime al alma generada
```

## Pipeline de 10 Fases

```
Fase  1 — Inicialización del ser (desde DNA/Genome)              → initialization.py
Fase  2 — Simulación temporal mes a mes                           → simulation.py
Fase  3 — Context Engine para cada mes                            → events.py
Fase  4 — Event Probability Engine (pesos dinámicos)              → events.py
Fase  5 — Generación de eventos por etapa via LLM (Life Director) → events.py
Fase  6 — Reflection Engine (eventos importantes)                 → reflection.py
Fase  7 — Relationship Evolution                                  → (integrado en simulation.py)
Fase  8 — Identity Drift (personalidad cambia con la vida)        → reflection.py
Fase  9 — Semantic Compression → soul.json                        → compression.py
Fase 10 — Retrieval Architecture (búsqueda semántica)             → accessor.py
```

## Archivos del Subpackage

### `__init__.py`
Barrel. Exporta `SoulGenerator` y `RuntimeSoulAccessor`. Importa los 5 submódulos de fase para registrar métodos.

### `soul_generator.py` — Clase Base

Define `SoulGenerator`, el `_SoulState` (dataclass), y todas las constantes del sistema.

**Constantes:**
- `EVENT_TYPES` — 28 tipos de eventos (family, romantic, trauma, etc.)
- `LIFE_STAGES` — 6 etapas: early_childhood (0-6) → maturity (50+)
- `DEFAULT_EVENT_WEIGHTS` — Pesos probabilísticos por tipo de evento
- `SOUL_GENERATION_SYSTEM_PROMPT` — System prompt para el Life Director LLM

**API Pública:**

| Método | Rol |
|--------|-----|
| `generate_soul(...)` | Orquestador principal: 18 parámetros, ejecuta el pipeline completo |
| `retrieve_relevant_memories(query, ...)` | Búsqueda semántica con scoring compuesto (similitud + importancia + peso emocional + retención) y filtro de amnesia infantil |
| `has_soul(character_name)` | Verifica existencia de `soul.json` |
| `has_timeline_db(character_name)` | Verifica existencia de base ChromaDB |
| `get_soul_data(character_name)` | Lee y retorna `soul.json` como dict |
| `get_soul_path(character_name)` | Retorna Path al `soul.json` si existe |

**`_SoulState`**: Dataclass con ~20 campos: `core_traits`, `beliefs`, `mental_state`, `worldview`, `goals`, `fears`, `education_stage`, etc.

### `initialization.py` — Fase 1

| Método | Rol |
|--------|-----|
| `_init_soul_state(identity, personality, speech, rules, age, genome)` | Construye estado inicial desde Genome + DNA: Big Five, worldview, mental state, valores, miedos |
| `_load_genome(char_dir, personality)` | Carga `genome.json` o deriva desde PersonalityDNA |

### `events.py` — Fase 2-5

Generación de eventos de vida usando el patrón Life Director (LLM) + Character Mind (LLM) + Random Chaos Layer.

| Método | Rol |
|--------|-----|
| `_interpret_event_with_character_mind(name, traits, flaws, motivations, event)` | Usa LLM para interpretar subjetivamente un evento objetivo → emoción, impacto psicológico, creencia, reflexión, coping |
| `_roll_random_chaos_event(age)` | Lanzamiento anual de caos: 3 capas (life-changing 2%, strong 8%, social 20%) con modifiers por genome y economía |
| `_pre_generate_stage_events(identity, personality, ...)` | Life Director: genera eventos por etapa via LLM, luego los interpreta con Character Mind |
| `_parse_events_from_json(text)` | Parsea JSON de eventos desde respuesta del LLM |
| `_generate_random_events(age, start)` | Fallback aleatorio cuando no hay LLM |
| `_generate_random_events_for_stage(stage, age, start)` | Eventos aleatorios para una etapa específica |

**Life Director prompt**: Incluye contexto histórico, geográfico, económico y de mundo (real o ficción). Soporta `query_for_orchestrator` para modo interactivo.

### `simulation.py` — Simulación Mes a Mes

Itera mes a mes la vida del personaje.

| Método | Rol |
|--------|-----|
| `_simulate_life(age, stage_events, start, ...)` | Loop principal: por cada mes procesa eventos, chaos anual, micro-eventos, modo interactivo, identity drift anual, checkpoints cada 6 meses |
| `_generate_micro_event(month)` | Micro-evento aleatorio (encuentro casual, reflexión, descubrimiento) |

**Por mes:**
1. Random Chaos Layer (anual, al iniciar año)
2. Procesar eventos del mes → ChromaDB + history + progreso
3. Reflexión sobre eventos importantes (>0.65)
4. Micro-eventos si no hay eventos mayores (8% probabilidad)
5. Timeline Interactive Mode (fin de año, si está activo)
6. Identity Drift (anual)

### `reflection.py` — Fase 6 + 8

| Método | Rol |
|--------|-----|
| `_process_reflection(event, state)` | Procesa reflexión sobre evento importante: actualiza mental_state, beliefs, skills |
| `_generate_reflection_with_llm(event, state)` | Reflexión profunda via LLM con contexto del estado actual |
| `_generate_reflection_rule_based(event, state)` | Reflexión basada en reglas (6 tipos mapeados: loss, trauma, betrayal, success, failure, romantic) |
| `_parse_reflection_from_json(text)` | Parsea JSON de reflexión |
| `_apply_identity_drift(month, state)` | Deriva anual de Big Five: drift natural, neuroticism por conflictos, agreeableness por traumas, conscientiousness por edad |

### `compression.py` — Fase 9 + Persistencia

Comprime toda la vida simulada en `soul.json`.

| Método | Rol |
|--------|-----|
| `_compress_soul(total_events)` | Orquesta compresión: LLM si disponible, sino heurística |
| `_compress_with_llm(state, total_events)` | Usa LLM para generar núcleo psicológico comprimido (~15 campos) |
| `_compress_heuristic(state, total_events)` | Compresión basada en reglas (arquetipo desde Big Five, resumen desde mental state) |
| `_parse_compressed_json(text)` | Parsea JSON comprimido |
| `_save_checkpoint(path, month, state, name)` | Guarda checkpoint para reanudación |
| `_load_checkpoint(path)` | Carga checkpoint |
| `_restore_soul_state(data)` | Restaura estado desde checkpoint |
| `_cleanup_checkpoints(path)` | Elimina checkpoints al completar |
| `_save_soul_json(path, data)` | Guarda `soul.json` final con estructura completa (versión, compressed, beliefs, genome, world_context) |
| `_add_event_to_history(id, month, event, impact)` | Agrega evento procesado a `life_events.json` |

### `accessor.py` — RuntimeSoulAccessor

Proporciona acceso en tiempo de ejecución al alma generada. Se inicializa durante `load_character()` si existe `soul.json`.

| Método / Propiedad | Rol |
|---------------------|-----|
| `is_active` (property) | True si el alma está activa |
| `initialize()` | Carga `soul.json` e inicializa ChromaDB |
| `get_soul_block()` | Genera bloque `[SOUL SYSTEM]` para el system prompt: identidad, arquetipo, filosofía, contexto del mundo, heridas, contradicciones, deseos, worldview, estilo de habla |
| `retrieve_context(query, top_k)` | Recupera recuerdos semánticamente relevantes con scoring compuesto y filtro de amnesia infantil + decaimiento exponencial |

**Scoring de recuperación**: `similitud*0.40 + importancia*0.25 + peso_emocional*0.15 + retención*0.20`. La retención decae exponencialmente con los años (eventos viejos se olvidan a menos que sean muy importantes).

## Dependencias Externas

| Módulo | Lo usa |
|--------|--------|
| `db.chroma_store.ChromaStore` | `soul_generator.py`, `accessor.py` |
| `psychology.PsychologySynthesizer` | `initialization.py` |
| `psychology.dna_traits_to_genome` | `initialization.py` |
| `types.Genome`, `types.BeliefEntry` | `soul_generator.py` |
| `types.CoreIdentity`, `types.EmotionalMemory`, `types.TurningPoint` | `synthesizer.py` (vía psychology) |
