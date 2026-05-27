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

# Alternativa: Si instalaste CUDA Toolkit 12.4, usa:
# pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124

# Alternativa: CPU-only (sin GPU)
# pip install llama-cpp-python
```

## Uso básico

```python
from vtool_llama import VToolLlama

# Inicializar (carga el modelo automáticamente)
llm = VToolLlama()

# Chat simple
respuesta = llm.chat("Hola, ¿cómo estás?")
print(respuesta)

# Streaming token por token
for token in llm.stream_chat("Explícame Python"):
    print(token, end="")
```

## API completa

### Chat
| Método | Descripción |
|--------|-------------|
| `chat(prompt, tools=None)` | Respuesta completa (retorna texto o dict de tool_call) |
| `stream_chat(prompt, tools=None)` | Streaming token por token / chunks de tool_call |
| `chat_with_thinking(prompt)` | Retorna tupla `(thinking, content)` |
| `stream_chat_with_thinking(prompt)` | Streaming de tuplas `(tipo, token)` para razonamiento |

### Memoria
| Método | Descripción |
|--------|-------------|
| `clear_memory()` | Limpiar historial |
| `reset_chat()` | Reiniciar conversación |
| `get_memory()` | Obtener historial como lista |
| `add_tool_message(content, tool_call_id)` | Registrar respuesta de herramienta |
| `export_memory_json(path)` | Exportar historial a JSON |
| `import_memory_json(data)` | Importar historial desde JSON |
| `set_system_prompt(text)` | Cambiar system prompt |

### Modelo
| Método | Descripción |
|--------|-------------|
| `load_model(path)` | Cargar modelo GGUF (path opcional; si se omite usa default_model) |
| `unload_model()` | Descargar modelo (libera VRAM) |
| `reload_model()` | Recargar con configuración actual |
| `switch_model(path)` | Cambiar a otro modelo |
| `get_model_info()` | Metadatos del modelo |
| `list_available_models()` | Lista todos los `.gguf` en `models_directory` |

```python
# Listar modelos disponibles
modelos = llm.list_available_models()
for m in modelos:
    print(f"{m['filename']} — {m['size_gb']} GB")

# Cargar solo con el nombre (busca en models_directory)
llm.load_model("Mistral-7B.gguf")

# O cargar el default del config
llm.load_model()
```

### Debug
| Método | Descripción |
|--------|-------------|
| `enable_debug()` | Activar logs detallados en consola |
| `disable_debug()` | Desactivar logs |

### Contexto
| Método | Descripción |
|--------|-------------|
| `trim_memory()` | Recortar manualmente el contexto |

## Configuración

Editar `vtool_llama/config/config.json`:

```json
{
  "debug": true,
  "models_directory": "D:/AI/Models",
  "default_model": "Qwen3-8B-Q4_K_M.gguf",
  "system_prompt": "Eres un asistente útil y natural.",
  "n_ctx": 4096,
  "gpu_layers": -1,
  "temperature": 0.8,
  "max_tokens": 512,
  "auto_trim_context": true
}
```

El `load_model()` sin argumentos usa `models_directory + default_model`.
Podés pasar solo el nombre del archivo y lo busca en el directorio:
```python
llm.load_model("Mistral-7B.gguf")
```

## Arquitectura

```
vtool_llama/
│
├── __init__.py          # API pública
├── engine.py            # Clase VToolLlama (orquestador)
├── model_manager.py     # Carga/inferencia/descarga de modelos
├── config_manager.py    # Configuración desde JSON
├── chat_memory.py       # Historial de conversación
├── tokenizer_utils.py   # Utilidades de tokenización
├── logger_manager.py    # Logging + debug coloreado
├── stats_manager.py     # Estadísticas de rendimiento
├── exceptions.py        # Excepciones personalizadas
├── types.py             # Dataclasses y tipos compartidos
│
├── config/
│   └── config.json      # Configuración global
│
├── examples/
│   └── console_chat.py  # Ejemplo de consola (NO es el núcleo)
│
├── requirements.txt
└── README.md
```

## Características

- **Persistencia del modelo**: el modelo se carga UNA vez y se reutiliza entre mensajes
- **Streaming real**: tokens en tiempo real via `llama-cpp-python`
- **Auto-trim de contexto**: evita que el contexto explote automáticamente
- **Thread-safe**: locks para acceso concurrente seguro
- **GPU automático**: detecta CUDA y configura GPU; fallback a CPU
- **Manejo de OOM**: detecta memoria insuficiente y sugiere soluciones
- **Logging a archivo**: rotación diaria con 30 días de retención
- **Debug coloreado**: tags `[MODEL] [GPU] [CHAT] [TOKENS] [MEMORY]`
- **Historial estilo OpenAI**: compatible con formatos de chat estándar
- **Configurable desde JSON**: sin tocar código para cambiar parámetros

## Ejemplo de integración

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "vtool_llama"))

from vtool_llama import VToolLlama

llm = VToolLlama(
    config_path="mi_config.json",
    auto_load=True
)

while True:
    pregunta = input("> ")
    if pregunta == "salir":
        break
    print(llm.chat(pregunta))
```

## Recomendaciones de Rendimiento y Velocidad

Si notas que el chat tarda demasiado en responder o generar texto, revisa las siguientes optimizaciones en tu configuración y entorno:

### 1. Activar Flash Attention (Velocidad y Memoria)
* Asegúrate de tener `"flash_attn": true` en tu `config.json`. Esto reduce significativamente el uso de memoria en contextos largos y acelera el procesamiento del prompt (pre-evaluación).

### 2. Sintonizar el Número de Hilos (`threads`)
* En tu `config.json`, define `"threads"` exactamente igual a la cantidad de **núcleos físicos** (no hilos lógicos/hiperhilos) de tu procesador (usualmente `4` o `6`). Configurar más hilos que núcleos físicos provoca sobrecarga por sincronización y ralentiza la inferencia.

### 3. Reducir el Contexto (`n_ctx`)
* Un valor de `"n_ctx": 4096` requiere procesar y almacenar un historial más largo. Si el bot no requiere memoria excesivamente larga, reducirlo a `2048` aumentará la velocidad drásticamente en chats prolongados.

### 4. Elegir Modelos de Menor Parámetro (ej. 3B o 1.5B)
* El modelo por defecto `Qwen3-8B-Q4_K_M.gguf` requiere una cantidad considerable de VRAM/cómputo.
* Si necesitas respuestas casi instantáneas, te recomendamos descargar variantes de menor tamaño, tales como:
  * `Qwen2.5-3B-Instruct-Q4_K_M.gguf`
  * `Llama-3.2-3B-Instruct-Q4_K_M.gguf`
  * `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`

### 5. Utilizar `stream_chat` para el Usuario Final
* En lugar de esperar a que termine toda la respuesta con `.chat()`, utiliza el generador `.stream_chat()`. Esto reduce a milisegundos el **tiempo para el primer token** (TTFT) percibido por el usuario, ofreciendo una experiencia mucho más fluida.

## Licencia

MIT
