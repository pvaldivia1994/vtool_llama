"""model_ops.py — Carga, descarga, recarga y listado de modelos."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .manager import ModelManager
from ..exceptions import (
    InferenceError,
    InvalidModelError,
    ModelNotFoundError,
    OOMError,
)
from ..types import ModelInfo


def _resolve_model_path(self: ModelManager, model_path: Optional[str] = None) -> Path:
    if model_path:
        path = Path(model_path)
        if path.is_absolute():
            return path
        return Path(self._config.models_directory) / path
    base = Path(self._config.models_directory)
    return base / self._config.default_model

ModelManager._resolve_model_path = _resolve_model_path


def list_available_models(self: ModelManager) -> list[dict[str, str]]:
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

ModelManager.list_available_models = list_available_models


def load_model(self: ModelManager, model_path: Optional[str] = None,
               n_ctx_override: Optional[int] = None) -> None:
    with self._lock:
        if self._loading:
            self._log("MODEL", "Ya hay una carga en progreso, ignorando...")
            return

        self._loading = True
        path = self._resolve_model_path(model_path)

        try:
            self._validate_model_path(path)
            self._log("MODEL", f"Cargando modelo: {path.name}")

            cuda_available = self._check_cuda()
            kwargs = self._build_llama_kwargs(path, cuda_available, n_ctx_override=n_ctx_override)

            try:
                from llama_cpp import Llama
            except ImportError as e:
                raise ImportError(
                    "llama-cpp-python no está instalado. "
                    "Ejecuta: pip install llama-cpp-python"
                ) from e

            self._log("MODEL", "Inicializando modelo (esto puede tomar varios segundos)...")

            try:
                model = Llama(**kwargs)
            except Exception as e:
                error_msg = str(e).lower()

                if any(term in error_msg for term in [
                    "out of memory", "cuda out of", "cuda error",
                    "memory", "alloc", "vram",
                ]):
                    raise OOMError(
                        f"Memoria insuficiente para cargar {path.name} "
                        f"con la configuración actual. "
                        f"Intenta reducir n_ctx o gpu_layers."
                    ) from e

                if any(term in error_msg for term in [
                    "invalid", "corrupt", "format", "magic",
                    "not a llama", "gguf",
                ]):
                    raise InvalidModelError(
                        f"El archivo {path.name} no es un GGUF válido "
                        f"o está corrupto: {e}"
                    ) from e

                raise InferenceError(f"Error al cargar el modelo: {e}") from e

            self._model = model
            self._n_keep = None  # nuevo modelo, nuevo core
            # Guardar n_ctx del usuario la primera vez (no sobrescribir en recargas)
            if self._user_n_ctx == 0:
                self._user_n_ctx = self._config.n_ctx
            self._model_info = self._build_model_info(path)

            if hasattr(model, "tokenize"):
                self._tokenize_fn = model.tokenize
            elif hasattr(model, "tokenizer"):
                self._tokenize_fn = model.tokenizer.encode

            self._log("MODEL", f"Modelo cargado: {self._model_info.model_name}")
            self._log("MODEL", f"Contexto: {self._model_info.context_size} tokens")
            self._log("GPU", f"Capas GPU: {self._model_info.gpu_layers}")
            self._log("GPU", f"VRAM estimada: {self._model_info.estimated_vram_gb} GB")

        finally:
            self._loading = False

ModelManager.load_model = load_model


def _validate_model_path(self: ModelManager, path: Path) -> None:
    if not path.exists():
        raise ModelNotFoundError(
            f"Modelo no encontrado: {path}\n"
            f"Verifica la ruta en config.json o proporciona una válida."
        )

    if not path.is_file():
        raise InvalidModelError(f"La ruta {path} no es un archivo.")

    extension = path.suffix.lower()
    if extension != ".gguf":
        self._log("MODEL", f"Advertencia: extensión '{extension}' no es .gguf")

ModelManager._validate_model_path = _validate_model_path


def _check_cuda(self: ModelManager) -> bool:
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

ModelManager._check_cuda = _check_cuda


def _build_llama_kwargs(self: ModelManager, path: Path, cuda_available: bool,
                         n_ctx_override: Optional[int] = None) -> dict:
    n_ctx = n_ctx_override if n_ctx_override is not None else self._config.n_ctx
    kwargs = {
        "model_path": str(path),
        "n_ctx": n_ctx,
        "n_batch": self._config.n_batch,
        "n_threads": self._config.threads,
        "flash_attn": self._config.flash_attn,
        "verbose": False,
    }

    if cuda_available:
        kwargs["n_gpu_layers"] = self._config.gpu_layers
        self._log("GPU", f"Usando GPU con n_gpu_layers={self._config.gpu_layers}")
    else:
        kwargs["n_gpu_layers"] = 0
        self._log("GPU", "Modo CPU: todas las capas en CPU")

    kwargs["temperature"] = self._config.temperature
    kwargs["top_p"] = self._config.top_p
    kwargs["top_k"] = self._config.top_k
    kwargs["repeat_penalty"] = self._config.repeat_penalty

    if self._config.seed != -1:
        kwargs["seed"] = self._config.seed

    self._log("CONFIG", f"n_ctx={kwargs['n_ctx']}, n_batch={kwargs['n_batch']}")
    self._log("CONFIG", f"threads={kwargs['n_threads']}, gpu_layers={kwargs.get('n_gpu_layers', 0)}")

    return kwargs

ModelManager._build_llama_kwargs = _build_llama_kwargs


def _build_model_info(self: ModelManager, path: Path) -> ModelInfo:
    model_name = self._extract_model_name(path)

    file_size_gb = path.stat().st_size / (1024 ** 3)
    estimated_vram = round(file_size_gb * 1.4, 1)

    return ModelInfo(
        model_name=model_name,
        model_path=str(path),
        context_size=self._config.n_ctx,
        gpu_layers=self._config.gpu_layers,
        estimated_vram_gb=estimated_vram,
        loaded=True,
    )

ModelManager._build_model_info = _build_model_info


def _extract_model_name(self: ModelManager, path: Path) -> str:
    try:
        if self._model is not None:
            metadata = getattr(self._model, "metadata", None)
            if metadata:
                for key in ["general.name", "llama.model_name", "model.name"]:
                    if key in metadata:
                        return str(metadata[key])

            model_type = getattr(self._model, "model_type", None)
            if model_type:
                return f"{model_type}"
    except Exception:
        pass

    name = path.stem
    for suffix in ["-Q4_K_M", "-Q4_K_S", "-Q5_K_M", "-Q5_K_S",
                   "-Q6_K", "-Q8_0", "-F16", "-BF16",
                   ".Q4_K_M", ".Q4_K_S", ".Q5_K_M"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name

ModelManager._extract_model_name = _extract_model_name


def unload_model(self: ModelManager) -> None:
    with self._lock:
        if self._model is None:
            self._log("MODEL", "No hay modelo cargado para descargar.")
            return

        model_name = self._model_info.model_name
        self._log("MODEL", f"Descargando modelo: {model_name}")

        self._model = None
        self._tokenize_fn = None
        self._model_info = ModelInfo()
        self._n_keep = None  # el core se pierde al descargar el modelo

        import gc
        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                self._log("GPU", "Cache de CUDA liberada")
        except ImportError:
            pass

        self._log("MODEL", f"Modelo {model_name} descargado correctamente")

ModelManager.unload_model = unload_model


def reload_model(self: ModelManager) -> None:
    with self._lock:
        current_path = self._model_info.model_path
        if not current_path:
            self._log("MODEL", "No hay ruta de modelo para recargar.")
            return

        self._log("MODEL", "Recargando modelo...")
        self.unload_model()
        self.load_model(current_path)

ModelManager.reload_model = reload_model


def reload_model_with_expanded_ctx(self: ModelManager, expanded_n_ctx: int) -> None:
    """Recarga el modelo con un n_ctx mayor para hacer el core invisible.

    Solo debe llamarse desde _warmup_character_cache() cuando
    expand_n_ctx_for_core=True y se acaba de medir n_keep.
    """
    with self._lock:
        current_path = self._model_info.model_path
        if not current_path:
            self._log("MODEL", "No hay ruta de modelo para recargar.")
            return

        self._log("MODEL", f"Recargando con n_ctx expandido a {expanded_n_ctx} "
                  f"(core {expanded_n_ctx - self._user_n_ctx} + user {self._user_n_ctx})")
        self.unload_model()
        self.load_model(current_path, n_ctx_override=expanded_n_ctx)
        self._core_expanded = True

ModelManager.reload_model_with_expanded_ctx = reload_model_with_expanded_ctx


def switch_model(self: ModelManager, model_path: str) -> None:
    with self._lock:
        self._log("MODEL", f"Cambiando a modelo: {Path(model_path).name}")
        self.unload_model()
        self.load_model(model_path)

ModelManager.switch_model = switch_model
