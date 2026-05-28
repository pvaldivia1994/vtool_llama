"""
types — Subpackage con las dataclasses compartidas, divididas por dominio.

Mantiene compatibilidad total: from vtool_llama.types import Xxx sigue funcionando.
"""

from .core import ConfigSchema, GenerationStats, Message, ModelInfo
from .character import (
    CharacterMod,
    EpisodeSnapshot,
    IdentityDNA,
    MemoryEntry,
    PersonalityDNA,
    PersonalityState,
    RelationshipState,
    RulesDNA,
    RuntimeState,
    SpeechDNA,
)
from .psychology import (
    BeliefEntry,
    CoreIdentity,
    DriftEntry,
    EmotionalMemory,
    EmotionalState,
    Genome,
    PersonaState,
    PsychologyState,
    SoulEvent,
    TurningPoint,
)

__all__ = [
    "ConfigSchema", "GenerationStats", "Message", "ModelInfo",
    "CharacterMod", "EpisodeSnapshot", "IdentityDNA", "MemoryEntry",
    "PersonalityDNA", "PersonalityState", "RelationshipState", "RulesDNA",
    "RuntimeState", "SpeechDNA",
    "BeliefEntry", "CoreIdentity", "DriftEntry", "EmotionalMemory",
    "EmotionalState", "Genome", "PersonaState", "PsychologyState",
    "SoulEvent", "TurningPoint",
]
