"""
soul — Subpackage con el Soul System dividido por fase de generación.
"""

from .soul_generator import SoulGenerator
from .accessor import RuntimeSoulAccessor

# Register phase methods onto SoulGenerator
from . import initialization  # noqa: F401
from . import events          # noqa: F401
from . import simulation      # noqa: F401
from . import reflection      # noqa: F401
from . import compression     # noqa: F401

__all__ = ["SoulGenerator", "RuntimeSoulAccessor"]
