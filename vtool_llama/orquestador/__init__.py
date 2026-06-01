"""
orquestador — Sistema de inyección de contexto conversacional.

Permite agregar entradas de contexto persistentes que se inyectan
automáticamente en el prompt del personaje en cada turno.

Tipos de contexto disponibles:
  character  → Estado emocional del personaje
  time       → Momento del día, clima, estación
  thoughts   → Pensamientos internos del personaje
  world      → Eventos del entorno, ambiente
  scene      → Descripción de escena (desde /scene_view)
  custom     → Contexto definido por el usuario
"""

from .context_injector import (
    CONTEXT_DEFINITIONS,
    CONTEXT_HEADER,
    CONTEXT_TYPES,
    ContextEntry,
    ContextInjector,
)
from .strategies import ContextInjectionStrategy, SceneContextStrategy

# Tags legacy — mantenidos para compatibilidad
from .tags import (
    SAYS, DOES, THINKS,
    DEFINE, STATE, SCENE,
    CONTENT_TAGS, SYSTEM_TAGS,
)

__all__ = [
    "CONTEXT_DEFINITIONS", "CONTEXT_HEADER", "CONTEXT_TYPES",
    "ContextEntry", "ContextInjector",
    "ContextInjectionStrategy", "SceneContextStrategy",
    "SAYS", "DOES", "THINKS",
    "DEFINE", "STATE", "SCENE",
    "CONTENT_TAGS", "SYSTEM_TAGS",
]
