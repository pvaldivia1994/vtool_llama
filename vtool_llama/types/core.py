"""
Tipos base del sistema: configuración, modelo, mensajes y estadísticas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Message:
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list[dict]] = None
    tool_call_id: Optional[str] = None


@dataclass
class ModelInfo:
    model_name: str = "No cargado"
    model_path: str = ""
    context_size: int = 4096
    gpu_layers: int = -1
    estimated_vram_gb: float = 0.0
    loaded: bool = False


@dataclass
class GenerationStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tokens_per_second: float = 0.0
    duration_ms: float = 0.0
    model_name: str = ""


@dataclass
class ConfigSchema:
    debug: bool = True
    python_path: str = "C:/Users/LiuniK/AppData/Local/Python/pythoncore-3.14-64"
    models_directory: str = "C:/_IA/_llama_models"
    default_model: str = "Qwen3-8B-Q4_K_M.gguf"
    system_prompt: str = "You are a natural conversational partner."
    n_ctx: int = 4096
    n_batch: int = 512
    gpu_layers: int = -1
    threads: int = 8
    flash_attn: bool = True
    temperature: float = 0.8
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.1
    max_tokens: int = 512
    seed: int = -1
    stream: bool = True
    enable_logging: bool = True
    enable_console_debug: bool = False
    history_limit: int = 40
    auto_trim_context: bool = True
    context_reserve_tokens: int = 800
    model_idle_timeout: int = 600
    auto_unload_model: bool = False
    short_memory_limit: int = 5
    chat_memory_retrieval_limit: int = 3
    characters_directory: str = ""
    chat_memory_limit: int = 25
    auto_summary_interval: int = 10
    auto_summary_reason: str = "interval"
    semantic_memory_enabled: bool = False
    context_snapshot_debug: bool = False
