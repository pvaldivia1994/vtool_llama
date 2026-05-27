"""
vtool_llama — Librería de IA conversacional local para Windows.

Motor modular y reutilizable para usar modelos GGUF locales
(Llama, Qwen, Gemma, Mistral, DeepSeek, etc.) mediante
llama-cpp-python.

Uso básico:
    from vtool_llama import VToolLlama

    llm = VToolLlama()

    respuesta = llm.chat("Hola")
    print(respuesta)

    for token in llm.stream_chat("Explícame Python"):
        print(token, end="")

Requiere:
    - Python 3.11+
    - llama-cpp-python con soporte CUDA
    - Un modelo GGUF compatible
"""

from __future__ import annotations

from .engine import VToolLlama
from .exceptions import (
    ConfigError,
    CUDAUnavailableError,
    EmptyPromptError,
    InferenceError,
    InvalidModelError,
    ModelNotFoundError,
    ModelNotLoadedError,
    OOMError,
    VToolLlamaError,
)
from .types import ConfigSchema, GenerationStats, Message, ModelInfo

# Versión de la librería (semver)
__version__ = "0.1.0"

# Exportar la API pública
__all__ = [
    # Clase principal
    "VToolLlama",
    # Excepciones
    "VToolLlamaError",
    "ModelNotFoundError",
    "InvalidModelError",
    "CUDAUnavailableError",
    "OOMError",
    "EmptyPromptError",
    "ConfigError",
    "InferenceError",
    "ModelNotLoadedError",
    # Tipos
    "ConfigSchema",
    "Message",
    "ModelInfo",
    "GenerationStats",
    # Metadatos
    "__version__",
]
