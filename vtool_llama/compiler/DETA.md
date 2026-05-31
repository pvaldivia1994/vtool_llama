# CharacterCompiler — Arquitectura Detallada

## Visión General

El CharacterCompiler ensambla el system prompt y los bloques de estado del personaje combinando todas las capas en orden de peso cognitivo descendente. Resuelve conflictos con prioridad: **MODS > STATE > DNA**.

Para maximizar el reuso de **KV-Cache** en `llama.cpp`, el pipeline se divide en dos bloques:
1. **System Prompt Estático**: Compila el ADN base inmutable, reglas, estilo y lore. Se inyecta en el primer mensaje de sistema (índice 0) y calienta el KV-Cache de manera permanente.
2. **Estado Dinámico**: Compila el estado de relación, emociones, modificadores temporales y psicología. Se inyecta dinámicamente como un mensaje de sistema temporal antes del mensaje del usuario de cada turno.

```
compile_static_prompt()
  └── base_system_prompt (desde config.json)
  ├── 1. [SYSTEM CORE]              ← yaml_loader (system_core.yaml)
  ├── 2. [SECTION REFERENCE]        ← 12_definitions.md
  ├── 3. [ANTI-ASSISTANT]           ← yaml_loader (anti_assistant.yaml)
  ├── 4. [IDENTITY]                 ← 1_identity.md
  ├── 5. [TRAITS]                   ← 2_traits.md
  ├── 6. [MOTIVATIONS]              ← 3_motivations.md
  ├── 7. [FLAWS]                    ← 4_flaws.md
  ├── 8. [INNER CONFLICT]           ← 6_inner_conflict.md
  ├── 9. [EMOTIONAL TRIGGERS]       ← 7_emotional_triggers.md
  ├── 10. [SPEECH STYLE]            ← 5_speech.md
  ├── 11. [SPEECH PATTERNS]         ← 8_speech_patterns.md
  ├── 12. [WORLD]                   ← 15_scenario.md
  ├── 13. [CORE RULES]              ← 9_core_rules.md
  ├── 14. [HARD RULES]              ← 10_never_do.md
  ├── 15. [RESPONSE STYLE]          ← 16_response_style.md
  ├── 16. [ROLEPLAY MODE]           ← roleplay_mode.yaml
  ├── 17. [CONTEXT DEFINITIONS]     ← Orquestador context definitions
  ├── 18. [FEW SHOT EXAMPLES]       ← 14_few_shot.md
  ├── 19. [GUÍA DE TAGS]            ← tags.py TAG_DEFINITIONS (v13)
  └── Estáticos de Soul y creencias

compile_dynamic_prompt()
  └── 1. [STATE]                    ← emoción actual (v13, antes [CONTEXT][CHARACTER])
  └── 2. [STATE]                    ← relación si hay dinámicas (v13)
```

## Archivos del Subpackage

### `__init__.py`
Barrel. Exporta `CharacterCompiler`.

### `compiler.py` — Clase Base

Define `CharacterCompiler` y la API pública.

| Método | Rol |
|--------|-----|
| `compile_prompt(base, config)` | Une el bloque estático y dinámico (para compatibilidad hacia atrás) |
| `compile_static_prompt(base, config)` | Genera el prompt del sistema 100% estático |
| `compile_full_prompt(base, config)` | Alias explicito del prompt completo estático para auditoria/rebuild |
| `compile_compact_prompt(base, config)` | Genera una `[CHARACTER CAPSULE]` compacta para runtime |
| `compile_dynamic_prompt()` | Genera el bloque de estados y mods dinámicos |
| `get_layer_token_breakdown(base, count_fn, config)` | Diagnostico de tokens por capa: fase, tokens, chars, obligatoriedad y si puede moverse a retrieval |
| `_resolve_definitions()` | Carga `config/prompts/12_definitions.md` como guía de secciones |
| `_try_add(parts, block)` | Agrega bloque si no está vacío |

**Pipeline de Compilación**:
- `compile_static_prompt` compila la estructura inmutable del personaje (Placeholders de DNA + Reglas + Lore + Ejemplos).
- `compile_dynamic_prompt` compila las capas que cambian en cada turno (Emociones, Nivel de Confianza, Heridas, Mods de humor, etc.).

### `yaml_loader.py` — Carga de YAML

Métodos asignados a `CharacterCompiler` para cargar prompts desde archivos YAML del personaje.

| Método | Rol |
|--------|-----|
| `_load_yaml_prompt(filename)` | Busca `char_dir/filename` → `default/filename` → string vacío |

**Resolución de YAML**: busca primero en `char_dir/<filename>`, luego en `default/<filename>`.

**Archivos YAML por personaje:** `system_core.yaml`, `anti_assistant.yaml`, `roleplay_mode.yaml`

### `dna_layers.py` — Capas de Resolución

Incluye `_render_template()` que carga templates `.md` numerados desde `config/prompts/`. Cada template usa placeholders `#PLACEHOLDER`, items `#ITEMS`, y bloques condicionales `#HAS_X.../HAS_X`.

| Método | Genera el bloque | Template |
|--------|-----------------|----------|
| `_resolve_identity()` | `[IDENTITY]` | `1_identity.md` |
| `_resolve_traits()` | `[TRAITS]` | `2_traits.md` |
| `_resolve_motivations()` | `[MOTIVATIONS]` | `3_motivations.md` |
| `_resolve_flaws()` | `[FLAWS]` | `4_flaws.md` |
| `_resolve_speech()` | `[SPEECH STYLE]` | `5_speech.md` |
| `_resolve_few_shot_examples()` | `[FEW SHOT EXAMPLES]` | `14_few_shot.md` |
| `_resolve_scenario()` | `[WORLD]` | `15_scenario.md` |
| `_resolve_response_style()` | `[RESPONSE STYLE]` | `16_response_style.md` |
| `_resolve_inner_conflict()` | `[INNER CONFLICT]` | `6_inner_conflict.md` |
| `_resolve_emotional_triggers()` | `[EMOTIONAL TRIGGERS]` | `7_emotional_triggers.md` |
| `_resolve_speech_patterns()` | `[SPEECH PATTERNS]` | `8_speech_patterns.md` |
| `_resolve_core_rules()` | `[CORE RULES]` | `9_core_rules.md` |
| `_resolve_never_do()` | `[HARD RULES]` | `10_never_do.md` |
| `_resolve_state()` | `[EMOTIONAL STATE]` | `11_state.md` |
| `_resolve_relationship()` | `[RELATIONSHIP]` | `13_relationship.md` |
| `_resolve_roleplay_mode()` | `[ROLEPLAY MODE]` | `roleplay_mode.yaml` por personaje |
| `_resolve_dna()` | Compila todas las capas DNA | — |
| `_resolve_beliefs_contradictions()`, `_resolve_soul()`, `_resolve_psychology()`, `_resolve_persona()`, `_resolve_active_mods_description()`, `_resolve_memory()`, `_resolve_episode()` | Capas dinámicas (sin template) | — |
| `_resolve_persona()` | `[EXPRESSION STATE]` | No |

### Helpers de prompts internos

`config/prompts/helpers/` contiene prompts tecnicos reutilizables que no forman parte directa del system prompt estatico del personaje. Siguen el mismo criterio de versionado que los templates `.md`, pero se consumen desde modulos internos.

| Archivo | Consumidor | Rol |
|--------|------------|-----|
| `helpers/context_digest_system.md` | `engine/memory.py` | System prompt tecnico para comprimir contexto |
| `helpers/context_digest_user.md` | `engine/memory.py` | Template user con placeholder `#SOURCE` para la conversacion a comprimir |
| `helpers/character_capsule_system.md` | futuro compactador LLM | System prompt tecnico para generar capsulas compactas |
| `helpers/character_capsule_user.md` | futuro compactador LLM | Template user con `#SOURCE` y `#TARGET_TOKENS` |

Convencion recomendada: instrucciones tecnicas internas en ingles para mejorar obediencia del modelo, salida solicitada en espanol cuando el resultado vuelve al contexto conversacional del personaje.

`LAYER_POLICIES` define para cada capa si es obligatoria (`required`), candidata a moverse a retrieval (`movable`) y si entra en el prompt compacto (`compact`). Esta tabla alimenta el diagnostico de tokens y evita que la estrategia compacta diverja del reporte.

## Sistema de Resolución de Conflictos

Cuando un Mod activo apunta a una capa específica (`target_layer`), se sobreescribe el valor original:

```
_get_mod_override("traits") → reemplaza [RASGOS]
_get_mod_override("speech") → reemplaza [ESTILO DE HABLA]
_get_mod_override("emotion") → reemplaza [ESTADO EMOCIONAL]
```

Si hay múltiples mods para la misma capa, gana el de mayor `intensity`.

## Dependencias

| Archivo | Importa |
|---------|---------|
| `compiler.py` | `types.ConfigSchema` |
| `yaml_loader.py` | `compiler.CharacterCompiler` |
| `dna_layers.py` | `compiler.CharacterCompiler` |

## Uso

`CharacterCompiler` es instanciado por `CharacterManager.__init__` y usado por:
- `CharacterManager.build_system_prompt()` → `compile_prompt()`
- `CharacterManager.build_base_system_prompt()` → `compile_base_prompt()`
- `CharacterManager.compile_base_soul_prompt()` → `compile_base_soul_prompt()`
- `engine.base.VToolLlama._inject_personality_into_system_prompt()` vía `build_system_prompt()`
