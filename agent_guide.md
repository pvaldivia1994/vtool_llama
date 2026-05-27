# Manual de Integración de `vtool_llama` para Agentes de IA

Este documento sirve como especificación técnica y guía de referencia ("skill") para que cualquier Agente de IA pueda consumir e integrar la librería `vtool_llama` (v0.2.2) de forma autónoma en proyectos Python.

---

## 1. Descripción de la Herramienta

`vtool_llama` es una librería modular de IA conversacional local optimizada para Windows. En su versión **0.2.2** incorpora un **Character Operating System**, lo que la convierte en un framework capaz de soportar personalidad persistente a través del ADN de un personaje, un motor de relaciones, capas temporales (Mods), comandos de bajo nivel y validación estricta de ejecución de herramientas. Todo bajo un motor Llama-cpp (GGUF).

---

## 2. Estructura del Proyecto

```
vtool_llama/
├── __init__.py              # Exporta la API pública
├── engine.py                # VToolLlama (orquestador principal)
├── character_manager.py     # Capas del Character OS + prompt cache
├── character_compiler.py    # Compilador de prompts (MODS > STATE > DNA)
├── chat_memory.py           # Historial de conversación (OpenAI format)
├── config_manager.py        # Carga/validación de config.json
├── exceptions.py            # Jerarquía de excepciones
├── logger_manager.py        # Logging a archivo + debug en consola
├── model_manager.py         # Inferencia llama.cpp + KV Cache
├── slash_commands.py        # Sistema de comandos prefijados con /
├── stats_manager.py         # Estadísticas de rendimiento
├── tokenizer_utils.py       # Tokenización y estimación de contexto
├── types.py                 # Dataclasses (DNA, State, Mods, Config, etc.)
│
├── tools/                   # Sistema de herramientas internas
│   ├── __init__.py          # Exporta la API de tools
│   ├── definitions.py      # INTERNAL_TOOLS, TOOL_USAGE_POLICY, SCENE_SYSTEM_COMMAND
│   ├── parser.py           # TEXT_TOOL_RE, parse, strip, execute
│   ├── manager.py          # ToolExecutionManager (razoning loop, coercion)
│   └── stream_processor.py # StreamPostProcessor (interceptor streaming)
│
├── config/config.json       # Configuración de la librería
├── personajes/              # Perfiles de personajes
│   ├── default/
│   ├── coder/
│   └── roleplay/
└── examples/                # Scripts de ejemplo
    ├── console_chat.py          # Consola interactiva completa
    ├── example_ai_builder.py    # Generación de personajes con IA
    ├── example_builder.py       # Creación manual de personajes
    ├── example_elara.py         # Uso avanzado (context manager, episodios)
    └── thinking_and_tools.py    # Thinking mode + Tool Calling
```

---

## 3. API de la Clase Principal: `VToolLlama`

La interfaz pública principal se importa desde la raíz del paquete:
```python
from vtool_llama import VToolLlama
```

### Constructor: `VToolLlama(config_path=None, auto_load=True)`

* **`config_path`**: Ruta personalizada al `config.json`. Si es `None`, busca en `vtool_llama/config/config.json`.
* **`auto_load`**: Si es `True`, carga el modelo GGUF por defecto al instanciar. **No** carga un personaje automáticamente (usa `load_character()` después).

### Context Manager

`VToolLlama` soporta el protocolo de contexto de Python. Al salir del bloque, auto-guarda el episodio de conversación y descarga el modelo si está configurado:

```python
with VToolLlama(auto_load=True) as llm:
    llm.load_character("roleplay")
    respuesta = llm.chat("Hola")
```

---

## 4. Catálogo de Métodos y Sistemas Disponibles

### A. Gestión del Character OS y KV Cache Dual

El sistema separa la lógica del personaje en jerarquías: `DNA` (inmutable), `Memory` (persistente), `State` (dinámico), `Mods` (superposiciones).

| Método | Descripción |
|--------|-------------|
| `list_characters() -> list[str]` | Devuelve carpetas válidas en `personajes/` que tienen subcarpeta `dna/` |
| `load_character(name: str)` | Inicializa el personaje + KV Cache Dual con invalidación SHA-256 |
| `create_character(name, identity, personality, speech, rules, memories)` | Crea la estructura de directorios y archivos JSON del DNA |
| `generate_character_with_ai(name, prompt)` | Usa el LLM para generar el DNA completo desde un prompt descriptivo |
| `rebuild_personality_state()` | Ejecuta LLM interno para resumir historial y actualizar `relationship_state.json` |

#### KV Cache Dual (Differential Inference)

El sistema guarda dos snapshots del KV Cache:

1. **`base.state`**: Tensores del DNA puro (inmutable). Solo se regenera si el DNA cambia.
2. **`personality_plus_memory.state`**: DNA + memoria + estado. Se invalida por **hash SHA-256** del prompt compilado.

Si el hash no cambió, la carga es instantánea (~0.2s). Si cambió, solo se recalculan los tokens nuevos.

### B. Conversación y Chat

| Método | Descripción |
|--------|-------------|
| `chat(prompt, tools=None, **kwargs) -> str \| dict` | Envía prompt, retorna texto o `dict` de `tool_calls`. Si empieza con `/`, ejecuta slash command. |
| `stream_chat(prompt, tools=None, **kwargs) -> Generator` | Streaming token por token. Valida tool_calls en tiempo real. |
| `chat_with_thinking(prompt, **kwargs) -> tuple[str, str]` | Retorna `(thinking_content, final_answer)`. Parsea `reasoning_content` nativo y etiquetas `<think>`. |
| `stream_chat_with_thinking(prompt, **kwargs) -> Generator[tuple[str, str]]` | Streaming con tuplas `(tipo, token)` donde tipo es `'thinking'` o `'content'`. |

**Parámetros opcionales** de generación:
- `max_tokens`, `temperature`, `top_p`, `top_k`, `repeat_penalty`
- `tools`: lista de definiciones de herramientas (formato OpenAI)
- `tool_choice`: control de selección (`"auto"`, `"none"`, o nombre específico)

#### Auto-Tools: `store_long_term_memory`

El motor inyecta automáticamente una herramienta interna `store_long_term_memory` en cada llamada. Cuando el modelo decide usarla, la memoria se guarda en `long_term.json` sin intervención del usuario y el bucle de razonamiento continúa para generar la respuesta textual. Límite: 3 iteraciones para evitar loops infinitos.

### C. Sistema de Memoria y Estado

| Método | Descripción |
|--------|-------------|
| `add_memory(content, priority=0.5, always_include=False, tags=None) -> dict` | Agrega una memoria persistente a `long_term.json` |
| `clear_memory()` | Limpia el historial de conversación (preserva system prompt) |
| `reset_chat()` | Alias de `clear_memory()` |
| `get_memory() -> list[dict]` | Retorna el historial actual como lista de mensajes |
| `export_memory_json(path=None) -> str` | Exporta el historial a JSON (opcionalmente a archivo) |
| `import_memory_json(json_str_or_path)` | Importa un historial desde string JSON o archivo |
| `set_system_prompt(prompt)` | Cambia el system prompt en caliente |
| `trim_memory() -> int` | Recorta manualmente el historial según el presupuesto de tokens |
| `add_tool_message(content, tool_call_id)` | Agrega la respuesta de una herramienta externa al historial |

#### Memoria Episódica (Short-Term Versionada)

| Método | Descripción |
|--------|-------------|
| `save_episode() -> EpisodeSnapshot` | Extrae los últimos 5 mensajes, genera resumen con LLM y guarda `episode_NNN.json` |
| `list_episodes() -> list[dict]` | Lista todos los episodios guardados con metadatos |
| `load_episode(episode_id)` | Restaura el contexto de un episodio anterior (rollback) |
| `delete_episode(episode_id) -> bool` | Elimina un snapshot de episodio |

#### Acceso Interno al Character System

```python
# Acceso directo al CharacterManager (para config avanzada)
cm = llm.state_manager
cm.add_memory("texto", priority=1.0)

# Estado actual del agente
info = llm.get_state_info()
```

### D. Slash Commands

Se ejecutan enviándolos como prompt en `chat()` o `stream_chat()`. **No gastan tokens** y modifican el Character OS directamente.

| Comando | Descripción |
|---------|-------------|
| `/mem <texto>` | Guarda una memoria persistente (priority=1.0, always_include=True) |
| `/memories` | Lista todas las memorias con su ID, tags y pin |
| `/rel <trust> <familiarity>` | Actualiza el Relationship Engine (valores 0.0 a 1.0) |
| `/mood <layer> <value> [intensity]` | Aplica CharacterMod temporal. Ej: `/mood speech silencioso 1.5` |
| `/rebuild` | Reconstruye el estado de personalidad vía LLM interno |
| `/state` | Muestra el estado actual del agente en JSON |
| `/save_episode` | Genera resumen y guarda snapshot episódico |
| `/episodes [load N \| delete N]` | Lista, carga o elimina episodios |
| `/scene_view` | Fuerza una descripción inmersiva de escena en tercera persona |
| `/help` | Lista todos los comandos disponibles |

#### Slash Commands Personalizados

```python
@llm.slash_commands.command("git", description="Ejecuta un comando git")
def handle_git(args: str) -> str:
    return os.popen(f"git {args}").read()
```

### E. Gestión de Modelos GGUF

| Método | Descripción |
|--------|-------------|
| `load_model(model_path=None)` | Carga el modelo. Si es `None`, usa `default_model` del config |
| `reload_model()` | Recarga el modelo actual (útil tras cambiar config) |
| `unload_model()` | Descarga el modelo (libera VRAM) |
| `switch_model(model_path)` | Descarga el actual y carga otro |
| `get_model_info() -> dict` | Metadatos del modelo + info de hardware GPU (nvidia-smi) |
| `list_available_models() -> list[dict]` | Escanea `models_directory` y lista todos los `.gguf` |

### F. Configuración

| Método | Descripción |
|--------|-------------|
| `get_config() -> ConfigSchema` | Retorna la configuración actual |
| `reload_config()` | Recarga desde `config.json` en caliente |
| `enable_debug()` | Activa logs de debug en consola |
| `disable_debug()` | Desactiva logs de debug en consola |

### G. Manejo de Herramientas (Tool Calling)

El motor soporta tools en formato OpenAI. Flujo típico:

```python
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Obtiene el clima",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string"}
            },
            "required": ["location"]
        }
    }
}]

# 1. El modelo decide llamar a la herramienta
result = llm.chat("¿Clima en Tokio?", tools=tools)
if isinstance(result, dict) and "tool_calls" in result:
    tc = result["tool_calls"][0]
    # 2. Ejecutar la función local
    output = get_weather(**json.loads(tc["function"]["arguments"]))
    # 3. Registrar la respuesta
    llm.add_tool_message(output, tc["id"])
    # 4. El modelo genera la respuesta final
    final = llm.chat("Redacta la respuesta final.")
```

**Validación anti-alucinación**: El motor descarta automáticamente cualquier `tool_call` cuyo nombre no exista en la definición de tools del usuario.

---

## 5. Tipos y Dataclasses Exportados

| Tipo | Descripción |
|------|-------------|
| `ConfigSchema` | Esquema tipado del `config.json` |
| `Message` | Mensaje individual del historial (role, content, tool_calls) |
| `ModelInfo` | Metadatos del modelo cargado |
| `GenerationStats` | Estadísticas de una inferencia |
| `IdentityDNA` | Nombre, rol, edad, background, escenario |
| `PersonalityDNA` | Traits, flaws, motivations |
| `SpeechDNA` | Estilo, tono, verbosidad, emociones, ejemplos |
| `RulesDNA` | Core rules, never_do, response_style, roleplay_mode |
| `MemoryEntry` | Memoria persistente (id, content, priority, tags) |
| `EpisodeSnapshot` | Snapshot episódico (id, timestamp, summary, messages) |
| `RuntimeState` | Estado en tiempo real (emoción actual, versión) |
| `RelationshipState` | Confianza, familiaridad, memoria afectiva |
| `PersonalityState` | Resumen dinámico del DNA + Memory |
| `CharacterMod` | Modificador temporal (target_layer, override_value, intensity) |

## 6. Excepciones

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

## 7. Gestores Internos (para integración avanzada)

| Gestor | Acceso | Propósito |
|--------|--------|-----------|
| `CharacterManager` | `llm.state_manager` | Capas de personalidad, memoria, episodios |
| `SlashCommandRegistry` | `llm.slash_commands` | Registro y ejecución de comandos `/` |
| `ChatMemory` | `llm._memory` | Historial de conversación |
| `ConfigManager` | `llm._config_manager` | Carga y validación de config |
| `ModelManager` | `llm._model_manager` | Inferencia llama.cpp |
| `StatsManager` | `llm._stats` | Estadísticas de rendimiento |
| `LoggerManager` | `llm._log_manager` | Logging y debug |

---

## 8. Ejemplos Rápidos de Uso

### Ejemplo 1: Iniciar y Manipular un Personaje
```python
from vtool_llama import VToolLlama
llm = VToolLlama()
llm.load_character("roleplay")

# Modificar el motor de relaciones
print(llm.chat("/rel 0.9 0.8"))

# Modificar una capa del ADN (Mod temporal)
llm.chat("/mood traits aterrorizado")

# Ahora el system prompt compila el personaje aterrorizado y de alta confianza
print(llm.chat("¿Qué fue ese ruido?"))
```

### Ejemplo 2: Uso con Context Manager y Episodios
```python
with VToolLlama(auto_load=True) as llm:
    llm.load_character("roleplay")
    
    # /save_episode al salir del bloque se ejecuta automáticamente
    print(llm.chat("Hola, ¿cómo estás?"))
```

### Ejemplo 3: Thinking Mode con DeepSeek-R1
```python
llm = VToolLlama()
thinking, response = llm.chat_with_thinking("Explica la gravedad en 2 líneas")
print(f"Pensamiento: {thinking}")
print(f"Respuesta: {response}")
```

### Ejemplo 4: Tool Calling Completo
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

## 9. Arquitectura del Compiler (v0.2.2)

Al llamar al modelo, el `CharacterCompiler` construye el System Prompt resolviendo conflictos bajo la regla **MODS > STATE > DNA**:

1. `base_prompt` (`config.system_prompt`)
2. `DNA`: Extrae `identity.json`, `rules.json`, `personality.json`, `speech.json`.
3. `STATE`: Inyecta `runtime_state.json` y `relationship_state.json` (Confianza: 0.9, Familiaridad: 0.5).
4. `MODS`: Reemplaza cualquier bloque del DNA si hay un Mod activo.
5. `MEMORY`: Memorias extraídas de `long_term.json` con priority >= 0.5 o always_include=True.
6. `EPISODE`: Resumen de la sesión anterior desde el último `episode_NNN.json`.
7. `SHORT MEMORY`: Contexto inmediato en RAM (últimos N mensajes sin resumir).

**Regla de Oro:** Todo el estado vive en `vtool_llama/personajes/<nombre>/`. Los datos inmutables en `dna/`, los dinámicos en `memory/`, `state/` y `mods/`. Los binarios del KV Cache en `memory/base.state` y `memory/personality_plus_memory.state`.

## 10. Configuración (`config.json`)

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
