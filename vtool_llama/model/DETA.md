# Model — Arquitectura Detallada

## Visión General

Gestiona el ciclo de vida completo del modelo GGUF usando `llama-cpp-python`. Responsabilidades: cargar/descargar/recambiar modelos, ejecutar inferencia (stream y no-stream), detectar CUDA, gestionar KV Cache para warmup de personajes, y consultar capacidad del modelo.

```
model/
├── __init__.py       # Barrel: exporta ModelManager
├── manager.py        # Clase base + constructor + propiedades
├── model_ops.py      # Carga/descarga/recarga + validación + path + CUDA
├── inference.py      # generate()
├── kv_cache.py       # warmup + save/load KV state
└── capacity.py       # get_model_info + supports_tools + count_tokens
```

## Archivos del Subpackage

### `__init__.py`
Barrel. Exporta `ModelManager`. Importa los 4 submódulos para asignar métodos a la clase.

### `manager.py` — Clase Base

Define `ModelManager` con constructor y propiedades de solo lectura.

| Propiedad | Tipo | Descripción |
|-----------|------|-------------|
| `model` | `Any` | Referencia al objeto `Llama` (None si no hay) |
| `model_info` | `ModelInfo` | Metadatos del modelo cargado |
| `is_loaded` | `bool` | True si hay modelo en memoria |
| `tokenize_fn` | `Optional[Callable]` | Función de tokenización del modelo |

**Constructor**: Recibe `ConfigSchema`, `logger_fn(tag, msg)`, `error_fn(msg)`. Inicializa `RLock` para thread-safety.

### `model_ops.py` — Operaciones del Modelo

Métodos asignados a `ModelManager` para el ciclo de vida del modelo.

| Método | Rol |
|--------|-----|
| `load_model(path)` | Carga modelo GGUF: valida path, detecta CUDA, construye kwargs, instancia `Llama()`, cachea tokenizer |
| `_validate_model_path(path)` | Verifica que el archivo exista y sea `.gguf` |
| `_check_cuda()` | Detecta CUDA vía `llama_cpp.llama_supports_gpu_offload()` o fallback a `torch.cuda` |
| `_build_llama_kwargs(path, cuda)` | Arma kwargs para `Llama()` con config + GPU |
| `_build_model_info(path)` | Construye `ModelInfo` con nombre, contexto, VRAM estimada |
| `_extract_model_name(path)` | Extrae nombre desde metadata GGUF o filename |
| `_resolve_model_path(path)` | Resuelve ruta absoluta/relativa/default |
| `list_available_models()` | Escanea `models_directory` por `.gguf` files |
| `unload_model()` | Libera modelo + GC + `torch.cuda.empty_cache()` |
| `reload_model()` | Unload + load con misma ruta |
| `switch_model(path)` | Unload + load con nueva ruta |

**Flujo de carga** (`load_model`):
```
_resolve_model_path → _validate_model_path → _check_cuda
→ _build_llama_kwargs → Llama(**kwargs) → _build_model_info
```

**Manejo de errores**: Diferencia OOM (out of memory), GGUF inválido/corrupto, y errores genéricos. Cada uno lanza su propia excepción (`OOMError`, `InvalidModelError`, `InferenceError`).

### `inference.py` — Generación

| Método | Rol |
|--------|-----|
| `generate(messages, stream, ...)` | Llama a `model.create_chat_completion()` con merge de parámetros (config defaults sobreescribibles por call-site) |

**Soporta**: streaming, tools (OpenAI format), tool_choice. Detecta OOM durante inferencia.

### `kv_cache.py` — KV Cache

Gestiona el estado del KV Cache para warmup de personajes (arquitectura de caché dual: Base + Dynamic).

| Método | Rol |
|--------|-----|
| `save_kv_state(filepath)` | Serializa KV Cache con pickle |
| `load_kv_state(filepath)` | Carga KV Cache desde disco |
| `warmup_system_prompt(prompt)` | Pre-evalúa system prompt para rellenar KV Cache |

### `capacity.py` — Consultas de Capacidad

| Método | Rol |
|--------|-----|
| `get_model_info()` | Metadata del modelo + hardware GPU (nvidia-smi + torch fallback) |
| `supports_tools()` | Detecta tool calling nativo analizando `tokenizer.chat_template` en metadata GGUF |
| `count_tokens(text)` | Tokens exactos vía tokenizer del modelo, o estimación si no hay modelo |

## Thread Safety

Todos los métodos mutantes usan `self._lock` (RLock) para acceso concurrente seguro. `_loading` previene cargas duplicadas.

## Dependencias Externas

| Dependencia | Uso |
|-------------|-----|
| `llama-cpp-python` (Llama) | Motor de inferencia GGUF |
| `torch` (opcional) | Fallback para detección CUDA y limpieza de cache |
| `nvidia-smi` (opcional) | Información detallada de VRAM hardware |
| `engine/tokenizer_utils` | Conteo exacto/estimado de tokens |

## Manejo de Errores

| Error | Condición |
|-------|-----------|
| `ModelNotFoundError` | Archivo `.gguf` no existe |
| `InvalidModelError` | Archivo no es GGUF válido o está corrupto |
| `CUDAUnavailableError` | CUDA no disponible |
| `OOMError` | VRAM/RAM insuficiente (carga o inferencia) |
| `ModelNotLoadedError` | Se llamó a `generate()` sin modelo cargado |
| `InferenceError` | Error genérico durante inferencia |
