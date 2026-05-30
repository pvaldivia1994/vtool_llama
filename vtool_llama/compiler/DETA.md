# CharacterCompiler — Arquitectura Detallada

## Visión General

El CharacterCompiler ensambla el system prompt final que recibe el LLM combinando todas las capas del personaje en orden de peso cognitivo descendente. El pipeline tiene ~27 capas y resuelve conflictos con prioridad: **MODS > STATE > DNA**.

```
compile_prompt()
  └── base_system_prompt (desde config.json)
  ├── 1. [SYSTEM CORE]              ← yaml_loader (system_core.yaml)
  ├── 2. [ANTI-ASSISTANT]           ← yaml_loader (anti_assistant.yaml)
  ├── 3. [IDENTITY]                 ← 1_identity.md (template)
  ├── 4. [TRAITS]                   ← 2_traits.md (template)
  ├── 5. [MOTIVATIONS]              ← 3_motivations.md (template)
  ├── 6. [FLAWS]                    ← 4_flaws.md (template)
  ├── 7. [SPEECH STYLE]             ← 5_speech.md (template)
  ├── 8. [INNER CONFLICT]           ← 6_inner_conflict.md (template)
  ├── 9. [EMOTIONAL TRIGGERS]       ← 7_emotional_triggers.md (template)
  ├── 10. [SPEECH PATTERNS]         ← 8_speech_patterns.md (template)
  ├── 11. [CORE RULES]              ← 9_core_rules.md (template)
  ├── 12. [HARD RULES]              ← 10_never_do.md (template)
  ├── 13. [EMOTIONAL STATE]         ← 11_state.md (template)
  ├── 14. [RELATIONSHIP]            ← 13_relationship.md (template)
  ├── 15. [WORLD]                   ← 15_scenario.md (template)
  ├── 16. [RESPONSE STYLE]          ← 16_response_style.md (template)
  ├── 17. [FEW SHOT EXAMPLES]       ← 14_few_shot.md (template)
  ├── 18. [ROLEPLAY MODE]           ← roleplay_mode.yaml (por personaje)
  ├── soul, beliefs, psych, persona, mods, memory, episode ← dinámicos (sin template)
  └── 19. [SECTION REFERENCE]       ← 12_definitions.md (guía de secciones)
```

## Archivos del Subpackage

### `__init__.py`
Barrel. Exporta `CharacterCompiler`.

### `compiler.py` — Clase Base

Define `CharacterCompiler` y la API pública. Contiene `_resolve_definitions()` que carga `12_definitions.md`.

| Método | Rol |
|--------|-----|
| `compile_prompt(base, config)` | Pipeline completo de capas (DNA templates + YAML + dinámicas) |
| `_resolve_definitions()` | Carga `config/prompts/12_definitions.md` como guía de secciones |
| `_try_add(parts, block)` | Agrega bloque si no está vacío |

**Pipeline** (`compile_prompt`):
1. YAML por personaje: `system_core.yaml`, `anti_assistant.yaml`
2. Templates `.md` numerados desde `config/prompts/`: identity, traits, motivations, flaws, speech, etc.
3. Capas dinámicas: soul, beliefs, psychology, persona, memory, episode, active_mods
4. YAML por personaje: `roleplay_mode.yaml`
5. `12_definitions.md` como guía final de secciones

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
