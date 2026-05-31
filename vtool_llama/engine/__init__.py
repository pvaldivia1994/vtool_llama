"""
engine — Subpackage con la clase VToolLlama dividida por dominio.

Los métodos se asignan a VToolLlama desde módulos hermanos para
mantener cada archivo en ~300-500 LOC.
"""

from .base import VToolLlama

# Import submodules to register methods onto VToolLlama
from . import internal     # noqa: F401
from . import chat         # noqa: F401
from . import character    # noqa: F401
from . import memory       # noqa: F401
from . import slash_commands  # noqa: F401
from . import inline          # noqa: F401

__all__ = ["VToolLlama"]
