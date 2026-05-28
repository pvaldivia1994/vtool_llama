"""
db — Módulo de almacenamiento de datos.

Incluye acceso a base de datos vectorial (ChromaDB),
utilidades de I/O para archivos, y tipos relacionados
con persistencia.
"""

from .chroma_store import ChromaStore, HAS_CHROMA
from . import io

__all__ = ["ChromaStore", "HAS_CHROMA", "io"]
