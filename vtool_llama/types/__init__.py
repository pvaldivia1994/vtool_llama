"""
types — Subpackage con las dataclasses compartidas, divididas por dominio.

Mantiene compatibilidad total: from vtool_llama.types import Xxx sigue funcionando.
"""

from .chat import (
    Branch,
    ChatMessage,
    Conversation,
    ConversationSummary,
    PromptSection,
    SemanticMemory,
)
from .core import ConfigSchema, GenerationStats, Message, ModelInfo
from .character import (
    CharacterLoadResult,
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
    "Branch", "ChatMessage", "Conversation", "ConversationSummary",
    "PromptSection", "SemanticMemory",
    "ConfigSchema", "GenerationStats", "Message", "ModelInfo",
    "CharacterLoadResult", "CharacterMod", "EpisodeSnapshot",
    "IdentityDNA", "MemoryEntry", "PersonalityDNA", "PersonalityState",
    "RelationshipState", "RulesDNA", "RuntimeState", "SpeechDNA",
    "BeliefEntry", "CoreIdentity", "DriftEntry", "EmotionalMemory",
    "EmotionalState", "Genome", "PersonaState", "PsychologyState",
    "SoulEvent", "TurningPoint",
]
