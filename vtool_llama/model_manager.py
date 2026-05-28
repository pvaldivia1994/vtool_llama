"""
Gestor del modelo de lenguaje para vtool_llama.

Responsabilidades críticas:
- Cargar modelos GGUF usando llama-cpp-python
- Mantener el modelo en memoria (NO recargar entre mensajes)
- Detectar CUDA disponible y configurar GPU automáticamente
- Manejar OOM (Out Of Memory) con fallback a CPU
- Exponer metadatos del modelo cargado
- Ser thread-safe para acceso concurrente

Flujo típico:
1. load_model(ruta) -> crea Llama() y lo guarda en self._model
2. generate(prompt) -> usa self._model.create_completion()
3. unload_model() -> libera la memoria del modelo
4. switch_model(ruta) -> unload + load con nueva ruta

El modelo se mantiene en memoria hasta que se solicite
explícitamente su descarga o se cambie la configuración crítica.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Generator, Optional

from .exceptions import (
    CUDAUnavailableError,
    InferenceError,
    InvalidModelError,
    ModelNotFoundError,
    ModelNotLoadedError,
    OOMError,
)
from .types import ConfigSchema, ModelInfo


class ModelManager:
    """
    Gestiona el ciclo de vida del modelo GGUF.

    Args:
        config: configuración actual (ConfigSchema)
        logger_fn: callable para logging (tag, mensaje)
        error_fn: callable para logging de errores
    """

    def __init__(
        self,
        config: ConfigSchema,
        logger_fn: Callable[[str, str], None],
        error_fn: Callable[[str], None],
    ):
        self._config = config
        self._log = logger_fn
        self._error = error_fn

        # El modelo en sí — None hasta que se cargue
        self._model: Any = None

        # Metadatos del modelo actual
        self._model_info: ModelInfo = ModelInfo()

        # Lock para proteger acceso concurrente al modelo
        self._lock = threading.RLock()

        # Cache de función tokenize del modelo
        self._tokenize_fn: Optional[Callable] = None

        # Bandera para evitar cargas duplicadas
        self._loading = False

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    @property
    def model(self) -> Any:
        """Referencia al modelo Llama cargado (None si no hay)."""
        return self._model

    @property
    def model_info(self) -> ModelInfo:
        """Metadatos del modelo actual."""
        return self._model_info

    @property
    def is_loaded(self) -> bool:
        """Indica si hay un modelo cargado en memoria."""
        return self._model is not None

    @property
    def tokenize_fn(self) -> Optional[Callable]:
        """
        Función de tokenización del modelo cargado.
        Útil para contar tokens exactos sin exponer el modelo.
        """
        return self._tokenize_fn

    # ------------------------------------------------------------------
    # Resolución de ruta del modelo
    # ------------------------------------------------------------------

    def _resolve_model_path(self, model_path: Optional[str] = None) -> Path:
        """
        Resuelve la ruta completa al archivo .gguf.

        Si model_path es:
        - Una ruta absoluta a un .gguf  -> se usa directamente
        - Un nombre de archivo          -> se busca en models_directory
        - None                           -> se usa default_model en models_directory

        Returns:
            Path resuelto al archivo .gguf
        """
        if model_path:
            path = Path(model_path)
            if path.is_absolute():
                return path
            # Es un nombre de archivo relativo -> buscar en el directorio
            return Path(self._config.models_directory) / path

        # Sin argumento: construir desde models_directory + default_model
        base = Path(self._config.models_directory)
        return base / self._config.default_model

    # ------------------------------------------------------------------
    # Listar modelos disponibles
    # ------------------------------------------------------------------

    def list_available_models(self) -> list[dict[str, str]]:
        """
        Escanea el directorio de modelos y retorna todos los .gguf
        encontrados con su información básica.

        Returns:
            lista de dicts con nombre, ruta, tamaño (GB), y fecha
        """
        models_dir = Path(self._config.models_directory)
        if not models_dir.exists() or not models_dir.is_dir():
            self._log("MODEL", f"Directorio de modelos no encontrado: {models_dir}")
            return []

        resultados = []
        for f in sorted(models_dir.glob("*.gguf")):
            size_gb = round(f.stat().st_size / (1024 ** 3), 2)
            resultados.append({
                "filename": f.name,
                "path": str(f.resolve()),
                "size_gb": size_gb,
                "modified": f.stat().st_mtime,
            })

        self._log("MODEL", f"Modelos encontrados: {len(resultados)} en {models_dir}")
        return resultados

    # ------------------------------------------------------------------
    # Carga del modelo
    # ------------------------------------------------------------------

    def load_model(self, model_path: Optional[str] = None) -> None:
        """
        Carga un modelo GGUF en memoria.

        Args:
            model_path: ruta al .gguf. Si es None, usa models_directory
                       + default_model del config. También acepta solo
                       el nombre del archivo (lo busca en el directorio).

        Raises:
            ModelNotFoundError: el archivo no existe
            InvalidModelError: el archivo no es un GGUF válido
            CUDAUnavailableError: no se detectó CUDA
            OOMError: VRAM/RAM insuficiente
        """
        with self._lock:
            if self._loading:
                self._log("MODEL", "Ya hay una carga en progreso, ignorando...")
                return

            self._loading = True
            path = self._resolve_model_path(model_path)

            try:
                self._validate_model_path(path)
                self._log("MODEL", f"Cargando modelo: {path.name}")

                # Detectar CUDA
                cuda_available = self._check_cuda()

                # Construir kwargs para Llama
                kwargs = self._build_llama_kwargs(path, cuda_available)

                # Importar llama_cpp_python aquí para que el error
                # de importación sea claro si no está instalado
                try:
                    from llama_cpp import Llama
                except ImportError as e:
                    raise ImportError(
                        "llama-cpp-python no está instalado. "
                        "Ejecuta: pip install llama-cpp-python"
                    ) from e

                # Cargar el modelo
                self._log("MODEL", "Inicializando modelo (esto puede tomar varios segundos)...")

                try:
                    model = Llama(**kwargs)
                except Exception as e:
                    error_msg = str(e).lower()

                    # Detectar OOM
                    if any(term in error_msg for term in [
                        "out of memory", "cuda out of", "cuda error",
                        "memory", "alloc", "vram",
                    ]):
                        raise OOMError(
                            f"Memoria insuficiente para cargar {path.name} "
                            f"con la configuración actual. "
                            f"Intenta reducir n_ctx o gpu_layers."
                        ) from e

                    # Detectar GGUF inválido
                    if any(term in error_msg for term in [
                        "invalid", "corrupt", "format", "magic",
                        "not a llama", "gguf",
                    ]):
                        raise InvalidModelError(
                            f"El archivo {path.name} no es un GGUF válido "
                            f"o está corrupto: {e}"
                        ) from e

                    raise InferenceError(
                        f"Error al cargar el modelo: {e}"
                    ) from e

                self._model = model
                self._model_info = self._build_model_info(path)

                # Cachear función de tokenización
                if hasattr(model, "tokenize"):
                    self._tokenize_fn = model.tokenize
                elif hasattr(model, "tokenizer"):
                    self._tokenize_fn = model.tokenizer.encode

                # Mostrar info del modelo cargado
                self._log("MODEL", f"Modelo cargado: {self._model_info.model_name}")
                self._log("MODEL", f"Contexto: {self._model_info.context_size} tokens")
                self._log("GPU", f"Capas GPU: {self._model_info.gpu_layers}")
                self._log("GPU", f"VRAM estimada: {self._model_info.estimated_vram_gb} GB")

            finally:
                self._loading = False

    def _validate_model_path(self, path: Path) -> None:
        """
        Valida que la ruta del modelo exista y sea un archivo .gguf.

        Raises:
            ModelNotFoundError: si no existe
            InvalidModelError: si no termina en .gguf
        """
        if not path.exists():
            raise ModelNotFoundError(
                f"Modelo no encontrado: {path}\n"
                f"Verifica la ruta en config.json o proporciona una válida."
            )

        if not path.is_file():
            raise InvalidModelError(
                f"La ruta {path} no es un archivo."
            )

        extension = path.suffix.lower()
        if extension != ".gguf":
            self._log("MODEL", f"Advertencia: extensión '{extension}' no es .gguf")

    def _check_cuda(self) -> bool:
        """
        Detecta si CUDA está disponible para llama-cpp-python.

        Returns:
            True si CUDA está disponible
        """
        # Intentar detectar usando llama_cpp directamente
        try:
            import llama_cpp
            if hasattr(llama_cpp, "llama_supports_gpu_offload"):
                has_gpu = llama_cpp.llama_supports_gpu_offload()
                if has_gpu:
                    self._log("GPU", "llama.cpp reporta soporte para GPU/CUDA")
                else:
                    self._log("GPU", "llama.cpp compilado sin soporte GPU, usando CPU")
                return has_gpu
        except ImportError:
            pass

        # Fallback a torch si no pudimos con llama.cpp
        try:
            import torch
            cuda_available = torch.cuda.is_available()
            if cuda_available:
                device_count = torch.cuda.device_count()
                device_name = torch.cuda.get_device_name(0) if device_count > 0 else "desconocida"
                self._log("GPU", f"CUDA detectado vía torch: {device_name} ({device_count} dispositivo(s))")
            else:
                self._log("GPU", "CUDA no disponible, usando CPU")
            return cuda_available
        except ImportError:
            self._log("GPU", "No se pudo determinar soporte CUDA, asumiendo CPU")
            return False

    def _build_llama_kwargs(
        self,
        path: Path,
        cuda_available: bool,
    ) -> dict:
        """
        Construye los argumentos para crear una instancia de Llama.

        Args:
            path: ruta al archivo .gguf
            cuda_available: si CUDA está presente

        Returns:
            dict de kwargs para Llama()
        """
        kwargs = {
            "model_path": str(path),
            "n_ctx": self._config.n_ctx,
            "n_batch": self._config.n_batch,
            "n_threads": self._config.threads,
            "flash_attn": self._config.flash_attn,
            "verbose": False,  # Evitar el verbose nativo de llama.cpp
        }

        # Configurar GPU
        if cuda_available:
            # En Windows con CUDA, n_gpu_layers controla cuántas
            # capas se envían a GPU
            kwargs["n_gpu_layers"] = self._config.gpu_layers

            # Usar el backend metal para compatibilidad
            # En Windows con NVIDIA, se usa CUDA por defecto
            self._log("GPU", f"Usando GPU con n_gpu_layers={self._config.gpu_layers}")
        else:
            kwargs["n_gpu_layers"] = 0
            self._log("GPU", "Modo CPU: todas las capas en CPU")

        # Configuración de generación (valores por defecto)
        # Estos se pueden sobreescribir en cada llamada a generate()
        kwargs["temperature"] = self._config.temperature
        kwargs["top_p"] = self._config.top_p
        kwargs["top_k"] = self._config.top_k
        kwargs["repeat_penalty"] = self._config.repeat_penalty

        # Seed para reproducibilidad
        if self._config.seed != -1:
            kwargs["seed"] = self._config.seed

        # Logging de configuración
        self._log("CONFIG", f"n_ctx={kwargs['n_ctx']}, n_batch={kwargs['n_batch']}")
        self._log("CONFIG", f"threads={kwargs['n_threads']}, gpu_layers={kwargs.get('n_gpu_layers', 0)}")

        return kwargs

    def _build_model_info(self, path: Path) -> ModelInfo:
        """
        Construye metadatos del modelo cargado.

        Args:
            path: ruta al archivo .gguf

        Returns:
            ModelInfo con datos estimados
        """
        # Intentar obtener nombre del modelo desde el metadata
        model_name = self._extract_model_name(path)

        # Estimar tamaño del modelo basado en tamaño del archivo
        file_size_gb = path.stat().st_size / (1024 ** 3)

        # VRAM estimada: el archivo GGUF es ~60-70% del tamaño
        # en memoria de inferencia (por cuantización)
        estimated_vram = round(file_size_gb * 1.4, 1)

        return ModelInfo(
            model_name=model_name,
            model_path=str(path),
            context_size=self._config.n_ctx,
            gpu_layers=self._config.gpu_layers,
            estimated_vram_gb=estimated_vram,
            loaded=True,
        )

    def _extract_model_name(self, path: Path) -> str:
        """
        Extrae un nombre descriptivo del archivo GGUF.

        Intenta obtener metadata del modelo; si no puede,
        usa el nombre del archivo.
        """
        try:
            if self._model is not None:
                # Intentar acceder a metadata del modelo
                metadata = getattr(self._model, "metadata", None)
                if metadata:
                    for key in ["general.name", "llama.model_name", "model.name"]:
                        if key in metadata:
                            return str(metadata[key])

                # Leer el tipo de modelo desde el archivo
                model_type = getattr(self._model, "model_type", None)
                if model_type:
                    return f"{model_type}"
        except Exception:
            pass

        # Fallback: nombre del archivo sin extensión
        name = path.stem
        # Limpiar nombres comunes de cuantización
        for suffix in ["-Q4_K_M", "-Q4_K_S", "-Q5_K_M", "-Q5_K_S",
                       "-Q6_K", "-Q8_0", "-F16", "-BF16",
                       ".Q4_K_M", ".Q4_K_S", ".Q5_K_M"]:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break

        return name

    # ------------------------------------------------------------------
    # Generación (inferencia)
    # ------------------------------------------------------------------

    def generate(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[Any] = None,
    ) -> Any:
        """
        Ejecuta la inferencia del modelo.

        Args:
            messages: lista de mensajes estilo OpenAI
            stream: si es True, retorna un generador
            max_tokens: máximo de tokens a generar
            temperature: temperatura (sobreescribe config)
            top_p: top_p (sobreescribe config)
            top_k: top-k sampling
            repeat_penalty: penalización de repetición
            tools: lista de herramientas en formato OpenAI
            tool_choice: tipo de selección de herramienta

        Returns:
            dict con la respuesta completa, o generador si stream=True

        Raises:
            ModelNotLoadedError: si no hay modelo cargado
            InferenceError: si falla la generación
        """
        with self._lock:
            if self._model is None:
                raise ModelNotLoadedError(
                    "No hay modelo cargado. Llama a load_model() primero."
                )

            # Preparar kwargs específicos de esta generación
            kwargs = {
                "messages": messages,
                "max_tokens": max_tokens or self._config.max_tokens,
                "temperature": temperature if temperature is not None else self._config.temperature,
                "top_p": top_p if top_p is not None else self._config.top_p,
                "top_k": top_k if top_k is not None else self._config.top_k,
                "repeat_penalty": repeat_penalty if repeat_penalty is not None else self._config.repeat_penalty,
                "stream": stream,
            }

            if tools is not None:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice or "auto"

            try:
                result = self._model.create_chat_completion(**kwargs)
                return result
            except Exception as e:
                error_msg = str(e)

                # Detectar OOM durante inferencia
                if any(term in error_msg.lower() for term in [
                    "out of memory", "cuda out of", "cuda error: out of memory",
                ]):
                    raise OOMError(
                        "Memoria insuficiente durante inferencia. "
                        "Reduce n_ctx o usa un modelo más pequeño."
                    ) from e

                raise InferenceError(
                    f"Error durante inferencia: {e}"
                ) from e

    # ------------------------------------------------------------------
    # Descarga y recarga
    # ------------------------------------------------------------------

    def unload_model(self) -> None:
        """
        Descarga el modelo de memoria.

        Importante: llama_cpp_python no tiene un método close()
        oficial, así que eliminamos la referencia y forzamos GC.
        """
        with self._lock:
            if self._model is None:
                self._log("MODEL", "No hay modelo cargado para descargar.")
                return

            model_name = self._model_info.model_name
            self._log("MODEL", f"Descargando modelo: {model_name}")

            # Eliminar referencia al modelo
            self._model = None
            self._tokenize_fn = None
            self._model_info = ModelInfo()

            # Forzar garbage collection para liberar VRAM
            import gc
            gc.collect()

            # En Windows con CUDA, también intentar vaciar cache de torch
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    self._log("GPU", "Cache de CUDA liberada")
            except ImportError:
                pass

            self._log("MODEL", f"Modelo {model_name} descargado correctamente")

    def reload_model(self) -> None:
        """
        Recarga el modelo actual con la configuración vigente.
        Útil después de cambiar config.json sin reiniciar.
        """
        with self._lock:
            current_path = self._model_info.model_path
            if not current_path:
                self._log("MODEL", "No hay ruta de modelo para recargar.")
                return

            self._log("MODEL", "Recargando modelo...")
            self.unload_model()
            self.load_model(current_path)

    def switch_model(self, model_path: str) -> None:
        """
        Cambia a un modelo diferente.

        Descarga el modelo actual y carga el nuevo.
        Es equivalente a unload_model() + load_model(nuevo_path).

        Args:
            model_path: ruta al nuevo archivo .gguf
        """
        with self._lock:
            self._log("MODEL", f"Cambiando a modelo: {Path(model_path).name}")
            self.unload_model()
            self.load_model(model_path)

    # ------------------------------------------------------------------
    # KV Cache Management (Personality Warmup)
    # ------------------------------------------------------------------

    def save_kv_state(self, filepath: str) -> None:
        """
        Guarda el estado binario del KV Cache (LlamaState) en disco.
        """
        with self._lock:
            if not self._model: return
            import pickle
            state = self._model.save_state()
            with open(filepath, "wb") as f:
                pickle.dump(state, f)
            self._log("MODEL", f"KV Cache guardado en {filepath}")

    def load_kv_state(self, filepath: str) -> bool:
        """
        Carga un estado binario de KV Cache si existe.
        """
        with self._lock:
            if not self._model: return False
            if not os.path.exists(filepath): return False
            try:
                import pickle
                with open(filepath, "rb") as f:
                    state = pickle.load(f)
                self._model.load_state(state)
                self._log("MODEL", f"KV Cache cargado desde {filepath}")
                return True
            except Exception as e:
                self._error(f"Error cargando KV Cache {filepath}: {e}")
                return False

    def warmup_system_prompt(self, system_prompt: str) -> None:
        """
        Pre-evalúa el system prompt para rellenar el KV Cache.
        """
        with self._lock:
            if not self._model: return
            self._log("MODEL", "Ejecutando warmup del system prompt (KV Cache)...")
            self._model.create_chat_completion(
                messages=[{"role": "system", "content": system_prompt}],
                max_tokens=1
            )
            self._log("MODEL", "Warmup completado.")

    # ------------------------------------------------------------------
    # Consultas de capacidad
    # ------------------------------------------------------------------

    def get_model_info(self) -> dict:
        """
        Retorna información detallada del modelo cargado y del hardware GPU.

        Returns:
            dict con nombre, contexto, capas GPU, VRAM estimada y estadísticas de VRAM de hardware reales
        """
        info = self._model_info
        
        # Obtener información del hardware GPU
        hw_info = {
            "cuda_available": False,
            "gpu_name": "No GPU detectado o CUDA inactivo",
            "vram_total_gb": 0.0,
            "vram_used_gb": 0.0,
            "vram_free_gb": 0.0
        }
        
        # 1. Intentar obtener con nvidia-smi
        import subprocess
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            lines = result.stdout.strip().split("\n")
            if lines and lines[0]:
                parts = [p.strip() for p in lines[0].split(",")]
                if len(parts) >= 4:
                    hw_info["cuda_available"] = True
                    hw_info["gpu_name"] = parts[0]
                    hw_info["vram_total_gb"] = round(float(parts[1]) / 1024, 2)
                    hw_info["vram_used_gb"] = round(float(parts[2]) / 1024, 2)
                    hw_info["vram_free_gb"] = round(float(parts[3]) / 1024, 2)
        except Exception:
            pass

        # 2. Si falla nvidia-smi, probar con torch por si acaso
        if not hw_info["cuda_available"]:
            try:
                import torch
                if torch.cuda.is_available():
                    hw_info["cuda_available"] = True
                    hw_info["gpu_name"] = torch.cuda.get_device_name(0)
                    try:
                        free, total = torch.cuda.mem_get_info(0)
                        hw_info["vram_total_gb"] = round(total / (1024**3), 2)
                        hw_info["vram_used_gb"] = round((total - free) / (1024**3), 2)
                        hw_info["vram_free_gb"] = round(free / (1024**3), 2)
                    except Exception:
                        pass
            except Exception:
                pass

        return {
            "model_name": info.model_name,
            "model_path": info.model_path,
            "context_size": info.context_size,
            "gpu_layers": info.gpu_layers,
            "estimated_vram": f"{info.estimated_vram_gb} GB",
            "loaded": info.loaded,
            "cuda_available": hw_info["cuda_available"],
            "gpu_name": hw_info["gpu_name"],
            "vram_total": f"{hw_info['vram_total_gb']} GB",
            "vram_used": f"{hw_info['vram_used_gb']} GB",
            "vram_free": f"{hw_info['vram_free_gb']} GB",
            "supports_tools": self.supports_tools(),
        }

    def supports_tools(self) -> bool:
        """
        Detecta si el modelo cargado soporta function calling nativo
        (OpenAI-style tool calls) revisando su chat template.

        Método: busca en la metadata del GGUF el campo
        'tokenizer.chat_template'. Si contiene 'tools' o 'functions',
        el template soporta tool calling.

        Returns:
            True si el modelo probablemente soporta tools, False si no
        """
        if not self._model:
            return False
        try:
            metadata = getattr(self._model, "metadata", None) or {}
            chat_template = metadata.get("tokenizer.chat_template", "")
            if not chat_template:
                self._log("MODEL", "No hay chat_template en metadata — tools probablemente no soportadas")
                return False
            has_tools = "tools" in chat_template.lower() or "functions" in chat_template.lower()
            self._log("MODEL", f"Chat template {'SOPORTA' if has_tools else 'NO SOPORTA'} tools (len={len(chat_template)})")
            if has_tools:
                # Mostrar snippet del template para debug
                snippet = chat_template[:200].replace('\n', ' ')
                self._log("MODEL", f"Template snippet: {snippet}")
            return has_tools
        except Exception as e:
            self._log("MODEL", f"Error leyendo metadata: {e}")
            return False

    def count_tokens(self, text: str) -> int:
        """
        Cuenta tokens exactos usando el tokenizer del modelo cargado.

        Args:
            text: texto a tokenizar

        Returns:
            cantidad de tokens
        """
        from .tokenizer_utils import count_tokens_exact, estimate_tokens

        if self._tokenize_fn is not None:
            return count_tokens_exact(text, self._tokenize_fn)
        return estimate_tokens(text)
