# Types — Arquitectura Detallada

## Visión General

Centraliza todas las dataclasses de la librería para evitar importaciones circulares. Divididas en 3 archivos por dominio. El `__init__.py` re-exporta todo para backward compatibilidad total (`from vtool_llama.types import Xxx`).

```
types/
├── __init__.py      # Barrel: re-exporta los 24 tipos desde los 3 submódulos
├── core.py          # Tipos base del sistema
├── character.py     # Tipos del Character System
└── psychology.py    # Tipos de Psychology Engine v2 y Soul System
```

## Archivos del Subpackage

### `__init__.py`
Barrel. Importa y re-exporta los 24 tipos desde los 3 submódulos. No define nada propio.

### `core.py` — Tipos Base

| Tipo | Campos clave | Uso |
|------|-------------|-----|
| `Message` | `role`, `content`, `tool_calls`, `tool_call_id` | Historial de chat en formato OpenAI |
| `ModelInfo` | `model_name`, `context_size`, `gpu_layers`, `estimated_vram_gb`, `loaded` | Metadatos del modelo GGUF cargado |
| `GenerationStats` | `prompt_tokens`, `completion_tokens`, `tokens_per_second`, `duration_ms` | Estadísticas de cada inferencia |
| `ConfigSchema` | ~35 campos: `n_ctx`, `temperature`, `gpu_layers`, `history_limit`, `disable_thinking`, `semantic_memory_enabled`, `inject_dynamic_state`, `expand_n_ctx_for_core`, `user_tag`, etc. | Esquema del `config.json` |

### `character.py` — Tipos del Character System

**DNA (Inmutable):**

| Tipo | Campos | Persiste en |
|------|--------|-------------|
| `IdentityDNA` | `name`, `role`, `age`, `background`, `scenario` | `dna/identity.json` |
| `PersonalityDNA` | `traits`, `flaws`, `motivations`, `inner_conflict`, `emotional_triggers` | `dna/personality.json` |
| `SpeechDNA` | `style`, `verbosity`, `tone`, `emotions`, `speech_patterns`, `examples` | `dna/speech.json` |
| `RulesDNA` | `core_rules`, `never_do`, `response_style`, `roleplay_mode` | `dna/rules.json` |

**Memoria:**

| Tipo | Campos | Persiste en |
|------|--------|-------------|
| `MemoryEntry` | `id`, `content`, `priority`, `always_include`, `tags` | `_memory/long_term.json` |
| `EpisodeSnapshot` | `episode_id`, `timestamp`, `summary`, `messages` | `_memory/episodes/episode_NNN.json` |

**Estado Runtime:**

| Tipo | Campos | Persiste en |
|------|--------|-------------|
| `RuntimeState` | `current_emotion`, `active_context`, `version` | `state/runtime_state.json` |
| `RelationshipState` | `trust_level`, `familiarity`, `affective_memory`, `dynamics` | `state/relationship_state.json` |
| `PersonalityState` | `base_personality`, `emotional_signature`, `user_model`, `behavior_summary` | `state/personality_state.json` |

**Mods, Load Result & Chat Types:**

| Tipo | Campos | Persiste en |
|------|--------|-------------|
| `CharacterMod` | `id`, `target_layer`, `override_value`, `intensity` | `mods/active_mods.json` |
| `CharacterLoadResult` | `success`, `character_name`, `soul_active`, `psychology_active`, `logs`, `error` | No persiste — retorno de `load_character()` |
| `ChatMessage` | `id`, `conversation_id`, `branch_id`, `message_index`, `role`, `content`, `status` | SQLite `messages` |
| `ConversationSummary` | `id`, `start_message_id`, `end_message_id`, `summary`, `reason`, `embedding_id` | SQLite `summaries` (episodios, escenas, contexto) |
| `ContextEntry` | `id`, `ctx_type`, `content`, `tag`, `order`, `created_at` | SQLite `summaries` con `reason='ctx_{type}'` |
| `PromptSection` | `type`, `priority`, `tokens`, `messages` | No persiste — usado por ContextBuilder |
| `Branch` | `id`, `parent_branch_id`, `created_from_message_id`, `label` | SQLite `branches` |
| `Conversation` | `id`, `character_name`, `active_branch_id`, `active_leaf_message_id` | SQLite `conversations` |

### `psychology.py` — Tipos de Psicología y Soul

**Genética e Identidad Profunda:**

| Tipo | Campos | Descripción |
|------|--------|-------------|
| `Genome` | 13 ejes: `sociability`, `empathy`, `risk_aversion`, ... | Temperamento innato (0.0-1.0). NO cambia con la vida |
| `CoreIdentity` | `core_fears`, `core_desires`, `self_narrative`, `interpretation_biases`, `self_beliefs`, ... | Filtro perceptual: cómo INTERPRETA las experiencias |

`CoreIdentity` incluye métodos:
- `to_prompt_block()` → bloque `[CORE IDENTITY]` para el prompt
- `derive_contradictions()` → conflictos internos desde deseos + miedos
- `interpret_event(type, desc, importance)` → pipeline de filtro perceptual

**Eventos y Memorias del Alma:**

| Tipo | Campos | Descripción |
|------|--------|-------------|
| `TurningPoint` | `age`, `event`, `intensity`, `positive`, `meaning_assigned` | Evento que redefine la identidad |
| `EmotionalMemory` | `original_event`, `remembered_version`, `distortion_level` | Recuerdo con distorsión temporal |
| `SoulEvent` | `month`, `event_type`, `importance`, `psychological_impact` | Evento de vida con impacto psicológico numérico |
| `BeliefEntry` | `content`, `strength`, `category`, `formed_at_month` | Creencia aprendida de una experiencia |

**Psicología Runtime:**

| Tipo | Campos | Descripción |
|------|--------|-------------|
| `PsychologyState` | `current_big_five`, `attachment_style`, `needs`, `active_wounds`, `worldview` | Estado psicológico EMERGENTE sintetizado periódicamente |
| `EmotionalState` | `valence`, `arousal`, `dominant_emotion`, `emotional_inertia` | Sistema multi-eje (circumplex de Russell) |
| `PersonaState` | `speech_style`, `verbosity`, `sarcasm_tendency`, `warmth`, `defensiveness`, `humor_style` | Capa de expresión: cómo se manifiesta AHORA |
| `DriftEntry` | `axis`, `old_value`, `new_value`, `reason` | Registro de cambio psicológico detectado |

## Dependencias

Los tipos no tienen dependencias entre sí dentro del subpackage. Son importados por absolutamente todos los demás módulos de la librería.
