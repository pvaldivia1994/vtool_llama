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
    ContextOverflowError,
    CUDAUnavailableError,
    EmptyPromptError,
    InferenceError,
    InvalidModelError,
    ModelNotFoundError,
    ModelNotLoadedError,
    OOMError,
    VToolLlamaError,
)
from .engine.slash_registry import SlashCommandRegistry
from .character import CharacterManager
from .types import (
    ConfigSchema,
    GenerationStats,
    Message,
    ModelInfo,
    IdentityDNA,
    PersonalityDNA,
    SpeechDNA,
    RulesDNA,
    MemoryEntry,
    RuntimeState,
    RelationshipState,
    PersonalityState,
    CharacterMod,
    # v2 types
    Genome,
    SoulEvent,
    BeliefEntry,
    CoreIdentity,
    TurningPoint,
    EmotionalMemory,
    PsychologyState,
    EmotionalState,
    PersonaState,
    DriftEntry,
)
from .soul import SoulGenerator, RuntimeSoulAccessor
from .psychology import (
    PsychologySynthesizer,
    EmotionalDynamics,
    DriftDetector,
    BeliefManager,
    RuntimeSoulManager,
    dna_traits_to_genome,
)

# Versión de la librería (semver)
__version__ = "0.3.0"

# Exportar la API pública
__all__ = [
    # Clase principal
    "VToolLlama",
    # Sistema de agente
    "CharacterManager",
    "SlashCommandRegistry",
    # Soul System
    "SoulGenerator",
    "RuntimeSoulAccessor",
    # Psychology Engine v2
    "PsychologySynthesizer",
    "EmotionalDynamics",
    "DriftDetector",
    "BeliefManager",
    "RuntimeSoulManager",
    "dna_traits_to_genome",
    # Excepciones
    "VToolLlamaError",
    "ModelNotFoundError",
    "InvalidModelError",
    "CUDAUnavailableError",
    "OOMError",
    "EmptyPromptError",
    "ConfigError",
    "ContextOverflowError",
    "InferenceError",
    "ModelNotLoadedError",
    # Tipos
    "ConfigSchema",
    "Message",
    "ModelInfo",
    "GenerationStats",
    "IdentityDNA",
    "PersonalityDNA",
    "SpeechDNA",
    "RulesDNA",
    "MemoryEntry",
    "RuntimeState",
    "RelationshipState",
    "PersonalityState",
    "CharacterMod",
    # Tipos v2
    "Genome",
    "SoulEvent",
    "BeliefEntry",
    "CoreIdentity",
    "TurningPoint",
    "EmotionalMemory",
    "PsychologyState",
    "EmotionalState",
    "PersonaState",
    "DriftEntry",
    # Metadatos
    "__version__",
]
