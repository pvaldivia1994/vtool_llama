# vtool_llama

**Librería profesional de IA conversacional local para Windows.**

Motor modular, reutilizable y listo para producción que permite usar modelos GGUF locales (Llama, Qwen, Gemma, Mistral, DeepSeek, etc.) mediante `llama-cpp-python`.

En su versión **0.2.2**, `vtool_llama` introduce un **Character Operating System**, convirtiéndose en un framework avanzado para crear compañeros virtuales y agentes autónomos con memoria híbrida, personalidad modular por capas (DNA, Memory, State, Mods), motor de relaciones y comandos de bajo nivel.

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

Para lograr respuestas rápidas utilizando la GPU de tu tarjeta NVIDIA, sigue estos pasos:

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
Instala las dependencias base de Python y luego el motor `llama-cpp-python` enlazado con la versión de CUDA correspondiente:

```bash
# A. Instalar dependencias base
pip install -r requirements.txt

# B. Instalar llama-cpp-python con soporte para CUDA 12.1 (recomendado)
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121

# Alternativa: CPU-only (sin GPU)
# pip install llama-cpp-python
```

## Uso básico (Character OS)

```python
from vtool_llama import VToolLlama

# Inicializar (carga el modelo automáticamente, pero no asume un personaje)
llm = VToolLlama()

# Ver qué personajes existen en vtool_llama/personajes/
print("Personajes:", llm.list_characters())

# Cargar un personaje específico y sus memorias
llm.load_character("default")

# Chat simple
respuesta = llm.chat("Hola, ¿cómo estás?")
print(respuesta)

# Streaming token por token
for token in llm.stream_chat("Explícame Python"):
    print(token, end="")

# Uso de Slash Commands (bypassean el LLM y alteran el motor directo)
llm.chat("/rel 0.9 0.8") # Aumenta confianza/familiaridad
llm.chat("/mood speech enojado y cortante") # Mod temporal al habla

# Uso con context manager (auto-guarda episodio al salir)
with VToolLlama(auto_load=True) as llm:
    llm.load_character("default")
    print(llm.chat("Hola"))
```

## API completa (v0.2.2)

### Chat
| Método | Descripción |
|--------|-------------|
| `chat(prompt, tools=None, **kwargs)` | Respuesta completa. Si prompt empieza con `/`, ejecuta slash command |
| `stream_chat(prompt, tools=None, **kwargs)` | Streaming token por token. Valida tool_calls automáticamente. |
| `chat_with_thinking(prompt, **kwargs)` | Retorna tupla `(thinking, content)`. Parsea `reasoning_content` y `<think>` tags |
| `stream_chat_with_thinking(prompt, **kwargs)` | Streaming de tuplas `(tipo, token)` para razonamiento incremental |
| `add_tool_message(content, tool_call_id)` | Registra respuesta de herramienta externa en el historial |

### Character System
| Método | Descripción |
|--------|-------------|
| `list_characters()` | Lista nombres de personajes disponibles (carpetas con `dna/`) |
| `load_character(name)` | Inicializa personaje + KV Cache Dual con invalidación SHA-256 |
| `create_character(...)` | Crea estructura de directorios y JSONs del DNA |
| `generate_character_with_ai(name, prompt)` | Usa el LLM para autogenerar el DNA completo |
| `rebuild_personality_state()` | Ejecuta LLM interno para resumir historial y actualizar relación |
| `add_memory(content, priority, always_include, tags)` | Agrega memoria persistente a `long_term.json` |
| `get_state_info()` | Retorna dict con el estado actual del agente |

### Memoria y Contexto
| Método | Descripción |
|--------|-------------|
| `clear_memory()` | Limpia el historial de conversación (preserva system prompt) |
| `reset_chat()` | Alias de `clear_memory()` |
| `get_memory()` | Obtiene el historial como lista de dicts |
| `export_memory_json(path=None)` | Exporta historial a string JSON o archivo |
| `import_memory_json(str_or_path)` | Importa historial desde string JSON o archivo |
| `set_system_prompt(prompt)` | Cambia el system prompt en caliente |
| `trim_memory()` | Recorta manualmente el contexto según presupuesto de tokens |
| `save_episode()` | Guarda los últimos mensajes + resumen LLM en `episode_NNN.json` |
| `list_episodes()` | Lista todos los episodios guardados |
| `load_episode(id)` | Hace rollback al episodio indicado |
| `delete_episode(id)` | Elimina un snapshot de episodio |

### Modelo
| Método | Descripción |
|--------|-------------|
| `load_model(path=None)` | Carga modelo GGUF (path opcional, usa default_model si omitido) |
| `reload_model()` | Recarga el modelo actual (útil tras cambiar config) |
| `unload_model()` | Descarga el modelo (libera VRAM/RAM) |
| `switch_model(path)` | Descarga el actual y carga otro modelo |
| `get_model_info()` | Metadatos del modelo + info de hardware GPU (nvidia-smi) |
| `list_available_models()` | Escanea `models_directory` y lista todos los `.gguf` |

### Configuración y Debug
| Método | Descripción |
|--------|-------------|
| `get_config()` | Retorna la configuración actual como `ConfigSchema` |
| `reload_config()` | Recarga `config.json` en caliente |
| `enable_debug()` | Activa logs de debug en consola |
| `disable_debug()` | Desactiva logs de debug en consola |

### Propiedades de Extensión
| Propiedad | Tipo | Descripción |
|-----------|------|-------------|
| `state_manager` | `CharacterManager` | Acceso directo al sistema de capas del personaje |
| `slash_commands` | `SlashCommandRegistry` | Registro de comandos `/` para extensión |

## Slash Commands Incluidos
Se ejecutan como prompt en `chat()` o `stream_chat()`. **No gastan tokens** y operan sobre el Character OS directamente:

| Comando | Descripción |
|---------|-------------|
| `/mem <texto>` | Guarda memoria persistente con priority=1.0 |
| `/memories` | Lista todas las memorias con ID, tags y pin |
| `/save_episode` | Guarda snapshot episódico con resumen LLM |
| `/episodes [load N \| delete N]` | Lista, carga o elimina episodios |
| `/rel <trust> <familiarity>` | Actualiza el Relationship Engine (0.0 a 1.0) |
| `/mood <layer> <value> [intensity]` | Aplica CharacterMod temporal (ej: `/mood speech enojado 1.5`) |
| `/rebuild` | Reconstruye el estado de personalidad vía LLM |
| `/state` | Muestra el estado del agente en JSON |
| `/scene_view` | Fuerza descripción inmersiva de escena en 3ra persona |
| `/help` | Lista todos los comandos disponibles |

Para registrar comandos personalizados:
```python
@llm.slash_commands.command("mi_comando", description="Hace algo")
def handler(args: str) -> str:
    return f"Ejecutado con: {args}"
```

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
  "history_limit": 40,
  "auto_trim_context": true,
  "context_reserve_tokens": 800,
  "enable_logging": true,
  "enable_console_debug": false,
  "auto_unload_model": false,
  "model_idle_timeout": 600
}
```

| Campo | Default | Descripción |
|-------|---------|-------------|
| `n_ctx` | 4096 | Ventana de contexto en tokens |
| `n_batch` | 512 | Tamaño de lote para inferencia |
| `gpu_layers` | -1 | Capas en GPU (-1 = todas) |
| `flash_attn` | true | Flash Attention (acelera inferencia) |
| `short_memory_limit` | 5 | Mensajes recientes enviados crudos al LLM |
| `history_limit` | 40 | Máximo de mensajes en el historial |
| `auto_trim_context` | true | Recorte automático cuando se acerca al límite |
| `context_reserve_tokens` | 800 | Tokens reservados para la respuesta |
| `auto_unload_model` | false | Descarga el modelo al salir del context manager |
| `model_idle_timeout` | 600 | Tiempo de inactividad antes de auto-descarga (segundos) |

La versión 0.2.2 introduce un motor avanzado (Compiler v2) que separa el agente en componentes lógicos, utilizando un sistema de prioridad: **MODS > STATE > DNA**.
Además, incluye el sistema de **KV Cache Dual**, guardando tensores pre-evaluados (Base y Dinámico) con invalidación criptográfica SHA-256 para acelerar x10 los arranques.

- **DNA (Inmutable):** Archivos `identity.json`, `personality.json`, `speech.json` y `rules.json`. Define al personaje.
- **Memory (Persistente):** `long_term.json`, `episodes/`, `base.state`, `personality_plus_memory.state`. Recuerdos, memoria episódica versionada y caché compilado.
- **State (Dinámico):** `relationship_state.json`, `runtime_state.json`. Confianza, dinámica con el usuario.
- **Mods (Superposiciones):** Modificadores temporales en tiempo de ejecución.

```
vtool_llama/
│
├── __init__.py              # Exporta la API pública
├── engine.py                # VToolLlama (orquestador principal)
├── character_manager.py     # Capas del Character OS
├── character_compiler.py    # Compilador de prompts (MODS > STATE > DNA)
├── chat_memory.py           # Historial de conversación (OpenAI format)
├── config_manager.py        # Carga/validación de config.json
├── exceptions.py            # Jerarquía de excepciones personalizadas
├── logger_manager.py        # Logging a archivo + debug en consola
├── model_manager.py         # Inferencia llama.cpp + KV Cache
├── slash_commands.py        # Sistema de comandos con prefijo /
├── stats_manager.py         # Estadísticas de rendimiento
├── tokenizer_utils.py       # Tokenización y estimación de contexto
├── types.py                 # Dataclasses (DNA, State, Mods, Config)
│
├── config/
│   └── config.json          # Configuración de la librería
│
├── examples/                # Scripts de ejemplo
│   ├── console_chat.py      # Consola interactiva
│   ├── example_ai_builder.py# Generación de personajes con IA
│   ├── example_builder.py   # Creación manual de personajes
│   ├── example_elara.py     # Uso con context manager y episodios
│   └── thinking_and_tools.py# Thinking mode + Tool Calling
│
└── personajes/              # Perfiles de personajes
    ├── default/
    ├── coder/
    └── roleplay/
```

## Características Principales

- **KV Cache Dual con Inferencia Diferencial**: Reutiliza estados compilados (DNA) y calcula solo los tokens nuevos. ~0.2s de carga en caliente con invalidación criptográfica SHA-256.
- **Character Compiler v2**: Compila el prompt dinámicamente con prioridad MODS > STATE > DNA. Los Mods sobreescriben cualquier capa sin modificar archivos originales.
- **Memoria Episódica (Short-Term Versionada)**: Snapshot `episode_NNN.json` con resumen LLM que permite rollback y continuidad entre sesiones.
- **Auto-Tools (Reasoning Loop)**: Inyecta `remember_memory` silenciosamente. El modelo guarda datos en `long_term.json` sin romper el diálogo. Límite de 3 iteraciones anti-loop.
- **AI Character Generator**: El LLM genera el DNA completo (identidad, personalidad, habla, reglas, memorias) desde un prompt descriptivo.
- **Relationship Engine**: Confianza y familiaridad persistente (0.0 a 1.0) que modifica la actitud del personaje en tiempo real.
- **Thinking Mode**: Soporte nativo para `reasoning_content` de DeepSeek-R1 y parseo de etiquetas `<think>` en streaming.
- **Tool Calling con Validación**: El motor filtra alucinaciones de nombres de herramientas automáticamente. Formato OpenAI estándar.
- **Slash Commands Extensibles**: Comandos `/` que no gastan tokens. Registrables via `@llm.slash_commands.command()`.
- **Exportación/Importación de Historial**: Serializa y restaura conversaciones completas en JSON.
- **GPU Automático**: Detección de CUDA via `torch` y `nvidia-smi`. Distribución dinámica de capas con fallback a CPU.
- **Context Manager**: Soporte `with` con auto-guardado de episodios y descarga opcional del modelo.

## Licencia
MIT
