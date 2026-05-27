"""
Utilidades de tokenización para vtool_llama.

Provee funciones auxiliares para:
- Estimar tokens de un texto sin tener el modelo cargado
- Contar tokens exactos cuando el modelo está disponible
- Determinar si el contexto está cerca del límite
- Sugerir configuraciones seguras según VRAM disponible

Todas las funciones son independientes del modelo real
cuando se usan en modo estimación, y se conectan al
tokenizer del modelo cuando está disponible.
"""

from __future__ import annotations

import math
from typing import Callable, Optional


# Factor de conversión aproximado: 1 token ≈ 4 caracteres para
# español/inglés. Es una estimación conservadora usada cuando
# el modelo aún no está cargado.
_CHARS_PER_TOKEN_ESTIMATE = 4.0


def estimate_tokens(text: str) -> int:
    """
    Estima la cantidad de tokens de un texto sin usar el modelo.

    Útil antes de cargar el modelo para decidir si el contexto
    va a entrar en n_ctx. La estimación es 1 token cada ~4
    caracteres.

    Args:
        text: texto a estimar

    Returns:
        cantidad estimada de tokens (entero)
    """
    if not text or not text.strip():
        return 0
    return max(1, math.ceil(len(text) / _CHARS_PER_TOKEN_ESTIMATE))


def count_tokens_exact(text: str, tokenize_fn: Callable[[str], list[int]]) -> int:
    """
    Cuenta tokens exactos usando la función de tokenización
    del modelo cargado.

    Args:
        text: texto a tokenizar
        tokenize_fn: función que recibe string y retorna
                     lista de ids de tokens (ej: model.tokenize)

    Returns:
        cantidad exacta de tokens
    """
    if not text or not text.strip():
        return 0
    try:
        tokens = tokenize_fn(text)
        return len(tokens)
    except Exception:
        # Fallback a estimación si falla la tokenización
        return estimate_tokens(text)


def context_usage_percent(
    current_tokens: int,
    max_tokens: int,
) -> float:
    """
    Calcula el porcentaje de uso del contexto.

    Args:
        current_tokens: tokens actuales en el contexto
        max_tokens: límite máximo (n_ctx)

    Returns:
        porcentaje de uso (0.0 a 100.0)
    """
    if max_tokens <= 0:
        return 0.0
    return min(100.0, (current_tokens / max_tokens) * 100.0)


def is_context_near_limit(
    current_tokens: int,
    max_tokens: int,
    reserve_tokens: int = 800,
    threshold_percent: float = 85.0,
) -> bool:
    """
    Determina si el contexto está peligrosamente cerca del límite.

    Args:
        current_tokens: tokens actuales
        max_tokens: n_ctx configurado
        reserve_tokens: tokens a reservar para la respuesta
        threshold_percent: porcentaje para considerar "cerca"

    Returns:
        True si hay que hacer trim pronto
    """
    effective_limit = max_tokens - reserve_tokens
    if effective_limit <= 0:
        return True

    usage = context_usage_percent(current_tokens, max_tokens)
    return usage >= threshold_percent


def suggest_gpu_layers(vram_gb: float, model_size_gb: float) -> int:
    """
    Sugiere cuántas capas enviar a GPU según VRAM disponible.

    Para RTX 3050 8GB, esto ayuda a encontrar el balance entre
    velocidad y estabilidad.

    Args:
        vram_gb: VRAM total disponible en GB
        model_size_gb: tamaño aproximado del modelo GGUF

    Returns:
        cantidad de capas recomendadas para GPU
        (-1 significa "todas")
    """
    # Si la VRAM es holgada para el modelo, usar todas las capas
    if vram_gb >= model_size_gb * 1.3:
        return -1  # todas las capas en GPU

    # Si la VRAM es ajustada, calcular proporción
    ratio = vram_gb / model_size_gb
    if ratio >= 0.8:
        return -1  # suficiente margen

    if ratio >= 0.5:
        # ~70% de capas en GPU para dejar margen al contexto
        return 999  # dejar que llama.cpp decida

    # Poco margen: ~40% de capas en GPU
    return 999  # delegar a llama.cpp


def estimate_vram_for_model(
    model_size_gb: float,
    context_tokens: int,
    gpu_layers_ratio: float = 1.0,
) -> float:
    """
    Estima el consumo de VRAM para un modelo dado.

    Fórmula simplificada:
      VRAM ≈ parámetros_en_gpu * 2GB (FP16) + overhead de contexto

    Args:
        model_size_gb: tamaño del archivo GGUF en GB
        context_tokens: n_ctx configurado
        gpu_layers_ratio: proporción de capas en GPU (0.0 a 1.0)

    Returns:
        VRAM estimada en GB
    """
    # El tamaño del modelo en memoria es mayor que el archivo GGUF
    # por el overhead de descompresión y kv_cache
    model_memory = model_size_gb * 1.2 * gpu_layers_ratio

    # KV cache: ~2 bytes por token por capa por atención
    # Aproximación: ~0.5GB por cada 4096 tokens de contexto
    kv_cache_gb = (context_tokens / 4096) * 0.5 * gpu_layers_ratio

    # Overhead del runtime
    runtime_overhead = 0.3  # 300MB fijo

    return round(model_memory + kv_cache_gb + runtime_overhead, 1)


def safe_context_size_for_vram(
    vram_gb: float,
    model_size_gb: float,
    gpu_layers: int = -1,
) -> int:
    """
    Sugiere un n_ctx seguro para la VRAM disponible.

    Args:
        vram_gb: VRAM total
        model_size_gb: tamaño del GGUF
        gpu_layers: capas en GPU (-1 = todas)

    Returns:
        n_ctx recomendado (múltiplo de 512)
    """
    # Calcular capas en GPU como proporción
    if gpu_layers == -1:
        ratio = 1.0
    else:
        ratio = min(1.0, gpu_layers / 80.0)  # asumir ~80 capas

    model_usage = model_size_gb * 1.2 * ratio
    remaining = vram_gb - model_usage - 0.5  # 0.5GB de margen

    if remaining <= 0:
        return 1024  # contexto mínimo

    # Cada 4096 tokens consume ~0.5GB en kv_cache
    safe_ctx = int((remaining / 0.5) * 4096)

    # Redondear a múltiplo de 512
    safe_ctx = max(512, (safe_ctx // 512) * 512)

    return min(safe_ctx, 32768)  # cap en 32K
