"""
model — Subpackage con ModelManager dividido por responsabilidad.
"""

from .manager import ModelManager

from . import model_ops  # noqa: F401
from . import inference  # noqa: F401
from . import kv_cache   # noqa: F401
from . import capacity   # noqa: F401

__all__ = ["ModelManager"]
