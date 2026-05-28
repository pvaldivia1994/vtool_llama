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
    inner_conflict: str = ""
    emotional_triggers: list[str] = field(default_factory=list)

@dataclass
class SpeechDNA:
    style: str = ""
    verbosity: str = ""
    tone: str = ""
    emotions: list[str] = field(default_factory=list)
    speech_patterns: list[str] = field(default_factory=list)
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
# ARCHITECTURE V2 — GENOME / SOUL / PSYCHOLOGY / PERSONA
# ======================================================================

@dataclass
class Genome:
    """
    Temperamento innato. NO cambia con la vida.
    Son predisposiciones biológicas, NO rasgos de personalidad final.

    Cada eje es 0.0 a 1.0. 0.5 = promedio.

    Se authored como genome.json o se deriva de PersonalityDNA.traits
    si el archivo no existe (backward compat).
    """
    sociability: float = 0.5
    emotional_sensitivity: float = 0.5
    impulsivity: float = 0.5
    risk_aversion: float = 0.5
    empathy: float = 0.5
    curiosity: float = 0.5
    security_need: float = 0.5
    independence: float = 0.5
    creativity: float = 0.5
    aggression: float = 0.5
    emotional_regulation: float = 0.5
    persistence: float = 0.5
    playfulness: float = 0.5


@dataclass
class CoreIdentity:
    """
    Capa de identidad profunda: cómo el personaje INTERPRETA las experiencias.

    No es un trait. Es el filtro perceptual y narrativo que determina
    cómo un evento se convierte en psicología.

    Misma experiencia + distinta CoreIdentity = distinta persona.

    Se forma durante la simulación del alma y evoluciona con turning points.
    """
    core_fears: list[str] = field(default_factory=list)
    core_desires: list[str] = field(default_factory=list)
    shame_sources: list[str] = field(default_factory=list)
    emotional_needs: dict[str, float] = field(default_factory=lambda: {
        "safety": 0.5, "belonging": 0.5, "esteem": 0.5,
        "autonomy": 0.5, "meaning": 0.5,
    })
    self_narrative: str = ""
    meaning_system: dict[str, float] = field(default_factory=lambda: {
        "people_are_good": 0.5, "world_is_fair": 0.5,
        "i_have_control": 0.5, "life_has_purpose": 0.5,
    })
    interpretation_biases: dict[str, float] = field(default_factory=lambda: {
        "internalize_blame": 0.5,
        "externalize_blame": 0.5,
        "catastrophize": 0.5,
        "minimize": 0.5,
        "personalize": 0.5,
        "mind_read_negative": 0.5,
    })

    # Creencias nucleares sobre sí mismo (formato: "creencia": fuerza 0-1)
    self_beliefs: dict[str, float] = field(default_factory=lambda: {
        "i_am_lovable": 0.5,
        "i_am_capable": 0.5,
        "i_am_safe": 0.5,
        "i_belong": 0.5,
        "i_am_good": 0.5,
        "must_appear_confident": 0.5,
    })

    def to_prompt_block(self) -> str:
        """Genera el bloque de identidad para inyectar en el prompt."""
        parts = ["[CORE IDENTITY — Identidad profunda del personaje]"]

        if self.core_fears:
            parts.append(f"Miedos fundamentales: {', '.join(self.core_fears[:3])}")
        if self.core_desires:
            parts.append(f"Deseos fundamentales: {', '.join(self.core_desires[:3])}")
        if self.self_narrative:
            parts.append(f"Auto-narrativa: {self.self_narrative}")
        if self.shame_sources:
            parts.append(f"Fuentes de vergüenza: {', '.join(self.shame_sources[:2])}")

        active_beliefs = {k: v for k, v in self.self_beliefs.items() if v < 0.35}
        if active_beliefs:
            parts.append("Creencias sobre sí mismo:")
            for k, v in active_beliefs.items():
                label = k.replace("_", " ").capitalize()
                parts.append(f"- {label}: Baja ({v:.2f})")

        return "\n".join(parts)

    # Memoria temprana: edad desde la que el personaje recuerda conscientemente.
    # Antes de esto, los eventos existen en el alma pero no en la memoria narrativa.
    memory_loss_start_age: int = 0

    def derive_contradictions(self) -> list[str]:
        """
        Deriva contradicciones internas desde deseos + miedos + creencias.
        Ej: quiere intimidad pero le teme → conflicto real.
        """
        conflicts = []

        # Deseo de conexión vs miedo a ser lastimado
        if any("connection" in d.lower() or "love" in d.lower() or "belong" in d.lower() for d in self.core_desires):
            if any("abandonment" in f.lower() or "betrayal" in f.lower() or "hurt" in f.lower() for f in self.core_fears):
                conflicts.append("Wants intimacy but fears being hurt")

        # Deseo de libertad vs necesidad de seguridad
        if any("freedom" in d.lower() or "independence" in d.lower() or "autonomy" in d.lower() for d in self.core_desires):
            if any("instability" in f.lower() or "uncertainty" in f.lower() or "insecurity" in f.lower() for f in self.core_fears):
                conflicts.append("Craves freedom yet craves safety")

        # Autoesteem/Seguridad baja pero imperativa de parecer confiado/arrogante
        if (self.self_beliefs.get("i_am_lovable", 0.5) < 0.35 or self.self_beliefs.get("i_am_capable", 0.5) < 0.35) and self.self_beliefs.get("must_appear_confident", 0.5) > 0.65:
            conflicts.append("Feels inadequate but forces themselves to appear confident and strong")

        # Autoestima baja vs necesidad de parecer competente (legacy)
        elif self.self_beliefs.get("i_am_capable", 0.5) < 0.35 and self.self_beliefs.get("i_am_lovable", 0.5) < 0.35:
            if self.self_narrative and ("must" in self.self_narrative.lower() or "should" in self.self_narrative.lower()):
                conflicts.append("Feels inadequate but forces themselves to appear confident")

        # Vergüenza vs deseo de ser visto
        if self.shame_sources:
            if any("humiliation" in d.lower() or "recognition" in d.lower() or "seen" in d.lower() for d in self.core_desires):
                conflicts.append("Wants to be seen yet fears being exposed")

        # Deseo de control vs caos interno
        if self.meaning_system.get("i_have_control", 0.5) < 0.3 and self.interpretation_biases.get("catastrophize", 0.5) > 0.6:
            conflicts.append("Desperately needs control but expects disaster")

        return conflicts[:5]

    def interpret_event(self, event_type: str, description: str, importance: float) -> dict:
        """
        Filtra un evento a través de los sesgos de interpretación.
        Mismo evento → distinta interpretación según identidad.

        Returns:
            dict con perceived_severity, attribution, emotion, belief_impact
        """
        # Los sesgos amplifican o atenúan la percepción
        severity = importance
        if self.interpretation_biases.get("catastrophize", 0.5) > 0.6:
            severity = min(1.0, severity * (1 + self.interpretation_biases["catastrophize"] * 0.3))
        if self.interpretation_biases.get("minimize", 0.5) > 0.6:
            severity = max(0.0, severity * (1 - self.interpretation_biases["minimize"] * 0.3))

        # Atribución: internalizar o externalizar
        if self.interpretation_biases.get("internalize_blame", 0.5) > 0.6 and importance > 0.5:
            attribution = "self"
        elif self.interpretation_biases.get("externalize_blame", 0.5) > 0.6 and importance > 0.5:
            attribution = "others"
        else:
            attribution = "situation"

        # Personalización
        if self.interpretation_biases.get("personalize", 0.5) > 0.6:
            attribution = "self" if importance > 0.4 else attribution

        # Emoción derivada del filtro
        emotion = self._derive_emotion(event_type, severity, attribution)

        return {
            "perceived_severity": severity,
            "attribution": attribution,
            "emotion": emotion,
            "belief_impact": {
                k: -severity * 0.1 for k in self.self_beliefs
                if attribution == "self" and severity > 0.5
            },
        }

    def _derive_emotion(self, event_type: str, severity: float, attribution: str) -> str:
        if attribution == "self" and severity > 0.6:
            return "shame"
        if attribution == "self" and severity > 0.3:
            return "guilt"
        if attribution == "others" and severity > 0.5:
            return "anger"
        if event_type in ("loss", "death") and severity > 0.4:
            return "grief"
        if severity > 0.7:
            return "fear"
        if severity > 0.4:
            return "sadness"
        return "neutral"


@dataclass
class TurningPoint:
    """
    Un evento que redefine la identidad del personaje.
    No es solo un evento importante.
    Es un evento que cambia CÓMO el personaje se ve a sí mismo.

    age: edad en anios
    event: descripción
    intensity: 0-1
    positive: si fue positivo o negativo
    changed_traits: qué cambió y cuánto
    emotional_memory: cómo lo recuerda emocionalmente
    meaning_assigned: interpretación que le dio (crítico)
    """
    age: int = 0
    event: str = ""
    intensity: float = 0.0
    positive: bool = True
    changed_traits: dict[str, float] = field(default_factory=dict)
    emotional_memory: str = ""
    meaning_assigned: str = ""


@dataclass
class EmotionalMemory:
    """
    Un recuerdo con distorsión temporal.
    La gente no recuerda la realidad, recuerda una narrativa.

    original_event: lo que realmente pasó
    remembered_version: cómo lo recuerda ahora (puede diferir)
    emotional_weight: carga emocional 0-1
    confidence: qué tan seguro está de que es correcto
    distortion_level: 0=solo exacto, 1=completamente distorsionado
    last_recalled: timestamp de último recuerdo (para decaimiento)
    """
    id: str = ""
    original_event: str = ""
    remembered_version: str = ""
    emotional_weight: float = 0.5
    confidence: float = 0.8
    distortion_level: float = 0.0
    event_month: int = 0
    last_recalled: str = ""

    def recall(self, current_month: int) -> str:
        """
        Recupera el recuerdo, aplicando distorsión adicional
        si pasó mucho tiempo desde el último recuerdo.
        """
        months_since = current_month - self.event_month
        if months_since > 120:  # >10 años
            self.distortion_level = min(1.0, self.distortion_level + 0.05 * (months_since / 120))
        elif months_since > 60:  # >5 años
            self.distortion_level = min(1.0, self.distortion_level + 0.03 * (months_since / 60))

        if self.distortion_level > 0.5:
            return self.remembered_version
        return self.original_event


@dataclass
class SoulEvent:
    """
    Un evento de vida individual con impacto psicológico numérico.

    A diferencia del dict anterior, este dataclass incluye
    psychological_impact: un dict de variables psicológicas
    que este evento modifica, con valores numéricos (-1.0 a 1.0).
    """
    id: str = ""
    month: int = 0
    event_type: str = "unknown"
    description: str = ""
    importance: float = 0.5
    emotion: str = "neutral"
    people_involved: list[str] = field(default_factory=list)
    location: str = ""
    stage: str = ""

    # Impacto numérico en variables psicológicas
    # Ej: {"trust": -0.15, "self_esteem": -0.1, "fear_of_judgment": +0.3}
    psychological_impact: dict[str, float] = field(default_factory=dict)

    # Creencia formada a partir de este evento
    belief_formed: str = ""
    reflection: str = ""
    coping_strategy: str = ""

    def __post_init__(self):
        if not self.id:
            import uuid
            self.id = uuid.uuid4().hex[:12]


@dataclass
class BeliefEntry:
    """
    Una creencia aprendida de una experiencia de vida.
    """
    id: str = ""
    content: str = ""
    source_event_id: str = ""
    strength: float = 0.5
    category: str = "general"  # trust, worldview, self, others, future
    formed_at_month: int = 0
    last_reinforced: str = ""  # timestamp o month

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:8]


@dataclass
class PsychologyState:
    """
    Estado psicológico EMERGENTE sintetizado periódicamente
    desde Genome + Soul + interacciones recientes.

    NO se authored. Se computa.
    """
    current_big_five: dict[str, float] = field(default_factory=lambda: {
        "openness": 0.5, "conscientiousness": 0.5,
        "extraversion": 0.5, "agreeableness": 0.5,
        "neuroticism": 0.5,
    })
    attachment_style: str = "secure"
    needs: dict[str, float] = field(default_factory=lambda: {
        "safety": 0.5, "belonging": 0.5, "esteem": 0.5,
        "autonomy": 0.5, "meaning": 0.5,
    })
    active_wounds: list[str] = field(default_factory=list)
    active_coping: list[str] = field(default_factory=list)
    active_conflicts: list[str] = field(default_factory=list)
    active_biases: list[str] = field(default_factory=list)
    worldview: dict[str, float] = field(default_factory=lambda: {
        "optimism": 0.5, "trust_in_people": 0.5,
        "sense_of_control": 0.5, "meaningfulness": 0.5,
    })
    version: int = 0


@dataclass
class EmotionalState:
    """
    Sistema emocional multi-eje con decaimiento y dinámica.

    Usa el modelo circumplex de Russell (valence + arousal)
    más emociones secundarias y decaimiento temporal.
    """
    valence: float = 0.0       # -1.0 (negativo) a +1.0 (positivo)
    arousal: float = 0.0       # -1.0 (calma) a +1.0 (activado)
    dominant_emotion: str = "neutral"
    secondary_emotions: dict[str, float] = field(default_factory=dict)
    last_update: str = ""       # timestamp ISO
    emotional_inertia: float = 0.3  # 0=cambia instantáneo, 1=nunca cambia


@dataclass
class PersonaState:
    """
    Capa de expresión: cómo se manifiesta el personaje AHORA.

    Regenerado desde PsychologyState + contexto conversacional.
    Nunca se authored. Siempre se sintetiza.
    """
    speech_style: str = "neutral"
    verbosity: float = 0.5
    sarcasm_tendency: float = 0.3
    warmth: float = 0.5
    defensiveness: float = 0.3
    uses_actions: bool = True
    self_disclosure: float = 0.5
    humor_style: str = "none"
    humor_frequency: float = 0.3
    emotional_distance: float = 0.5
    _synthesized_at: str = ""


@dataclass
class DriftEntry:
    """
    Registro de un cambio psicológico detectado.
    """
    timestamp: str = ""
    axis: str = ""
    old_value: float = 0.5
    new_value: float = 0.5
    reason: str = ""
    source: str = ""  # "synthesis", "feedback_loop", "user_event"


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
    system_prompt: str = "You are a natural conversational partner."
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
    chat_memory_retrieval_limit: int = 3

    # (system_core y anti_assistant_layer se cargan desde YAML ahora)
