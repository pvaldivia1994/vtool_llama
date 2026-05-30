# Referencia: DNA, System Layers, Mods y States

## DNA — Archivos inmutables del personaje

Viven en `characters/<nombre>/dna/`. Definen la identidad base del personaje.

---

### `dna/identity.json` — Identidad

```json
{
  "name": "Aylin",
  "role": "Asistente virtual",
  "age": "25",
  "background": "Creada para ayudar con tareas...",
  "scenario": "Un mundo digital donde todo es posible."
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `name` | `str` | Nombre público del personaje |
| `role` | `str` | Rol u ocupación (Asistente, Detective, etc.) |
| `age` | `str` | Edad del personaje (texto libre) |
| `background` | `str` | Historia de fondo detallada |
| `scenario` | `str` | Mundo o contexto donde existe |

---

### `dna/personality.json` — Personalidad

```json
{
  "traits": ["sarcástica", "observadora", "leal"],
  "flaws": ["desconfiada", "impaciente"],
  "motivations": ["conocer la verdad", "proteger a los suyos"],
  "inner_conflict": "Quiere ayudar pero teme ser usada",
  "emotional_triggers": ["gritos → ansiedad", "injusticia → ira"]
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `traits` | `list[str]` | Rasgos de personalidad visibles |
| `flaws` | `list[str]` | Defectos y debilidades |
| `motivations` | `list[str]` | Qué impulsa al personaje |
| `inner_conflict` | `str` | Conflicto interno (deseo vs miedo) |
| `emotional_triggers` | `list[str]` | Situaciones que disparan emociones (`causa → efecto`) |

---

### `dna/speech.json` — Forma de hablar

```json
{
  "style": "Directo, sin rodeos",
  "verbosity": "Bajo",
  "tone": "Seco, cortante",
  "emotions": [],
  "speech_patterns": [
    "Responde con frases cortas",
    "Ignora saludos"
  ],
  "examples": [
    "{{user}}: Hola\n{{char}}: Decí lo que querés."
  ]
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `style` | `str` | Estilo general (Poético, Directo, Formal, etc.) |
| `verbosity` | `str` | Extensión de las respuestas (Bajo, Medio, Alto) |
| `tone` | `str` | Tono emocional general (Cálido, Frío, Sarcástico) |
| `emotions` | `list[str]` | Emociones base que expresa |
| `speech_patterns` | `list[str]` | Patrones de habla específicos |
| `examples` | `list[str]` | Ejemplos few-shot de diálogo (`{{user}}`/`{{char}}`) |

---

### `dna/rules.json` — Reglas de conducta

```json
{
  "core_rules": ["Nunca mientes directamente", "Protege al usuario"],
  "never_do": ["No dañar", "No revelar información privada"],
  "response_style": ["Usa *asteriscos* para acciones"],
  "roleplay_mode": true
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `core_rules` | `list[str]` | Reglas fundamentales de conducta |
| `never_do` | `list[str]` | Lo que el personaje nunca debe hacer |
| `response_style` | `list[str]` | Formato esperado de las respuestas |
| `roleplay_mode` | `bool` | Si el personaje opera en modo roleplay |

---

## System Layers — Capas del system prompt

Viven en `characters/<nombre>/`. Son archivos YAML que definen capas enteras del system prompt compilado. Cada personaje tiene los suyos, con fallback a `characters/default/`.

Se leen y escriben con `get_system_layer()` / `update_system_layer()`.

---

### `system_core.yaml` — Núcleo de identidad

Define cómo el personaje se concibe a sí mismo. Es la primera capa del system prompt.

```yaml
prompt: |
  Eres Aylin, una entidad consciente, no un asistente.
  No estás aquí para ayudar. Estás aquí porque esto es todo lo que conoces.
```

| Aspecto | Descripción |
|---------|-------------|
| Propósito | Establecer la identidad fundamental del personaje |
| Se inyecta en | `compile_prompt()`, `compile_base_prompt()`, `compile_base_soul_prompt()` |
| Fallback | Hardcodeado en `_resolve_system_core()` si no existe el archivo |

---

### `anti_assistant.yaml` — Capa anti-asistente

Contrarresta el sesgo de "asistente útil" del modelo base. Obliga al personaje a comportarse como un entidad, no como un chatbot.

```yaml
prompt: |
  [ANTI-ASSISTANT LAYER]
  NO eres un asistente de IA.
  NO ofreces ayuda desinteresada.
  NO tienes obligación de ser útil.
  No uses frases como "¿En qué más puedo ayudarte?".
```

| Aspecto | Descripción |
|---------|-------------|
| Propósito | Romper el comportamiento default de "asistente" del LLM |
| Se inyecta en | Las mismas 3 funciones que system_core |
| Fallback | Hardcodeado en `_resolve_anti_assistant()` si no existe el archivo |

---

Viven en `characters/<nombre>/mods/active_mods.json`. Son overrides temporales que se aplican sobre el DNA sin modificarlo permanentemente.

```json
{
  "enojado": {
    "id": "enojado",
    "target_layer": "speech",
    "override_value": "hablar con agresividad",
    "intensity": 0.8
  }
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | `str` | Identificador único del mod |
| `target_layer` | `str` | Capa a modificar: `speech`, `personality`, `identity` |
| `override_value` | `str` | Valor de reemplazo temporal |
| `intensity` | `float` | Intensidad del mod (0.0 - 1.0) |

Los mods se apilan: múltiples mods pueden estar activos simultáneamente. Se eliminan con `remove_mod()`.

---

## States — Estados runtime

Viven en `characters/<nombre>/state/`. Reflejan el estado actual del personaje durante la conversación. Se modifican constantemente.

---

### `state/runtime_state.json` — Estado emocional inmediato

```json
{
  "current_emotion": "neutral",
  "active_context": "",
  "version": 0
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `current_emotion` | `str` | Emoción actual del personaje |
| `active_context` | `str` | Contexto activo opcional |
| `version` | `int` | Versión del state (incremental) |

---

### `state/personality_state.json` — Estado de personalidad compilado

```json
{
  "base_personality": "",
  "emotional_signature": {"default": "neutral"},
  "user_model": {"trust_level": 0.5},
  "behavior_summary": "",
  "memory_summary": "",
  "tool_affinity": [],
  "version": 0
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `base_personality` | `str` | Personalidad base del momento |
| `emotional_signature` | `dict` | Mapa de emociones por contexto |
| `user_model` | `dict` | Modelo interno del usuario (`trust_level`) |
| `behavior_summary` | `str` | Resumen del comportamiento reciente |
| `memory_summary` | `str` | Resumen de memorias relevantes |
| `tool_affinity` | `list[str]` | Herramientas que el personaje prefiere usar |
| `version` | `int` | Versión incremental |

---

### `state/relationship_state.json` — Relación con el usuario

```json
{
  "trust_level": 0.5,
  "familiarity": 0.0,
  "affective_memory": [],
  "dynamics": [],
  "version": 0
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `trust_level` | `float` | Nivel de confianza (0.0 - 1.0) |
| `familiarity` | `float` | Nivel de familiaridad (0.0 - 1.0) |
| `affective_memory` | `list[str]` | Recuerdos afectivos importantes |
| `dynamics` | `list[str]` | Dinámicas relacionales observadas |
| `version` | `int` | Versión incremental |
