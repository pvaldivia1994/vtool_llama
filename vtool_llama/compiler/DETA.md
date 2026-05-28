# CharacterCompiler — Arquitectura Detallada

## Visión General

El CharacterCompiler ensambla el system prompt final que recibe el LLM combinando todas las capas del personaje en orden de peso cognitivo descendente. El pipeline tiene ~27 capas y resuelve conflictos con prioridad: **MODS > STATE > DNA**.

```
compile_prompt()
  └── base_system_prompt (desde config.json)
  ├── 1. [SYSTEM CORE]            ← yaml_loader (system_core.yaml)
  ├── 2. [ANTI-ASSISTANT]         ← yaml_loader (anti_assistant_layer.yaml)
  ├── 3. [IDENTIDAD]              ← dna_layers._resolve_identity()
  ├── 4. [SOUL SYSTEM]            ← dna_layers._resolve_soul()
  ├── 5. [RASGOS]                 ← dna_layers._resolve_traits()  (mod override)
  ├── 6. [CREENCIAS Y CONTRADICCIONES] ← dna_layers._resolve_beliefs_contradictions()
  ├── 7. [EMOTIONAL TRIGGERS]     ← dna_layers._resolve_emotional_triggers()
  ├── 8. [MOTIVACIONES]           ← dna_layers._resolve_motivations()
  ├── 9. [CONFLICTO INTERNO]      ← dna_layers._resolve_inner_conflict()
  ├── 10. [ESTADO EMOCIONAL]      ← dna_layers._resolve_state()  (mod override)
  ├── 11. [RELACIÓN]              ← dna_layers._resolve_relationship()
  ├── 12. [ESTILO DE HABLA]       ← dna_layers._resolve_speech()  (mod override)
  ├── 13. [PATRONES DE HABLA]     ← dna_layers._resolve_speech_patterns()
  ├── 14-15. [CORE/HARD RULES]    ← constantes + dna_layers
  ├── 16-26. capas complementarias ← dna_layers (mods, memoria, episodios, psicología, persona, flaws, roleplay)
  └── 27. [MODO ROLEPLAY]         ← dna_layers._resolve_roleplay_mode()
```

## Archivos del Subpackage

### `__init__.py`
Barrel. Exporta `CharacterCompiler`.

### `compiler.py` — Clase Base

Define `CharacterCompiler` y la API pública. Contiene las constantes `CORE_RULES_BLOCK` y `NEVER_DO_BLOCK`.

| Método | Rol |
|--------|-----|
| `compile_prompt(base, config)` | Pipeline completo de 27 capas |
| `compile_base_prompt(base, config)` | Solo SYSTEM CORE + ANTI-ASSISTANT + DNA (para KV Cache Base) |
| `compile_base_soul_prompt(base, config)` | Base + Soul (para KV Cache Base Soul) |
| `_try_add(parts, block)` | Agrega bloque si no está vacío |
| `_get_soul_data()` | Retorna `_soul_data` del SoulAccessor si está activo |

**Pipeline** (`compile_prompt`):
1. Capas fundacionales (YAML): SYSTEM CORE + ANTI-ASSISTANT
2. DNA: identidad, alma, rasgos, creencias, triggers, motivaciones, conflicto
3. Estado runtime: emoción, relación, habla, patrones
4. Reglas (CORE + NEVER DO + personalizadas)
5. Capas complementarias: estilo, escenario, few-shot, mods, memoria, episodios, psicología, persona, flaws, roleplay

### `yaml_loader.py` — Carga de YAML

Métodos asignados a `CharacterCompiler` para cargar prompts desde archivos YAML del personaje.

| Método | Rol |
|--------|-----|
| `_load_yaml_prompt(filename)` | Busca `char_dir/filename` → `default/filename` → string vacío |
| `_resolve_system_core()` | `system_core.yaml` o fallback hardcodeado (~50 LOC) |
| `_resolve_anti_assistant()` | `anti_assistant_layer.yaml` o fallback hardcodeado (~70 LOC) |

**Resolución de YAML**: busca primero en `char_dir/<filename>`, luego en `default/<filename>`. Si no existe ningún YAML, usa el bloque hardcodeado.

### `dna_layers.py` — Capas de Resolución

Todos los métodos `_resolve_*` que generan cada bloque del prompt. ~22 métodos cortos (5-20 LOC cada uno).

| Método | Genera el bloque | Soporta mod override |
|--------|-----------------|---------------------|
| `_get_mod_override(target)` | Busca mod activo para una capa | — |
| `_resolve_identity()` | `[IDENTIDAD]` | No |
| `_resolve_traits()` | `[RASGOS]` | **Sí** (traits) |
| `_resolve_motivations()` | `[MOTIVACIONES]` | No |
| `_resolve_flaws()` | `[DEFECTOS]` | No |
| `_resolve_speech()` | `[ESTILO DE HABLA]` | **Sí** (speech) |
| `_resolve_few_shot_examples()` | `[FEW SHOT EXAMPLES]` | No |
| `_resolve_scenario()` | `[MUNDO / ESCENARIO]` | No |
| `_resolve_response_style()` | `[ESTILO DE RESPUESTA]` | No |
| `_resolve_inner_conflict()` | `[CONFLICTO INTERNO]` | No |
| `_resolve_emotional_triggers()` | `[EMOTIONAL TRIGGERS]` | No |
| `_resolve_speech_patterns()` | `[PATRONES DE HABLA]` | No |
| `_resolve_roleplay_mode()` | `[MODO ROLEPLAY]` | No |
| `_resolve_dna()` | Compila todas las capas DNA para KV Cache | No |
| `_resolve_core_rules()` | Reglas adicionales del `rules.json` | No |
| `_resolve_never_do()` | Restricciones del `rules.json` | No |
| `_resolve_beliefs_contradictions()` | `[CREENCIAS Y CONTRADICCIONES]` desde alma | No |
| `_resolve_soul()` | `[SOUL SYSTEM]` bloque psicológico | No |
| `_resolve_state()` | `[ESTADO EMOCIONAL]` | **Sí** (emotion) |
| `_resolve_relationship()` | `[RELACIÓN CON EL USUARIO]` | No |
| `_resolve_active_mods_description()` | `[MODIFICADORES ACTIVOS]` | No |
| `_resolve_memory()` | `[MEMORIA RELEVANTE]` | No |
| `_resolve_episode()` | `[MEMORIA EPISÓDICA]` | No |
| `_resolve_psychology()` | `[PSYCHOLOGY STATE]` | No |
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
