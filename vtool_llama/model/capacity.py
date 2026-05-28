"""capacity.py — Consultas de capacidad y metadata del modelo."""

from __future__ import annotations

from .manager import ModelManager


def get_model_info(self: ModelManager) -> dict:
    info = self._model_info

    hw_info = {
        "cuda_available": False,
        "gpu_name": "No GPU detectado o CUDA inactivo",
        "vram_total_gb": 0.0,
        "vram_used_gb": 0.0,
        "vram_free_gb": 0.0,
    }

    import subprocess
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
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

ModelManager.get_model_info = get_model_info


def supports_tools(self: ModelManager) -> bool:
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
            snippet = chat_template[:200].replace('\n', ' ')
            self._log("MODEL", f"Template snippet: {snippet}")
        return has_tools
    except Exception as e:
        self._log("MODEL", f"Error leyendo metadata: {e}")
        return False

ModelManager.supports_tools = supports_tools


def count_tokens(self: ModelManager, text: str) -> int:
    from ..engine.tokenizer_utils import count_tokens_exact, estimate_tokens

    if self._tokenize_fn is not None:
        return count_tokens_exact(text, self._tokenize_fn)
    return estimate_tokens(text)

ModelManager.count_tokens = count_tokens
