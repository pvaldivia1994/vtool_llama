# Manual de Integración de `vtool_llama` para Agentes de IA

Este documento sirve como especificación técnica y guía de referencia ("skill") para que cualquier Agente de IA pueda consumir e integrar la librería `vtool_llama` de forma autónoma en proyectos Python.

---

## 1. Descripción de la Herramienta
`vtool_llama` es una librería modular de IA conversacional local optimizada para Windows. Encapsula `llama-cpp-python` para cargar modelos GGUF, gestionar el historial de conversación (estilo OpenAI) con auto-recorte de contexto, y automatizar el uso de aceleración por GPU (CUDA).

---

## 2. API de la Clase Principal: `VToolLlama`

La interfaz pública principal se importa desde la raíz del paquete:
```python
from vtool_llama import VToolLlama
```

### Constructor: `VToolLlama(config_path=None, auto_load=True)`
* **`config_path`** *(str, opcional)*: Ruta absoluta o relativa a un archivo de configuración personalizado. Si se omite, busca en el directorio por defecto (`vtool_llama/config/config.json`).
* **`auto_load`** *(bool, opcional)*: Si es `True`, carga automáticamente el modelo definido en la configuración durante la inicialización. Por defecto `True`.

---

## 3. Catálogo de Métodos Disponibles

### A. Conversación y Chat
* **`chat(prompt, max_tokens=None, temperature=None, top_p=None, top_k=None, repeat_penalty=None, tools=None, tool_choice=None)` -> `str` o `dict`**
  * Envía un mensaje al modelo (añadiéndolo automáticamente al historial) y retorna la respuesta.
  * Si se pasa `tools` (lista de definiciones de funciones en formato OpenAI JSON Schema), y el modelo decide invocar una herramienta, el retorno será el diccionario del mensaje completo con la clave `tool_calls`. Si no, devuelve un `str` con el texto de la respuesta.
  * *Argumentos:* Permiten sobrescribir dinámicamente los parámetros definidos en `config.json` para esta inferencia.

* **`stream_chat(prompt, max_tokens=None, temperature=None, top_p=None, top_k=None, repeat_penalty=None, tools=None, tool_choice=None)` -> `Generator[str o dict, None, None]`**
  * Versión en streaming del método anterior. Retorna un generador que entrega los tokens uno a uno a medida que se generan en tiempo real.
  * Si se pasa `tools`, el generador yieldeará los chunks del stream que contienen fragmentos de `tool_calls`.

* **`chat_with_thinking(prompt, max_tokens=None, temperature=None, top_p=None, top_k=None, repeat_penalty=None)` -> `tuple[str, str]`**
  * Diseñado para modelos de razonamiento (como DeepSeek-R1). Retorna una tupla `(thinking, content)` donde `thinking` es la cadena del pensamiento interno (extraída de las etiquetas `<think>...</think>`) y `content` es la respuesta final de texto.

* **`stream_chat_with_thinking(prompt, max_tokens=None, temperature=None, top_p=None, top_k=None, repeat_penalty=None)` -> `Generator[tuple[str, str], None, None]`**
  * Generador en streaming que rinde tuplas de la forma `(tipo, token)`, donde `tipo` puede ser `"thinking"` (si pertenece al razonamiento interno) o `"content"` (si pertenece al mensaje final). Ideal para interfaces de usuario en tiempo real.

### B. Gestión de Memoria e Historial
* **`clear_memory()` / `reset_chat()` -> `None`**
  * Borra todo el historial de la conversación actual. El `system_prompt` no se elimina, se mantiene activo.
* **`get_memory()` -> `list[dict]`**
  * Retorna la lista de mensajes acumulados en el historial en formato OpenAI, incluyendo soporte para `tool_calls` y mensajes de rol `tool`.
* **`set_system_prompt(prompt)` -> `None`**
  * Cambia el prompt del sistema asignado para la conversación.
* **`add_tool_message(content, tool_call_id)` -> `None`**
  * Registra la salida de la ejecución de una herramienta local en el historial de conversación para que el modelo pueda leerla en su próximo turno.
* **`export_memory_json(path=None)` -> `str`**
  * Exporta el historial actual a un formato JSON string. Si se le pasa `path`, guarda el archivo directamente en disco.
* **`import_memory_json(json_str_or_path)` -> `None`**
  * Importa y reemplaza la memoria actual a partir de una cadena JSON o de la ruta de un archivo exportado.
* **`trim_memory()` -> `int`**
  * Recorta manualmente los mensajes más antiguos del historial si exceden el presupuesto del contexto definido por `n_ctx` y `context_reserve_tokens`. Retorna la cantidad de mensajes eliminados.

### C. Gestión del Modelo GGUF
* **`load_model(model_path=None)` -> `None`**
  * Carga el modelo en memoria. Si `model_path` es `None`, se carga el modelo configurado por defecto. Acepta nombres de archivo simples si están dentro del directorio de modelos.
* **`unload_model()` -> `None`**
  * Libera el modelo y fuerza la recolección de basura para desocupar la VRAM/RAM en el sistema.
* **`switch_model(model_path)` -> `None`**
  * Descarga el modelo actual y carga el nuevo especificado en `model_path`.
* **`get_model_info()` -> `dict`**
  * Retorna un diccionario con metadatos del modelo actual: `model_name`, `model_path`, `context_size`, `gpu_layers`, `estimated_vram` y `loaded`.
* **`list_available_models()` -> `list[dict]`**
  * Escanea el directorio de modelos (`models_directory`) y devuelve una lista de diccionarios con información de los archivos `.gguf` disponibles.

### D. Configuración y Debug
* **`enable_debug()` / `disable_debug()` -> `None`**
  * Activa/desactiva logs detallados en la consola.
* **`reload_config()` -> `None`**
  * Vuelve a cargar y aplicar el archivo `config.json` en caliente sin necesidad de reiniciar la aplicación.

---

## 4. Ejemplos Rápidos de Uso

### Ejemplo 1: Flujo Básico de Pregunta y Respuesta (No-Blocking)
```python
import sys
from pathlib import Path

# Añadir vtool_llama al path de ejecución si está localmente en el subdirectorio
sys.path.insert(0, str(Path(__file__).parent / "vtool_llama"))

from vtool_llama import VToolLlama

# Inicializar y cargar el modelo automáticamente
llm = VToolLlama()

# Realizar una pregunta simple
respuesta = llm.chat("¿Cuál es la diferencia entre una lista y una tupla en Python?")
print(f"Respuesta del Asistente:\n{respuesta}")

# Reiniciar la memoria para iniciar una nueva conversación
llm.reset_chat()
```

### Ejemplo 2: Generación en Streaming (Recomendado para UIs)
```python
from vtool_llama import VToolLlama

llm = VToolLlama()

# Enviar prompt y leer token a token
print("Bot: ", end="")
for token in llm.stream_chat("Escribe un poema corto sobre inteligencia artificial"):
    print(token, end="", flush=True)
print()
```

### Ejemplo 3: Gestión de Modelos y Cambio en Caliente
```python
from vtool_llama import VToolLlama

llm = VToolLlama(auto_load=False)  # No cargar nada al inicio

# Ver modelos disponibles
modelos = llm.list_available_models()
for m in modelos:
    print(f"Modelo: {m['filename']} | Tamaño: {m['size_gb']} GB")

# Cargar un modelo específico de la lista
if modelos:
    llm.load_model(modelos[0]['filename'])
    
    # Hacer una pregunta
    print(llm.chat("Hola"))
    
    # Liberar memoria de forma explícita
    llm.unload_model()
```

---

## 5. Manejo de Excepciones Comunes

El agente debe envolver las llamadas en bloques `try/except` utilizando los tipos provistos por `vtool_llama.exceptions`:

```python
from vtool_llama.exceptions import (
    ModelNotFoundError,
    OOMError,
    InferenceError,
    ModelNotLoadedError
)

try:
    llm.chat("Mi prompt largo")
except ModelNotFoundError:
    print("Error: El archivo .gguf no existe en la ruta configurada.")
except OOMError:
    print("Error: Sin memoria suficiente (VRAM/RAM). Reduce n_ctx en config.json.")
except ModelNotLoadedError:
    print("Error: Intento de inferencia sin cargar un modelo. Ejecuta llm.load_model().")
except InferenceError as e:
    print(f"Error general de ejecución en llama.cpp: {e}")
```
