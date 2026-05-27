"""
Tipos compartidos y dataclasses para vtool_llama.

Centraliza las estructuras de datos que usan varios módulos
para evitar importaciones circulares y mantener consistencia.

Incluye:
- Message: un mensaje individual del historial (rol + contenido)
- ModelInfo: metadatos del modelo cargado
- ConfigSchema: estructura esperada del config.json
- GenerationStats: estadísticas de una inferencia
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Message:
    """
    Representa un mensaje individual en el historial.

    Atributos:
        role: 'system' | 'user' | 'assistant' | 'tool'
        content: texto del mensaje (opcional si hay tool_calls)
        tool_calls: lista de llamadas a herramientas dict (opcional)
        tool_call_id: ID de la llamada a la herramienta si es un mensaje de respuesta del tool (opcional)
    """
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list[dict]] = None
    tool_call_id: Optional[str] = None


@dataclass
class ModelInfo:
    """
    Metadatos del modelo actualmente cargado.

    Se llena después de load_model() exitoso y se consulta
    con get_model_info().

    Atributos:
        model_name: nombre descriptivo (ej: "Qwen3 8B")
        model_path: ruta absoluta al .gguf
        context_size: n_ctx configurado
        gpu_layers: capas en GPU (-1 = todas)
        estimated_vram_gb: VRAM estimada en GB
        loaded: si el modelo está en memoria
    """
    model_name: str = "No cargado"
    model_path: str = ""
    context_size: int = 4096
    gpu_layers: int = -1
    estimated_vram_gb: float = 0.0
    loaded: bool = False


@dataclass
class GenerationStats:
    """
    Estadísticas de una generación individual.

    Se genera después de cada llamada a chat() o stream_chat().

    Atributos:
        prompt_tokens: tokens de entrada
        completion_tokens: tokens generados
        total_tokens: suma de ambos
        tokens_per_second: velocidad de generación
        duration_ms: tiempo total en milisegundos
        model_name: modelo usado
    """
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tokens_per_second: float = 0.0
    duration_ms: float = 0.0
    model_name: str = ""


@dataclass
class ConfigSchema:
    """
    Esquema tipado del config.json.

    Todos los valores tienen defaults para que el sistema
    funcione incluso con un config.json mínimo.
    """
    debug: bool = True
    python_path: str = "C:/Users/LiuniK/AppData/Local/Python/pythoncore-3.14-64"
    models_directory: str = "C:/_IA/_llama_models"
    default_model: str = "Qwen3-8B-Q4_K_M.gguf"
    system_prompt: str = "Eres un asistente útil y natural."
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
