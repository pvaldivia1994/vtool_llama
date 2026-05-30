# vtool_llama

**Librería profesional de IA conversacional local para Windows.**

Motor modular, reutilizable y listo para producción que permite usar modelos GGUF locales (Llama, Qwen, Gemma, Mistral, DeepSeek, etc.) mediante `llama-cpp-python`.

## Filosofía

vtool_llama **no es una aplicación de consola**. Es una **librería/framework** diseñada para integrarse como dependencia dentro de proyectos Python mayores.

```
ProyectoPrincipal/
│
├── app_principal/
│
└── vtool_llama/          # pip install o copia local
```

## Requisitos

- **Python 3.11+**
- **Windows 10/11** con tarjeta gráfica NVIDIA (e.g. RTX 3050 con 8GB VRAM o superior)
- **NVIDIA CUDA Toolkit 12.1 o 12.4** instalado en el sistema (requerido para aceleración por GPU)
- **llama-cpp-python** compilado con soporte CUDA
- Un modelo GGUF compatible (Qwen, Llama, Mistral, DeepSeek, Gemma...)

## Instalación y Configuración de CUDA

### 1. Instalar el CUDA Toolkit de NVIDIA
1. Descarga el instalador oficial de **CUDA Toolkit** (versión recomendada **12.1** o **12.4**):
   * [Descargas de NVIDIA CUDA Toolkit Archive](https://developer.nvidia.com/cuda-downloads)
2. Selecciona **Windows** -> **x86_64** -> Versión de tu S.O. -> **exe (local)**.
3. Ejecuta el instalador y sigue las instrucciones en pantalla.
4. Para verificar que esté bien configurado en el sistema, abre una terminal y escribe:
   ```bash
   nvcc --version
   ```
   Debería mostrar la versión del compilador CUDA de NVIDIA.

### 2. Instalar dependencias de Python

```bash
# A. Instalar dependencias base
pip install -r requirements.txt

# B. Instalar llama-cpp-python con soporte para CUDA 12.1 (recomendado)
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121

# Alternativa: CPU-only (sin GPU)
# pip install llama-cpp-python
```

## Uso básico

```python
from vtool_llama import VToolLlama

# Inicializar (carga el modelo automáticamente)
llm = VToolLlama()

# Ver qué personajes existen
for c in llm.list_characters():
    print(f"{c['name']} — {c['role']} [Alma: {c['has_soul']}]")

# Cargar un personaje (activa Psychology Engine automáticamente)
llm.load_character("default")

# Chat simple (con psicología + persona activas)
respuesta = llm.chat("Hola, ¿cómo estás?")
print(respuesta)

# Streaming token por token
for token in llm.stream_chat("Explícame Python"):
    print(token, end="")
```

## Arquitectura

La librería está organizada en **10 subpackages** por dominio, cada uno con su propia documentación:

| Subpackage | Propósito | Documentación |
|-----------|-----------|---------------|
| `engine/` | Núcleo: VToolLlama, chat, streaming, configuración, logging, ContextBuilder | `engine/AGENT.md` |
| `model/` | ModelManager: carga, inferencia, GPU, KV Cache | `model/AGENT.md` |
| `soul/` | Soul System: generación de vida simulada | `soul/AGENT.md` |
| `psychology/` | Psychology Engine v2: psicología runtime emergente | `psychology/AGENT.md` |
| `character/` | CharacterManager: carga, persistencia, episodios | `character/AGENT.md` |
| `compiler/` | CharacterCompiler: ensamblado del system prompt | `compiler/AGENT.md` |
| `tools/` | Tool system: function calling, parseo, ejecución | `tools/AGENT.md` |
| `types/` | Dataclasses compartidas por dominio | `types/AGENT.md` |
| `db/` | ChatStore (SQLite event store) + ChromaDB wrapper + file I/O | `db/AGENT.md` |
| `utils/` | Utilidades: TokenCounter centralizado | `utils/AGENT.md` |

### Pipeline psicológico (v0.3.0)

```
Genome (13 ejes de temperamento innato)
  → Core Identity (miedos, deseos, auto-narrativa, sesgos de interpretación)
    → Soul (vida simulada con impactos psicológicos numéricos)
      → Psychology (Big Five + apego + necesidades + heridas + worldview)
        → Persona (sarcasmo, calidez, verborrea, humor — derivados, no fijos)
          → Prompt (27 capas compiladas para el LLM)
```

### Mecanismos runtime

- **Emotional Dynamics**: sistema multi-eje (valence/arousal) con decaimiento temporal, inercia emocional y triggers por texto del usuario
- **Persona Compiler**: cada turno, la expresión se recalcula desde psicología + emoción
- **Drift Detector**: analiza las respuestas reales del LLM y detecta deriva sostenida vs persona esperada
- **Interpretation Engine**: el mismo evento produce distinta reacción según CoreIdentity (internaliza vs externaliza culpa, catastrofiza o minimiza)
- **Memory Distortion**: los recuerdos se deforman con el tiempo (original ≠ versión recordada)

## API completa

### Chat

| Método | Descripción |
|--------|-------------|
| `chat(prompt, tools=None, **kwargs)` | Respuesta completa. Si prompt empieza con `/`, ejecuta slash command. Incluye trigger emocional + persona + drift post-respuesta. |
| `stream_chat(prompt, tools=None, **kwargs)` | Streaming token por token |
| `chat_with_thinking(prompt, **kwargs)` | Retorna tupla `(thinking, content)` |
| `stream_chat_with_thinking(prompt, **kwargs)` | Streaming de tuplas `(tipo, token)` |
| `add_tool_message(content, tool_call_id)` | Registra respuesta de herramienta externa |

### Soul System

| Método | Descripción |
|--------|-------------|
| `generate_character_soul(name, force_regenerate=False, seed=None, progress_callback=None, stop_flag=None) -> dict` | Genera vida simulada completa mes a mes. Usa LLM para eventos con `psychological_impact` numérico y `belief_formed`. Guarda soul.json, beliefs.json, ChromaDB. Soporta checkpoints y reanudación. |
| `has_character_soul(name) -> bool` | Verifica si existe soul.json |
| `get_character_soul(name) -> dict \| None` | Obtiene datos del alma (incluye beliefs, genome, compressed) |

### Character System

| Método | Descripción |
|--------|-------------|
| `list_characters()` | Lista personajes con nombre, rol, background y estado del alma |
| `load_character(name)` | Inicializa personaje + KV Cache + Psychology Engine + Core Identity |
| `create_character(...)` | Crea estructura de directorios y JSONs del DNA |
| `generate_character_with_ai(name, prompt)` | Usa el LLM para autogenerar el DNA completo |
| `rebuild_personality_state()` | Reconstruye estado de personalidad vía LLM |
| `add_memory(content, priority, always_include, tags)` | Agrega memoria persistente |
| `get_state_info()` | Retorna dict con estado actual (incluye `soul_active`, `soul_archetype`) |

### Memoria y Contexto

| Método | Descripción |
|--------|-------------|
| `clear_memory()` / `reset_chat()` | Limpia historial |
| `get_memory()` | Obtiene historial como lista de dicts |
| `export_memory_json(path=None)` | Exporta historial a JSON |
| `import_memory_json(str_or_path)` | Importa historial desde JSON |
| `set_system_prompt(prompt)` | Cambia system prompt en caliente |
| `trim_memory()` | Recorta contexto según presupuesto de tokens |
| `save_episode()` | Guarda snapshot episódico con resumen LLM |
| `list_episodes()` | Lista episodios guardados |
| `load_episode(id)` | Rollback a episodio. Ejecuta un **rollback cronológico** en la DB vectorial de chat (ChromaDB) eliminando los recuerdos posteriores al hito. |
| `delete_episode(id)` | Elimina snapshot |

### Modelo

| Método | Descripción |
|--------|-------------|
| `load_model(path=None)` | Carga modelo GGUF |
| `reload_model()` | Recarga el modelo actual |
| `unload_model()` | Descarga el modelo |
| `switch_model(path)` | Cambia a otro modelo |
| `get_model_info()` | Metadatos del modelo + info GPU |
| `list_available_models()` | Escanea `models_directory` |

### Configuración y Debug

| Método | Descripción |
|--------|-------------|
| `get_config()` | Retorna la configuración actual |
| `reload_config()` | Recarga config.json en caliente |
| `enable_debug()` / `disable_debug()` | Control de logs debug |

### Propiedades de Extensión

| Propiedad | Tipo | Descripción |
|-----------|------|-------------|
| `state_manager` | `CharacterManager` | Acceso a capas del personaje, psychology manager, core identity |
| `slash_commands` | `SlashCommandRegistry` | Registro de comandos `/` para extensión |

## Slash Commands

| Comando | Descripción |
|---------|-------------|
| `/mem <texto>` | Guarda memoria persistente |
| `/memories` | Lista todas las memorias |
| `/save_episode` | Guarda snapshot episódico |
| `/episodes [load N \| delete N]` | Lista, carga o elimina episodios |
| `/rel <trust> <familiarity>` | Actualiza Relationship Engine |
| `/mood <layer> <value> [intensity]` | Aplica CharacterMod temporal |
| `/rebuild` | Reconstruye estado de personalidad |
| `/state` | Muestra estado del agente (incluye `soul_active`) |
| `/scene_view` | Descripción inmersiva de escena |
| `/help` | Lista todos los comandos |

## Configuración (`config.json`)

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
  "seed": -1,
  "short_memory_limit": 5,
  "chat_memory_retrieval_limit": 3,
  "history_limit": 40,
  "auto_trim_context": true,
  "context_reserve_tokens": 800,
  "enable_logging": true,
  "enable_console_debug": false,
  "auto_unload_model": false,
  "model_idle_timeout": 600,
  "characters_directory": ""
}
```

## Estructura de archivos por personaje

```
characters/<nombre>/
├── genome.json                        ← 13 ejes de temperamento innato (opcional)
├── dna/
│   ├── identity.json
│   ├── personality.json
│   ├── speech.json
│   └── rules.json
├── soul/
│   ├── soul.json                      ← Núcleo psicológico comprimido + genome + beliefs
│   ├── beliefs.json                   ← Creencias formadas con strength
│   └── life_timeline/                 ← ChromaDB (embeddings semánticos)
├── psychology/
│   ├── current_state.json             ← PsychologyState sintetizado
│   ├── emotional_state.json           ← EmotionalState con valence/arousal
│   └── core_identity.json             ← CoreIdentity con fears, desires, self_narrative
├── memory/
│   ├── long_term.json
│   ├── chat_history/                  ← Historial de chat vectorial en ChromaDB (embeddings)
│   ├── episodes/
│   ├── base.state
│   ├── base_soul.state
│   └── personality_plus_memory.state
├── state/
│   ├── runtime_state.json
│   ├── personality_state.json
│   ├── relationship_state.json
│   └── state_meta.json
└── mods/
    └── active_mods.json
```

## Características Principales

- **Genome (13 ejes)**: temperamento innato como predisposición, no como rasgo final. Separación conceptual de lo genético vs lo adquirido.
- **Core Identity**: filtro de interpretación perceptual. Mismos eventos → distintas personas según miedos, deseos, auto-narrativa y sesgos cognitivos.
- **Soul System**: vida simulada mes a mes con eventos que tienen `psychological_impact` numérico. Guarda en ChromaDB con búsqueda semántica. Checkpoints para reanudación.
- **Psychology Synthesizer**: Big Five, apego, necesidades, heridas activas, worldview. Sintetizado desde Genome + Soul events.
- **Emotional Dynamics**: sistema multi-eje (valence/arousal) con decaimiento exponencial, inercia emocional y triggers por palabras clave del usuario.
- **Persona Compiler**: cada turno deriva speech_style, verbosity, sarcasm_tendency, warmth, defensiveness, humor desde psicología + emoción.
- **Drift Detector**: feedback loop que analiza respuestas reales del LLM y detecta deriva sostenida vs persona esperada. Ajusta PsychologyState automáticamente.
- **Turning Points**: eventos >0.8 de intensidad que redefinen auto-narrativa, creencias nucleares y agregan miedos. Con `meaning_assigned`.
- **Memory Distortion**: los recuerdos se deforman con el tiempo. `EmotionalMemory.recall()` devuelve versión distorsionada si pasaron >5 años.
- **Memory Loss Start**: el personaje puede tener un punto de inicio de memoria consciente (no recuerda infancia), aunque los eventos sigan afectando su psicología.
- **Interpretation Engine**: `CoreIdentity.interpret_event()` filtra eventos por sesgos (internalize_blame, catastrophize, minimize, etc.) → mismo evento, distinta persona.
- **Runtime Evolution**: el alma evoluciona durante la conversación. Nuevos eventos, creencias y heridas se agregan en runtime.
- **KV Cache Dual**: inferencia diferencial con ~0.2s de carga en caliente.
- **Thinking Mode**: soporte nativo para `reasoning_content` de DeepSeek-R1 y parseo de etiquetas `<think>`.
- **Tool Calling con Validación**: filtra alucinaciones de nombres automáticamente.
- **Arquitectura modular**: 9 subpackages con documentación interna (`AGENT.md` + `DETA.md`) para navegación y mantenimiento.

## Licencia

MIT
