# Psychology Engine v2 — Arquitectura Detallada

## Visión General

Sistema de psicología emergente runtime. Cada clase tiene su propio archivo y responsabilidad única. Se inicializa durante `load_character()` si existe `genome.json` (o se deriva desde PersonalityDNA).

```
psychology/
├── __init__.py            # Barrel: exporta las 5 clases + dna_traits_to_genome
├── emotional_dynamics.py  # EmotionalDynamics — sistema emocional multi-eje
├── synthesizer.py         # PsychologySynthesizer — síntesis de psicología
├── drift_detector.py      # DriftDetector — feedback loop comportamiento→personalidad
├── belief_manager.py      # BeliefManager — formación y refuerzo de creencias
├── runtime_manager.py     # RuntimeSoulManager — evolución del alma en runtime
└── dna_adapter.py         # dna_traits_to_genome — adaptador PersonalityDNA→Genome
```

## Archivos del Subpackage

### `__init__.py`
Barrel. Exporta las 5 clases y la función `dna_traits_to_genome`.

### `emotional_dynamics.py` — EmotionalDynamics

Sistema emocional basado en el modelo circumplex de Russell (valence + arousal).

| Método | Rol |
|--------|-----|
| `create_default()` | Crea `EmotionalState` neutral |
| `decay(state)` | Decaimiento temporal: las emociones tienden a neutral con el tiempo |
| `apply_trigger(state, target_v, target_a, emotion)` | Cambio emocional con inercia (no instantáneo) |
| `apply_text_trigger(state, text)` | Analiza texto con keywords y aplica trigger heurístico |

**Constantes**: `EMOTION_MAP` (~33 emociones mapeadas a coordenadas valence/arousal), `DECAY_RATE`, `INERTIA_MIN/MAX`.

### `synthesizer.py` — PsychologySynthesizer

Corazón del sistema. Sintetiza `PsychologyState` desde Genome + Soul events + runtime data.

| Método | Rol |
|--------|-----|
| `synthesize(genome, soul_events, beliefs, ...)` | Síntesis completa (al cargar personaje): Big Five + apego + worldview + necesidades + heridas + coping + conflictos + sesgos |
| `tick(current, genome, interactions, beliefs)` | Síntesis ligera runtime: deriva de worldview y neuroticism desde interacciones recientes |
| `process_event(current, event, genome, ...)` | Pipeline causal completo: filtro perceptual → turning point → psychology update → emoción → creencia → herida |
| `compile_persona(psychology, emotional, genome)` | Compila `PersonaState` (verbosidad, sarcasmo, calidez, estilo de habla, humor, etc.) |

**Pipeline de `process_event`:**
```
event → perception filter (CoreIdentity) → turning point detection
→ Big Five update → worldview update → emotional trigger
→ belief creation → wound creation → emotional memory
```

**Métodos internos**: `_genome_to_big_five()`, `_compute_attachment()`, `_compute_worldview()`, `_compute_needs()`, `_compute_active_wounds()`, `_compute_coping()`, `_compute_conflicts()`, `_compute_biases()`.

**Propiedades**: `emotion` (acceso a `EmotionalDynamics` interno), `belief_manager` (lazy `BeliefManager`).

### `drift_detector.py` — DriftDetector

Feedback loop: analiza respuestas del LLM y detecta desviaciones sostenidas entre comportamiento real y psicología esperada.

| Método | Rol |
|--------|-----|
| `feed(response, expected_persona)` | Analiza una respuesta: word count, warmth ratio, sarcasmo. Compara con persona esperada. Si la deriva es sostenida (> threshold en N muestras), retorna `DriftEntry` |
| `clear()` | Limpia buffer de respuestas |

**Ejes de deriva**: verbosity, sarcasm, warmth. Se requiere `min_samples` (default 5) consecutivas con drift > `drift_threshold` (default 0.15) para reportar.

### `belief_manager.py` — BeliefManager

Gestión simple de creencias: formación, refuerzo y decaimiento.

| Método | Rol |
|--------|-----|
| `form_belief(content, ...)` | Crea `BeliefEntry` |
| `reinforce(belief, amount)` | Aumenta `strength` |
| `weaken(belief, amount)` | Disminuye `strength`, marca como weakened si < 0.1 |
| `decay_all(beliefs, factor)` | Decaimiento general, remueve beliefs con strength < 0.05 |

### `runtime_manager.py` — RuntimeSoulManager

Orquestador runtime que conecta el alma (Soul System) con la psicología. Carga/guarda estado, sintetiza psicología, y evoluciona el alma durante la conversación.

| Método | Rol |
|--------|-----|
| `load()` | Carga soul events, beliefs, psychology, emotional state desde disco |
| `save()` | Persiste todo el estado a disco |
| `synthesize_psychology()` | Síntesis completa desde genome + soul events + beliefs |
| `synthesize_persona()` | Compila PersonaState con decaimiento emocional |
| `tick(interactions)` | Tick periódico: deriva ligera |
| `add_runtime_event(event)` | Agrega evento runtime con pipeline causal completo |
| `add_belief(content, ...)` | Forma nueva creencia |
| `apply_emotional_trigger(text)` | Trigger emocional desde texto del usuario |

**Bloques de prompt** (usados por `CharacterCompiler`):

| Método | Genera |
|--------|--------|
| `get_psychology_block()` | `[PSYCHOLOGY STATE]` — Big Five, apego, necesidades, heridas, conflictos |
| `get_persona_block()` | `[EXPRESSION STATE]` — estilo de habla, verbosidad, sarcasmo, calidez, humor |
| `get_timeline_block()` | `[TIMELINE]` — turning points con barras de intensidad, memorias emocionales |
| `get_why_block(context)` | `[RAZÓN DE SER]` — eventos formativos, creencias, contradicciones |

**Propiedades**: `psychology`, `persona`, `emotional`, `genome`, `is_loaded`, `active`.

### `dna_adapter.py` — dna_traits_to_genome

Función standalone para backward compatibility. Convierte `PersonalityDNA` (traits, flaws, motivations) a `Genome` (13 ejes innatos) cuando no existe `genome.json`.

Usa `_keyword_val()` para evaluar frecuencia de keywords en los textos del DNA y mapear a cada eje del Genome.

## Flujo de Inicialización

```
CharacterManager._init_psychology_engine()
├── Cargar genome.json o derivar desde PersonalityDNA
├── Cargar CoreIdentity desde disco o derivar desde Genome
├── Crear PsychologySynthesizer
├── Crear RuntimeSoulManager(genome, synthesizer)
├── manager.load()          → carga estado previo
├── manager.synthesize_psychology() → Psicología inicial
└── manager.synthesize_persona()    → Persona inicial
```

## Flujo Runtime (por turno de chat)

```
Por cada chat():
├── engine.chat._apply_emotional_trigger(prompt)
│   └── psych_mgr.apply_emotional_trigger(texto)
├── generate()
└── engine.chat._feed_response_to_drift_detector(response)
    └── DriftDetector.feed(response, persona_esperada)
        └── si hay drift → psych_mgr.tick()
```

## Dependencias

| Módulo | Importa desde |
|--------|---------------|
| `emotional_dynamics.py` | `types.EmotionalState` |
| `synthesizer.py` | `types.*`, `emotional_dynamics.EmotionalDynamics`, `belief_manager.BeliefManager` |
| `drift_detector.py` | `types.DriftEntry`, `types.PersonaState` |
| `belief_manager.py` | `types.BeliefEntry` |
| `runtime_manager.py` | `types.*`, `synthesizer.PsychologySynthesizer` |
| `dna_adapter.py` | `types.Genome` |
