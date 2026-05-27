"""
Tipos compartidos y dataclasses para vtool_llama.

Centraliza las estructuras de datos que usan varios módulos
para evitar importaciones circulares y mantener consistencia.

Incluye:
- Message: un mensaje individual del historial (rol + contenido)
- ModelInfo: metadatos del modelo cargado
- ConfigSchema: estructura esperada del config.json
- GenerationStats: estadísticas de una inferencia
- PersonalityState: estado base de identidad y estilo del agente
- RelationshipState: relación del personaje con el usuario
- MemoryEntry: una memoria persistente individual
- MoodState: estado emocional de corto plazo
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional


# ======================================================================
# CHARACTER SYSTEM TYPES (DNA, STATE, MEMORY, MODS)
# ======================================================================

# --- DNA (Inmutable) ---

@dataclass
class IdentityDNA:
    name: str = ""
    role: str = ""
    age: str = "Desconocida"
    background: str = ""
    scenario: str = "Una IA creada para ayudar."

@dataclass
class PersonalityDNA:
    traits: list[str] = field(default_factory=list)
    flaws: list[str] = field(default_factory=list)
    motivations: list[str] = field(default_factory=list)

@dataclass
class SpeechDNA:
    style: str = ""
    verbosity: str = ""
    tone: str = ""
    emotions: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

@dataclass
class RulesDNA:
    core_rules: list[str] = field(default_factory=list)
    never_do: list[str] = field(default_factory=list)
    response_style: list[str] = field(default_factory=list)
    roleplay_mode: bool = False

# --- Memory ---

@dataclass
class MemoryEntry:
    """
    Una memoria persistente individual (long term).
    """
    id: str = ""
    content: str = ""
    priority: float = 0.5
    always_include: bool = False
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:8]

@dataclass
class EpisodeSnapshot:
    """
    Snapshot de memoria episódica (corto plazo versionada).
    
    Cada episodio almacena un resumen generado por LLM y los
    últimos N mensajes de la conversación. Se guarda como archivo
    independiente (episode_001.json, episode_002.json, etc.) 
    para permitir rollback y recuperación de estados anteriores.
    """
    episode_id: int = 0
    timestamp: str = ""
    summary: str = ""
    messages: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.timestamp:
            from datetime import datetime
            self.timestamp = datetime.now().isoformat()

# --- State (Runtime Cache) ---

@dataclass
class RuntimeState:
    """
    Estado en tiempo real de la sesión (mood actual, confianza, contexto).
    """
    current_emotion: str = "neutral"
    active_context: str = ""
    version: int = 0

@dataclass
class RelationshipState:
    """
    Memoria afectiva y evolución relacional con el usuario.
    """
    trust_level: float = 0.5
    familiarity: float = 0.0
    affective_memory: list[str] = field(default_factory=list)
    dynamics: list[str] = field(default_factory=list)
    version: int = 0

@dataclass
class PersonalityState:
    """
    Resumen dinámico del DNA + Memory que se inyecta al prompt.
    """
    base_personality: str = ""
    emotional_signature: dict[str, str] = field(default_factory=lambda: {"default": "neutral"})
    user_model: dict[str, float] = field(default_factory=lambda: {"trust_level": 0.5})
    behavior_summary: str = ""
    memory_summary: str = ""
    tool_affinity: list[str] = field(default_factory=list)
    version: int = 0

# --- Mods ---

@dataclass
class CharacterMod:
    """
    Modificador temporal que altera el personaje sin cambiar el DNA.
    """
    id: str = "mood_mod"
    target_layer: str = "speech"
    override_value: str = ""
    intensity: float = 1.0


# ======================================================================
# ORIGINAL TYPES
# ======================================================================


@dataclass
class Message:
    """
    Representa un mensaje individual en el historial.

    Atributos:
        role: 'system' | 'user' | 'assistant' | 'tool'
        content: texto del mensaje (opcional si hay tool_calls)
        tool_calls: lista de llamadas a herramientas dict (opcional)
        tool_call_id: ID de la llamada a la herramienta si es un mensaje de respuesta del tool (opcional)
    """
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list[dict]] = None
    tool_call_id: Optional[str] = None


@dataclass
class ModelInfo:
    """
    Metadatos del modelo actualmente cargado.

    Se llena después de load_model() exitoso y se consulta
    con get_model_info().

    Atributos:
        model_name: nombre descriptivo (ej: "Qwen3 8B")
        model_path: ruta absoluta al .gguf
        context_size: n_ctx configurado
        gpu_layers: capas en GPU (-1 = todas)
        estimated_vram_gb: VRAM estimada en GB
        loaded: si el modelo está en memoria
    """
    model_name: str = "No cargado"
    model_path: str = ""
    context_size: int = 4096
    gpu_layers: int = -1
    estimated_vram_gb: float = 0.0
    loaded: bool = False


@dataclass
class GenerationStats:
    """
    Estadísticas de una generación individual.

    Se genera después de cada llamada a chat() o stream_chat().

    Atributos:
        prompt_tokens: tokens de entrada
        completion_tokens: tokens generados
        total_tokens: suma de ambos
        tokens_per_second: velocidad de generación
        duration_ms: tiempo total en milisegundos
        model_name: modelo usado
    """
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tokens_per_second: float = 0.0
    duration_ms: float = 0.0
    model_name: str = ""


@dataclass
class ConfigSchema:
    """
    Esquema tipado del config.json.

    Todos los valores tienen defaults para que el sistema
    funcione incluso con un config.json mínimo.
    """
    debug: bool = True
    python_path: str = "C:/Users/LiuniK/AppData/Local/Python/pythoncore-3.14-64"
    models_directory: str = "C:/_IA/_llama_models"
    default_model: str = "Qwen3-8B-Q4_K_M.gguf"
    system_prompt: str = "Eres un asistente útil y natural."
    n_ctx: int = 4096
    n_batch: int = 512
    gpu_layers: int = -1
    threads: int = 8
    flash_attn: bool = True
    temperature: float = 0.8
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.1
    max_tokens: int = 512
    seed: int = -1
    stream: bool = True
    enable_logging: bool = True
    enable_console_debug: bool = False
    history_limit: int = 40
    auto_trim_context: bool = True
    context_reserve_tokens: int = 800
    model_idle_timeout: int = 600
    auto_unload_model: bool = False
    short_memory_limit: int = 5
