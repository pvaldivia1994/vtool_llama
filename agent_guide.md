# Manual de Integración de `vtool_llama` para Agentes de IA

Este documento sirve como especificación técnica y guía de referencia ("skill") para que cualquier Agente de IA pueda consumir e integrar la librería `vtool_llama` (v0.3.0) de forma autónoma en proyectos Python.

---

## 1. Descripción de la Herramienta

`vtool_llama` es un framework modular de IA conversacional local optimizado para Windows. En su versión **0.3.0** incorpora una **arquitectura psicológica completa** de 4 capas: **Genome → Soul → Psychology → Persona → Prompt**, lo que la convierte en un framework capaz de generar personajes con personalidad **emergente** (no impuesta), con vida simulada, psicología sintetizada, sistema emocional, capa de expresión dinámica y validación estricta de ejecución de herramientas. Todo bajo un motor Llama-cpp (GGUF).

---

## 2. Estructura del Proyecto

```
vtool_llama/
├── __init__.py                # Exporta la API pública
├── engine.py                  # VToolLlama (orquestador principal)
├── character_manager.py       # Capas del Character OS + prompt cache
├── character_compiler.py      # Compilador de prompts (9 capas)
├── chat_memory.py             # Historial de conversación (OpenAI format)
├── config_manager.py          # Carga/validación de config.json
├── exceptions.py              # Jerarquía de excepciones
├── logger_manager.py          # Logging a archivo + debug en consola
├── model_manager.py           # Inferencia llama.cpp + KV Cache
├── slash_commands.py          # Sistema de comandos prefijados con /
├── stats_manager.py           # Estadísticas de rendimiento
├── tokenizer_utils.py         # Tokenización y estimación de contexto
├── types.py                   # Dataclasses (DNA, Genome, Soul, Psychology, Persona, etc.)
├── soul_generator.py          # Soul System: vida simulada mes a mes
├── psychology_engine.py       # Psychology Engine v2: síntesis runtime, emociones, persona, drift
│
├── tools/                     # Sistema de herramientas internas
│   ├── __init__.py            # Exporta la API de tools
│   ├── definitions.py         # INTERNAL_TOOLS, TOOL_USAGE_POLICY, SCENE_SYSTEM_COMMAND
│   ├── parser.py              # TEXT_TOOL_RE, parse, strip, execute
│   ├── manager.py             # ToolExecutionManager (razoning loop, coercion)
│   └── stream_processor.py    # StreamPostProcessor (interceptor streaming)
│
├── config/config.json         # Configuración de la librería
├── personajes/                # Perfiles de personajes
│   ├── default/
│   ├── coder/
│   └── roleplay/
└── examples/                  # Scripts de ejemplo
    ├── console_chat.py            # Consola interactiva completa
    ├── example_ai_builder.py      # Generación de personajes con IA
    ├── example_builder.py         # Creación manual de personajes
    ├── example_elara.py           # Uso avanzado (context manager, episodios)
    ├── example_soul_generator.py  # Soul + Psychology + Persona + /why + /timeline
    └── thinking_and_tools.py      # Thinking mode + Tool Calling
```

---

## 3. Arquitectura Psicológica (v0.3.0)

```
Genome (13 ejes de temperamento innato)
  → Core Identity (miedos, deseos, auto-narrativa, sesgos de interpretación)
    → Soul (vida simulada mes a mes con impactos psicológicos NUMÉRICOS)
      → Psychology (Big Five + apego + necesidades + heridas + worldview)
        → Persona (sarcasmo, calidez, verborrea, humor DERIVADOS de psych)
          → Prompt (9 capas compiladas para el LLM)
```

### Las 4 capas conceptuales

| Capa | Archivo | Persistencia | Descripción |
|------|---------|-------------|-------------|
| **Genome** | `genome.json` | Inmutable | 13 ejes de predisposición innata (sociabilidad, sensibilidad, impulsividad, etc.) |
| **Core Identity** | `psychology/core_identity.json` | Evoluciona con turning points | Filtro de interpretación: miedos, deseos, auto-narrativa, sesgos cognitivos |
| **Soul** | `soul/soul.json`, `soul/beliefs.json`, `memory/life_timeline/` (ChromaDB) | Generado offline, evoluciona runtime | Eventos de vida con `psychological_impact` numérico, creencias formadas, memorias emocionales con distorsión |
| **Psychology** | `psychology/current_state.json` | Sintetizado runtime | Big Five actual, estilo de apego, necesidades (Maslow), heridas activas, worldview |
| **Persona** | (en memoria, derivado) | Regenerado cada turno | speech_style, verbosity, sarcasm_tendency, warmth, defensiveness, humor |

---

## 4. API de la Clase Principal: `VToolLlama`

```python
from vtool_llama import VToolLlama
```

### Constructor: `VToolLlama(config_path=None, auto_load=True)`

- **`config_path`**: Ruta personalizada al `config.json`. Si es `None`, busca en `vtool_llama/config/config.json`.
- **`auto_load`**: Si es `True`, carga el modelo GGUF por defecto al instanciar.

### Context Manager

```python
with VToolLlama(auto_load=True) as llm:
    llm.load_character("roleplay")
    respuesta = llm.chat("Hola")
```

---

## 5. Catálogo de Métodos

### A. Soul System (v0.3.0)

| Método | Descripción |
|--------|-------------|
| `generate_character_soul(name, force_regenerate, seed, progress_callback, stop_flag) -> dict` | Genera vida simulada completa mes a mes. Usa LLM para eventos por etapa, con `psychological_impact` numérico. Guarda soul.json, beliefs.json, ChromaDB. Soporta checkpoints para reanudación. |
| `has_character_soul(name) -> bool` | Verifica si existe soul.json |
| `get_character_soul(name) -> dict \| None` | Obtiene datos del alma (incluye beliefs, genome) |

**Parámetros de `generate_character_soul`:**
- `force_regenerate`: si True, regenera aunque exista
- `seed`: opcional, para reproducibilidad
- `progress_callback(progress: 0-100, stage: str)`: callback de progreso
- `stop_flag() -> bool`: si retorna True, detiene y guarda checkpoint

### B. Pipeline de Compilación (9 capas)

El `CharacterCompiler` construye el System Prompt en este orden:

1. `base_prompt` (`config.system_prompt`)
2. `DNA`: identity, personality, speech, rules (con overrides de Mods)
3. `STATE`: runtime_state, personality_state
4. `RELATIONSHIP`: trust_level, familiarity, dynamics
5. `MODS`: modificadores activos (descripción)
6. `MEMORY`: long_term relevantes (priority >= 0.5)
7. `EPISODE`: resumen de última sesión
8. `SOUL`: núcleo psicológico comprimido (opcional, si existe soul.json)
9. **`PSYCHOLOGY + PERSONA`**: estado psicológico emergente + expresión actual (v0.3.0)

### C. Psychology Engine (nuevo en v0.3.0)

El sistema tiene 5 subsistemas runtime que operan automáticamente:

| Subsistema | Archivo | Función |
|------------|---------|---------|
| `PsychologySynthesizer` | `psychology_engine.py` | Sintetiza PsychologyState desde Genome + Soul events |
| `EmotionalDynamics` | `psychology_engine.py` | Sistema emocional multi-eje (valence/arousal) con decaimiento, inercia y triggers por texto |
| `PersonaCompiler` | (integrado en `PsychologySynthesizer`) | Deriva PersonaState desde Psychology + emoción actual |
| `DriftDetector` | `psychology_engine.py` | Feedback loop: analiza respuestas del LLM, detecta deriva sostenida |
| `RuntimeSoulManager` | `psychology_engine.py` | Evolución del alma en runtime: eventos, creencias, memorias emocionales |

#### Flujo runtime en `chat()`:

```python
# Por cada turno de conversación:
1. EmotionalDynamics.apply_text_trigger(prompt_usuario)
   → detecta palabras clave → ajusta valence/arousal

2. PersonaCompiler.compile(psychology, emotional, genome)
   → regenera speech_style, verbosity, sarcasm, warmth, etc.

3. CharacterCompiler.compile_prompt()
   → inyecta Psychology + Persona blocks en system prompt

4. DriftDetector.feed(response_text, expected_persona)
   → si detecta deriva sostenida → ajusta PsychologyState
```

### D. Gestión del Character OS (existente)

| Método | Descripción |
|--------|-------------|
| `list_characters() -> list[str]` | Carpetas válidas en `personajes/` con subcarpeta `dna/` |
| `load_character(name: str)` | Inicializa personaje + KV Cache + Psychology Engine |
| `create_character(name, identity, personality, speech, rules, memories)` | Crea estructura de directorios y JSONs del DNA |
| `generate_character_with_ai(name, prompt)` | Usa el LLM para generar DNA completo |
| `rebuild_personality_state()` | Reconstruye estado de personalidad vía LLM |

### E. Conversación y Chat

| Método | Descripción |
|--------|-------------|
| `chat(prompt, tools=None, **kwargs) -> str \| dict` | Envía prompt, retorna texto o dict de tool_calls |
| `stream_chat(prompt, tools=None, **kwargs) -> Generator` | Streaming token por token |
| `chat_with_thinking(prompt, **kwargs) -> tuple[str, str]` | Retorna `(thinking_content, final_answer)` |
| `stream_chat_with_thinking(prompt, **kwargs) -> Generator[tuple[str, str]]` | Streaming con tuplas `(tipo, token)` |
| `add_tool_message(content, tool_call_id)` | Agrega respuesta de herramienta al historial |

### F. Slash Commands (v0.3.0)

| Comando | Descripción |
|---------|-------------|
| `/mem <texto>` | Guarda memoria persistente (priority=1.0) |
| `/memories` | Lista todas las memorias |
| `/rel <trust> <familiarity>` | Actualiza Relationship Engine |
| `/mood <layer> <value> [intensity]` | Aplica CharacterMod temporal |
| `/rebuild` | Reconstruye estado de personalidad vía LLM |
| `/state` | Muestra estado actual (incluye soul_active) |
| `/save_episode` | Guarda snapshot episódico |
| `/episodes [load N \| delete N]` | Lista, carga o elimina episodios (gatilla rollback en ChromaDB) |
| `/scene_view` | Descripción inmersiva de escena |
| `/help` | Lista todos los comandos |

### G. Gestión de Modelos GGUF

| Método | Descripción |
|--------|-------------|
| `load_model(model_path=None)` | Carga modelo GGUF |
| `reload_model()` | Recarga el modelo actual |
| `unload_model()` | Descarga el modelo (libera VRAM) |
| `switch_model(model_path)` | Cambia a otro modelo |
| `get_model_info() -> dict` | Metadatos del modelo + info GPU |
| `list_available_models() -> list[dict]` | Escanea `models_directory` por .gguf |

### H. Memoria y Contexto

| Método | Descripción |
|--------|-------------|
| `reset_chat()` / `clear_memory()` | Limpia el historial de conversación activo (corto plazo). |
| `get_memory() -> list[dict]` | Obtiene el historial de mensajes de la sesión actual. |
| `save_episode() -> EpisodeSnapshot` | Guarda un snapshot episódico de la conversación con resumen del LLM. |
| `list_episodes() -> list[dict]` | Lista todos los hitos/episodios guardados en disco. |
| `load_episode(id: int)` | Carga un hito (rollback). Ejecuta automáticamente el **rollback cronológico** en la DB de ChromaDB (`chat_history`), eliminando recuerdos posteriores al hito para mantener coherencia de la línea temporal. |
| `delete_episode(id: int) -> bool` | Elimina la copia del hito en disco. |

---

## 6. Tipos y Dataclasses Exportados (v0.3.0)

### Capa Genética

| Tipo | Descripción |
|------|-------------|
| `Genome` | 13 ejes de temperamento innato (sociability, emotional_sensitivity, impulsivity, risk_aversion, empathy, curiosity, etc.) |

### Capa de Identidad

| Tipo | Descripción |
|------|-------------|
| `CoreIdentity` | Filtro perceptual: core_fears, core_desires, self_narrative, interpretation_biases, self_beliefs, memory_loss_start_age |
| `TurningPoint` | Evento que redefinió identidad: age, event, meaning_assigned, changed_traits, emotional_memory |
| `EmotionalMemory` | Recuerdo con distorsión: original_event, remembered_version, distortion_level, recall() |

### Capa de Alma

| Tipo | Descripción |
|------|-------------|
| `SoulEvent` | Evento de vida con psychological_impact numérico, belief_formed, reflection |
| `BeliefEntry` | Creencia aprendida: content, strength, category, source_event_id |

### Capa Psicológica

| Tipo | Descripción |
|------|-------------|
| `PsychologyState` | Estado emergente: current_big_five, attachment_style, needs, active_wounds, worldview, active_conflicts |
| `EmotionalState` | Sistema multi-eje: valence, arousal, dominant_emotion, secondary_emotions, emotional_inertia |
| `PersonaState` | Expresión actual: speech_style, verbosity, sarcasm_tendency, warmth, defensiveness, humor_style |
| `DriftEntry` | Registro de cambio psicológico detectado por feedback loop |

### Capas Existentes

| Tipo | Descripción |
|------|-------------|
| `IdentityDNA` | Nombre, rol, edad, background, escenario |
| `PersonalityDNA` | Traits, flaws, motivations |
| `SpeechDNA` | Estilo, tono, verbosidad, emociones, ejemplos |
| `RulesDNA` | Core rules, never_do, response_style, roleplay_mode |
| `ConfigSchema` | Esquema tipado del config.json |
| `MemoryEntry` | Memoria persistente (id, content, priority, tags) |
| `EpisodeSnapshot` | Snapshot episódico (id, timestamp, summary, messages) |
| `CharacterMod` | Modificador temporal (target_layer, override_value, intensity) |
| `RuntimeState` | Estado en tiempo real (emoción actual, versión) |
| `RelationshipState` | Confianza, familiaridad, memoria afectiva |
| `PersonalityState` | (legacy) Resumen dinámico del DNA + Memory |

---

## 7. Excepciones

| Excepción | Causa |
|-----------|-------|
| `VToolLlamaError` | Base de toda la jerarquía |
| `ModelNotFoundError` | Archivo GGUF no existe |
| `InvalidModelError` | No es un GGUF válido o está corrupto |
| `CUDAUnavailableError` | CUDA no detectado |
| `OOMError` | VRAM/RAM insuficiente |
| `EmptyPromptError` | Prompt vacío |
| `ConfigError` | `config.json` corrupto o faltan claves |
| `ContextOverflowError` | Contexto excedió `n_ctx` sin recuperación |
| `InferenceError` | Error durante inferencia |
| `ModelNotLoadedError` | Se llamó a `chat()` sin modelo cargado |

---

## 8. Gestores Internos

| Gestor | Acceso | Propósito |
|--------|--------|-----------|
| `CharacterManager` | `llm.state_manager` | Capas de personalidad, memoria, episodios. Contiene `_psychology_manager`, `_core_identity`, `_genome` |
| `SoulGenerator` | `llm._soul_generator` | Generación de alma (vida simulada) |
| `RuntimeSoulManager` | `character_manager._psychology_manager` | Síntesis runtime, emociones, persona, drift |
| `SlashCommandRegistry` | `llm.slash_commands` | Registro y ejecución de comandos `/` |
| `ChatMemory` | `llm._memory` | Historial de conversación |
| `ConfigManager` | `llm._config_manager` | Carga y validación de config |
| `ModelManager` | `llm._model_manager` | Inferencia llama.cpp |
| `StatsManager` | `llm._stats` | Estadísticas de rendimiento |
| `LoggerManager` | `llm._log_manager` | Logging y debug |

---

## 9. Ejemplos Rápidos de Uso

### Ejemplo 1: Generar alma para un personaje existente

```python
from vtool_llama import VToolLlama

llm = VToolLlama(auto_load=True)

# Crear personaje (si no existe)
llm.generate_character_with_ai(
    name="zara",
    prompt="Una arqueóloga cyberpunk..."
)

# Generar vida simulada (alma)
# Esto puede tomar MINUTOS O HORAS con LLM real
result = llm.generate_character_soul(
    "zara",
    seed=42,
    progress_callback=lambda p, s: print(f"\r[{p}%] {s}", end=""),
)
print(f"Eventos generados: {result['events_generated']}")

# Cargar personaje con alma + psicología + persona
llm.load_character("zara")

# El sistema emocional y de persona se activan automáticamente
respuesta = llm.chat("¿Qué opinas de los gobiernos?")
```

### Ejemplo 2: Ver perfil psicológico completo

```python
cm = llm.state_manager
psych_mgr = cm._psychology_manager

# Genome
print(cm._genome)

# Core Identity
print(cm._core_identity.to_prompt_block())

# Psychology (Big Five, apego, necesidades, heridas)
print(psych_mgr.get_psychology_block())

# Persona (estilo, sarcasmo, calidez, humor)
print(psych_mgr.get_persona_block())

# /why — explicación causal
print(psych_mgr.get_why_block())

# /timeline — línea de vida con turning points
print(psych_mgr.get_timeline_block())
```

### Ejemplo 3: Comandos interactivos

```python
# En cualquier sesión de chat:
# /psych    — perfil psicológico completo
# /why      — "por qué soy como soy"
# /timeline — línea de vida con turning points
# /persona  — capa de expresión actual
```

### Ejemplo 4: Tool Calling

```python
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "parameters": {"type": "object", "properties": {"loc": {"type": "string"}}, "required": ["loc"]}
    }
}]
result = llm.chat("¿Clima en Madrid?", tools=tools)
if isinstance(result, dict):
    print("Tool call detectada:", result["tool_calls"])
```

---

## 10. Arquitectura del Compiler (v0.3.0)

Pipeline completo de 9 capas:

1. `base_prompt` (`config.system_prompt`)
2. `DNA`: identity, personality, speech, rules (con overrides de Mods)
3. `STATE`: runtime_state, personality_state, relationship_state
4. `RELATIONSHIP`: trust_level, familiarity, dynamics, affective_memory
5. `MODS`: modificadores activos (descripción)
6. `MEMORY`: long_term con priority >= 0.5 o always_include=True
7. `EPISODE`: resumen de última sesión desde `episode_NNN.json`
8. `SOUL`: nucleo psicologico comprimido (si existe soul.json)
9. `PSYCHOLOGY + PERSONA`: estado psicológico emergente + expresión actual (v0.3.0)

Además, por cada turno de chat:
- `EmotionalDynamics.apply_text_trigger()` ajusta estado emocional
- `PersonaCompiler.compile()` regenera persona según psicología + emoción
- `DriftDetector.feed()` analiza respuesta y detecta deriva sostenida
- `RuntimeSoulManager.tick()` aplica deriva ligera a worldview y big five

**Regla de Oro:** Todo el estado vive en `vtool_llama/personajes/<nombre>/`. Los datos inmutables en `dna/` y `genome.json`. Los dinámicos en `memory/`, `state/`, `mods/`, `soul/` y `psychology/`. Los binarios del KV Cache en `memory/base.state` y `memory/personality_plus_memory.state`.

---

## 11. Configuración (`config.json`)

```json
{
  "debug": true,
  "models_directory": "C:/_IA/_llama_models",
  "default_model": "Qwen3-8B-Q4_K_M.gguf",
  "system_prompt": "Eres un asistente útil y natural.",
  "n_ctx": 4096,
  "n_batch": 512,
  "gpu_layers": -1,
  "threads": 8,
  "flash_attn": true,
  "temperature": 0.8,
  "top_p": 0.9,
  "top_k": 40,
  "repeat_penalty": 1.1,
  "max_tokens": 512,
  "short_memory_limit": 5,
  "chat_memory_retrieval_limit": 3,
  "history_limit": 40,
  "auto_trim_context": true,
  "context_reserve_tokens": 800,
  "enable_logging": true,
  "enable_console_debug": false,
  "auto_unload_model": false,
  "model_idle_timeout": 600,
  "seed": -1
}
```
