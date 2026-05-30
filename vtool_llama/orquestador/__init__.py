"""
orquestador — Sistema de inyección de contexto conversacional.

Permite agregar entradas de contexto persistentes que se inyectan
automáticamente en el prompt del personaje en cada turno.

Tipos de contexto disponibles:
  character  → [CHARACTER] Estado emocional del personaje
  time       → [TIME] Momento del día, clima, estación
  thoughts   → [THOUGHTS] Pensamientos internos del personaje
  world      → [WORLD] Eventos del entorno, ambiente
  scene      → [ESCENA] Descripción de escena (desde /scene_view)
  custom     → [CUSTOM] Contexto definido por el usuario
"""

from .context_injector import (
    CONTEXT_DEFINITIONS,
    CONTEXT_HEADER,
    CONTEXT_TYPES,
    ContextEntry,
    ContextInjector,
)
from .strategies import ContextInjectionStrategy, SceneContextStrategy

__all__ = [
    "CONTEXT_DEFINITIONS", "CONTEXT_HEADER", "CONTEXT_TYPES",
    "ContextEntry", "ContextInjector",
    "ContextInjectionStrategy", "SceneContextStrategy",
]
