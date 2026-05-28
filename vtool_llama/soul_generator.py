"""
Soul System para vtool_llama.

Genera una vida simulada persistente para personajes, creando
experiencias, eventos, relaciones, evolucion psicologica y
recuerdos comprimidos.

Arquitectura:
  Fase 1 — Inicializacion del ser (desde DNA)
  Fase 2 — Simulacion temporal mes a mes (en etapas)
  Fase 3 — Context Engine para cada mes
  Fase 4 — Event Probability Engine (pesos dinamicos)
  Fase 5 — Generacion de eventos por etapa via LLM
  Fase 6 — Reflection Engine (eventos importantes)
  Fase 7 — Relationship Evolution
  Fase 8 — Identity Drift (personalidad cambia con la vida)
  Fase 9 — Semantic Compression -> soul.json
  Fase 10 — Retrieval Architecture (busqueda semantica)

Requisitos:
  - chromadb>=0.4.0
  - sentence-transformers (para embeddings por defecto)
"""

from __future__ import annotations

import json
import math
import os
import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .types import Genome, BeliefEntry

try:
    from .chroma_store import ChromaStore, HAS_CHROMA
except ImportError:
    HAS_CHROMA = False

# ======================================================================
# CONSTANTES
# ======================================================================

EVENT_TYPES = [
    "family", "romantic", "friendship", "education", "work",
    "economic", "health", "trauma", "accident", "violence",
    "loss", "travel", "success", "failure", "crime",
    "technology", "political", "existential", "social", "hobby",
    "skill_growth", "discrimination", "spiritual", "betrayal",
    "discovery", "responsibility", "rivalry", "mentorship",
]

LIFE_STAGES = [
    {"name": "early_childhood", "start": 0, "end": 72,
     "label": "First Years (0-6)",
     "event_density": 0.15},
    {"name": "middle_childhood", "start": 72, "end": 156,
     "label": "Childhood (6-13)",
     "event_density": 0.20},
    {"name": "adolescence", "start": 156, "end": 228,
     "label": "Adolescence (13-19)",
     "event_density": 0.30},
    {"name": "young_adult", "start": 228, "end": 360,
     "label": "Young Adult (20-30)",
     "event_density": 0.35},
    {"name": "adulthood", "start": 360, "end": 600,
     "label": "Adulthood (30-50)",
     "event_density": 0.30},
    {"name": "maturity", "start": 600, "end": 1200,
     "label": "Maturity (50+)",
     "event_density": 0.25},
]

# Pesos por defecto para Event Probability Engine
DEFAULT_EVENT_WEIGHTS = {
    "family": 0.5, "romantic": 0.3, "friendship": 0.5,
    "education": 0.4, "work": 0.3, "economic": 0.3,
    "health": 0.2, "trauma": 0.1, "accident": 0.1,
    "violence": 0.1, "loss": 0.1, "travel": 0.2,
    "success": 0.2, "failure": 0.2, "crime": 0.05,
    "technology": 0.2, "political": 0.1, "existential": 0.15,
    "social": 0.4, "hobby": 0.3, "skill_growth": 0.3,
    "discrimination": 0.1, "spiritual": 0.15, "betrayal": 0.1,
    "discovery": 0.25, "responsibility": 0.2, "rivalry": 0.15,
    "mentorship": 0.2,
}

SOUL_GENERATION_SYSTEM_PROMPT = (
    "Eres un escritor de ficcion especializado en crear vidas humanas "
    "profundas, realistas y psicologicamente complejas. "
    "Generas eventos de vida detallados, emocionalmente resonantes, "
    "con contradicciones, ambiguedad e imperfeccion. "
    "Cada evento debe sentirse real, no generico. "
    "DEBES responder UNICAMENTE con JSON valido, sin markdown, "
    "sin explicaciones, solo el JSON puro."
)


# ======================================================================
# ESTADO DEL ALMA (Soul State)
# ======================================================================

@dataclass
class _SoulState:
    """Estado interno del alma durante la simulacion de vida."""
    age_months: int = 0
    core_traits: dict = field(default_factory=lambda: {
        "openness": 0.5, "conscientiousness": 0.5,
        "extraversion": 0.5, "agreeableness": 0.5,
        "neuroticism": 0.5,
    })
    beliefs: dict = field(default_factory=dict)
    traumas: list = field(default_factory=list)
    social_links: list = field(default_factory=list)
    skills: dict = field(default_factory=dict)
    economic_state: dict = field(default_factory=lambda: {
        "level": "working_class", "stability": 0.5,
    })
    mental_state: dict = field(default_factory=lambda: {
        "happiness": 0.6, "anxiety": 0.3, "trust": 0.5,
        "self_esteem": 0.5, "resilience": 0.5,
    })
    worldview: dict = field(default_factory=lambda: {
        "optimism": 0.5, "morality": 0.5,
        "individualism": 0.5, "traditionalism": 0.5,
    })
    goals: list = field(default_factory=list)
    internal_conflicts: list = field(default_factory=list)
    values: list = field(default_factory=list)
    fears: list = field(default_factory=list)
    education_stage: str = "none"
    current_relationship: Optional[dict] = None
    event_count: int = 0
    last_reflection_month: int = 0
    memory_loss_start_age: int = 0


# ======================================================================
# GENERADOR DE ALMA (Soul Generator)
# ======================================================================

class SoulGenerator:
    """
    Genera una vida simulada completa para un personaje.

    El proceso incluye:
    - Inicializacion desde DNA del personaje
    - Simulacion mes a mes en etapas de vida
    - Generacion de eventos con pesos probabilisticos
    - Reflexion psicologica sobre eventos importantes
    - Deriva de identidad (personality drift)
    - Compresion semantica final en soul.json
    - Checkpoints para reanudacion
    """

    def __init__(
        self,
        character_manager: Any,
        model_manager: Any,
        config: Any,
        log_debug_fn: Callable = None,
        log_info_fn: Callable = None,
        log_warning_fn: Callable = None,
    ):
        self._cm = character_manager
        self._mm = model_manager
        self._config = config
        self._log_debug = log_debug_fn or (lambda t, m: None)
        self._log_info = log_info_fn or (lambda m: None)
        self._log_warning = log_warning_fn or (lambda m: None)

        self._chroma: Optional[ChromaStore] = None
        self._soul_state: Optional[_SoulState] = None
        self._char_dir: Optional[Path] = None
        self._has_llm: bool = False
        self._seed: Optional[int] = None

    # ==================================================================
    # API PUBLICA
    # ==================================================================

    def generate_soul(
        self,
        character_name: str,
        force_regenerate: bool = False,
        seed: Optional[int] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
        country: str = "US",
        birth_year: int = 2000,
        economy: str = "stable",
        family_income: str = "middle_class",
        world_description: str = "",
        start_age_years: int = 0,
        memory_loss_start_age: int = 0,
        interactive_mode: bool = False,
        interactive_callback: Optional[Callable[[int, list[dict]], str]] = None,
        world_type: str = "real",
        use_historical_context: bool = False,
        fictional_lore_reference: str = "",
        max_age_years: Optional[int] = None,
        save_events_history: bool = True,
    ) -> dict:
        """
        Genera o regenera el alma de un personaje.

        Args:
            character_name: nombre del personaje
            force_regenerate: si True, regenera aunque exista soul.json
            seed: semilla para reproducibilidad (None = aleatorio)
            progress_callback: fn(progress: 0-100, stage: str)
            stop_flag: fn() -> bool, si retorna True detiene generacion
            country: país de origen para contexto
            birth_year: año de nacimiento
            economy: situación económica del entorno
            family_income: nivel de ingresos familiares
            world_description: descripción o reglas especiales del mundo
            start_age_years: edad de inicio de simulación de vida
            memory_loss_start_age: edad de inicio de memoria narrativa
            interactive_mode: si True, permite intervención interactiva anual
            interactive_callback: fn(year, events) -> command_str para intervenir

        Returns:
            dict con status, ruta del soul, eventos generados
        """
        self._seed = seed
        if seed is not None:
            random.seed(seed)

        # Guardar parámetros de contexto y modo interactivo
        self._country = country
        self._birth_year = birth_year
        self._economy = economy
        self._family_income = family_income
        self._world_description = world_description
        self._interactive_mode = interactive_mode
        self._interactive_callback = interactive_callback
        self._world_type = world_type
        self._use_historical_context = use_historical_context
        self._fictional_lore_reference = fictional_lore_reference
        self._save_events_history = save_events_history

        # Verificar personaje
        char_dir = self._cm._base_dir / character_name
        if not char_dir.exists() or not (char_dir / "dna").exists():
            raise ValueError(f"Personaje '{character_name}' no encontrado")

        self._char_dir = char_dir
        soul_path = char_dir / "soul.json"
        progress_path = char_dir / "memory" / "soul_progress.json"

        # Verificar si ya existe
        if soul_path.exists() and not force_regenerate:
            raise ValueError(
                f"Soul ya existe para '{character_name}'. "
                "Usa force_regenerate=True para regenerar."
            )

        # Cargar DNA del personaje
        self._cm.load_character(character_name)
        identity = self._cm.identity
        personality = self._cm.personality_dna
        speech = self._cm.speech
        rules = self._cm.rules

        if max_age_years is not None and max_age_years > 0:
            age_months = max_age_years * 12
        else:
            age_months = _identity_age_to_months(identity)

        if age_months < 12:
            raise ValueError(f"Personaje demasiado joven ({age_months//12} anios) para generar alma.")

        # Inicializar ChromaDB
        self._chroma = ChromaStore(char_dir / "memory" / "life_timeline", "life_timeline", log_fn=lambda m: self._log_debug("SOUL", m))
        chroma_ok = self._chroma.initialize()

        if not chroma_ok:
            self._log_warning("ChromaDB no disponible. Continuando sin busqueda semantica.")

        # Si force_regenerate, limpiar datos existentes
        if force_regenerate:
            if self._chroma:
                self._chroma.clear()
            if soul_path.exists():
                soul_path.unlink()
            history_path = char_dir / "memory" / "life_events.json"
            if history_path.exists():
                try:
                    history_path.unlink()
                except Exception:
                    pass

        # Cargar Genome (innato) si existe, sino derivar desde PersonalityDNA
        self._genome = self._load_genome(char_dir, personality)

        # Inicializar estado del alma desde Genome
        self._soul_state = self._init_soul_state(
            identity, personality, speech, rules, age_months,
            genome=self._genome,
        )

        if memory_loss_start_age > 0:
            self._soul_state.memory_loss_start_age = memory_loss_start_age

        if progress_callback:
            progress_callback(1, "Initializing soul state...")

        # Verificar checkpoint para reanudacion
        current_month = 0
        if start_age_years > 0:
            current_month = start_age_years * 12
            self._soul_state.age_months = current_month

        if progress_path.exists():
            try:
                cp = self._load_checkpoint(progress_path)
                if cp and cp.get("character_name") == character_name:
                    current_month = cp.get("current_month", 0)
                    self._restore_soul_state(cp.get("soul_state", {}))
                    if self._chroma and cp.get("chroma_ready"):
                        self._chroma.initialize()
                    self._log_info(f"Reanudando generacion desde mes {current_month}")
                    if progress_callback:
                        pct = int((current_month / age_months) * 100)
                        progress_callback(max(pct, 1), f"Resuming from month {current_month}")
            except Exception as e:
                self._log_warning(f"Error cargando checkpoint: {e}")
                if start_age_years > 0:
                    current_month = start_age_years * 12
                    self._soul_state.age_months = current_month
                else:
                    current_month = 0

        # Determinar etapa actual
        stage_events = self._pre_generate_stage_events(
            identity, personality, rules, speech,
            age_months, progress_callback,
            start_month=current_month,
        )

        # Simular vida mes a mes
        result = self._simulate_life(
            age_months=age_months,
            stage_events=stage_events,
            start_month=current_month,
            progress_path=progress_path,
            progress_callback=progress_callback,
            stop_flag=stop_flag,
        )

        if result["status"] == "paused":
            return result

        # Comprimir alma
        if progress_callback:
            progress_callback(95, "Compressing soul essence...")

        compressed = self._compress_soul(result["events_generated"])

        # Guardar soul.json
        self._save_soul_json(soul_path, compressed)

        # Limpiar checkpoints
        self._cleanup_checkpoints(progress_path)

        if progress_callback:
            progress_callback(100, "Soul generation complete!")

        self._log_info(f"Soul generado para '{character_name}' con {result['events_generated']} eventos.")

        return {
            "status": "complete",
            "character": character_name,
            "soul_path": str(soul_path),
            "events_generated": result["events_generated"],
            "life_months": age_months,
            "genome": asdict(self._genome) if hasattr(self, '_genome') and self._genome else None,
        }

    def retrieve_relevant_memories(
        self,
        query: str,
        top_k: int = 5,
        importance_min: float = 0.0,
        emotion_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Recupera recuerdos semanticamente relevantes de la vida del personaje.

        Args:
            query: texto de consulta (prompt del usuario o contexto)
            top_k: maximo de resultados
            importance_min: filtro de importancia minima (0.0 a 1.0)
            emotion_filter: filtrar por emocion especifica

        Returns:
            lista de eventos ordenados por relevancia compuesta
        """
        if not self._chroma or not self._chroma.is_available:
            return []

        where_clause = {}
        if importance_min > 0:
            where_clause["importance"] = {"$gte": importance_min}
        if emotion_filter:
            where_clause["emotion"] = emotion_filter

        raw = self._chroma.search(query, top_k=top_k * 3, where=where_clause or None)

        # Scoring compuesto: similitud semantica + importancia + peso emocional + retencion
        scored = []
        for ev in raw:
            meta = ev.get("metadata", {})
            similarity = ev.get("similarity", 0.5)
            importance = meta.get("importance", 0.5)
            emotional_weight = meta.get("emotional_weight", 0.5)
            age_months = meta.get("age_months", meta.get("month", 0))
            
            event_age_years = age_months / 12.0

            # Filtro de pérdida de memoria consciente (amnesia infantil)
            memory_loss_age = 0
            if self._soul_state:
                memory_loss_age = self._soul_state.memory_loss_start_age
            elif hasattr(self, '_soul_data') and self._soul_data:
                memory_loss_age = self._soul_data.get("memory_loss_start_age", 0)

            # 1. Amnesia Infantil Gradual
            if event_age_years < 3.0:
                continue  # Amnesia absoluta antes de los 3 años
            elif memory_loss_age > 0 and event_age_years < memory_loss_age:
                # Solo se recuerdan eventos de gran importancia o impacto emocional
                if importance < 0.75 and emotional_weight < 0.75:
                    continue

            # 2. Decaimiento Temporal Exponencial (Fading)
            current_age_months = self._soul_state.age_months if self._soul_state else 1200
            elapsed_years = max(0.0, (current_age_months - age_months) / 12.0)
            
            max_importance = max(importance, emotional_weight)
            # El decaimiento disminuye según la importancia (importancia=1.0 -> sin decaimiento)
            decay_rate = 0.15 * ((1.0 - max_importance) ** 2)
            retention = math.exp(-decay_rate * elapsed_years)

            # Olvido completo si decae demasiado, a menos que sea muy importante (turning point)
            if retention < 0.15 and max_importance < 0.75:
                continue

            score = (
                similarity * 0.40 +
                importance * 0.25 +
                emotional_weight * 0.15 +
                retention * 0.20
            )
            scored.append((score, ev))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [ev for _, ev in scored[:top_k]]

    def has_soul(self, character_name: str) -> bool:
        """Verifica si un personaje tiene alma generada."""
        char_dir = self._cm._base_dir / character_name
        soul_path = char_dir / "soul.json"
        return soul_path.exists()

    def has_timeline_db(self, character_name: str) -> bool:
        """Verifica si existe base de datos de timeline de vida."""
        char_dir = self._cm._base_dir / character_name
        chroma_path = char_dir / "memory" / "life_timeline"
        return chroma_path.exists()

    def get_soul_data(self, character_name: str) -> Optional[dict]:
        """Lee y retorna el soul.json si existe."""
        char_dir = self._cm._base_dir / character_name
        soul_path = char_dir / "soul.json"
        if not soul_path.exists():
            return None
        try:
            with open(soul_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def get_soul_path(self, character_name: str) -> Optional[Path]:
        """Retorna la ruta al soul.json si existe."""
        char_dir = self._cm._base_dir / character_name
        soul_path = char_dir / "soul.json"
        return soul_path if soul_path.exists() else None

    # ==================================================================
    # FASE 1: INICIALIZACION
    # ==================================================================

    def _init_soul_state(
        self, identity, personality, speech, rules, age_months: int,
        genome: Optional[Genome] = None,
    ) -> _SoulState:
        """Construye el estado inicial del alma desde Genome + DNA."""
        state = _SoulState(age_months=age_months)

        # Configurar edad de pérdida de memoria desde la identidad profunda (CoreIdentity)
        core_id = getattr(self._cm, "_core_identity", None)
        if core_id:
            state.memory_loss_start_age = getattr(core_id, "memory_loss_start_age", 0)
        else:
            state.memory_loss_start_age = getattr(identity, "memory_loss_start_age", 0)

        if genome is not None:
            # Usar Genome real (13 ejes de temperamento innato)
            from .psychology_engine import dna_traits_to_genome as _dna_to_genome_fn
            # Si genome es un dict, convertirlo
            if isinstance(genome, dict):
                genome = Genome(**genome)
        else:
            # Backward compat: derivar Genome desde PersonalityDNA
            from .psychology_engine import dna_traits_to_genome
            genome = dna_traits_to_genome(personality)

        # Traducir Genome a Big Five
        from .psychology_engine import PsychologySynthesizer
        ps_synth = PsychologySynthesizer()
        trait_dict = ps_synth._genome_to_big_five(genome)
        state.core_traits = trait_dict

        # Worldview inicial desde genome
        state.worldview["optimism"] = 0.3 + genome.playfulness * 0.4
        state.worldview["individualism"] = genome.independence
        state.worldview["morality"] = genome.empathy * 0.5 + (1.0 - genome.aggression) * 0.5

        # Mental state inicial
        state.mental_state = {
            "happiness": 0.5 + (genome.playfulness - 0.5) * 0.3,
            "anxiety": 0.5 - (genome.emotional_regulation - 0.5) * 0.3,
            "trust": genome.empathy * 0.6 + (1.0 - genome.aggression) * 0.2,
            "self_esteem": genome.persistence * 0.4 + (1.0 - genome.emotional_sensitivity) * 0.3,
            "resilience": genome.emotional_regulation * 0.5 + genome.persistence * 0.3,
        }

        # Valores iniciales desde motivaciones
        for m in personality.motivations:
            state.values.append(m)

        # Miedos iniciales desde flaws + genome
        for f in personality.flaws:
            lower = f.lower()
            if "miedo" in lower or "temor" in lower or "fear" in lower:
                state.fears.append(f)
        if genome.risk_aversion > 0.7:
            state.fears.append("innate caution")

        return state

    def _load_genome(self, char_dir: Path, personality) -> Genome:
        """Carga genome.json o lo deriva desde PersonalityDNA."""
        genome_path = char_dir / "genome.json"
        if genome_path.exists():
            try:
                with open(genome_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._log_info(f"Genome cargado desde {genome_path}")
                return Genome(**data)
            except Exception as e:
                self._log_warning(f"Error cargando genome.json: {e}")

        # Derivar desde PersonalityDNA (backward compat)
        from .psychology_engine import dna_traits_to_genome
        genome = dna_traits_to_genome(personality)
        self._log_info("Genome derivado desde PersonalityDNA (backward compat)")
        return genome

    # ==================================================================
    # FASE 2-5: GENERACION DE EVENTOS POR ETAPA (via LLM)
    # ==================================================================

    def _interpret_event_with_character_mind(
        self,
        character_name: str,
        traits_str: str,
        flaws_str: str,
        motivations_str: str,
        ev: dict
    ) -> dict:
        """Usa la Character Mind (LLM) para interpretar subjetivamente un evento objetivo."""
        if not self._mm or not self._mm.is_loaded:
            rule_based = self._generate_reflection_rule_based(ev, self._soul_state)
            return {
                "emotion": ev.get("emotion", "neutral"),
                "psychological_impact": rule_based.get("emotional_shift", {}),
                "belief_formed": rule_based.get("belief_change", ""),
                "reflection": rule_based.get("thought", ""),
                "coping_strategy": rule_based.get("coping_strategy", "")
            }

        prompt = (
            f"Eres la Mente Emocional (Character Mind) de {character_name}.\n"
            f"Tu tarea es interpretar subjetivamente un evento objetivo que te ocurrió, determinando "
            f"cómo impacta tu psique y qué emociones y creencias dejas grabadas.\n\n"
            f"Tus rasgos innatos (Genome) y DNA:\n"
            f"- Rasgos: {traits_str}\n"
            f"- Defectos/Miedos: {flaws_str}\n"
            f"- Motivaciones: {motivations_str}\n\n"
            f"EVENTO OBJETIVO A INTERPRETAR:\n"
            f"- Mes: {ev.get('month', 0)} (Edad {ev.get('month', 0)//12} años)\n"
            f"- Tipo: {ev.get('type', 'social')}\n"
            f"- Qué pasó: {ev.get('description', '')}\n"
            f"- Importancia: {ev.get('importance', 0.5)}\n\n"
            "Determina:\n"
            "1. La emoción subjetiva predominante que sentiste (joy, sadness, anger, fear, surprise, disgust, trust, etc.).\n"
            "2. El impacto psicológico (psychological_impact): un dict de cambios sutiles (-0.2 a 0.2) en tus ejes: openness, conscientiousness, extraversion, agreeableness, neuroticism, trust_in_people, optimism, sense_of_control, meaningfulness, must_appear_confident.\n"
            "3. La creencia que formaste (belief_formed) como resultado.\n"
            "4. Tu reflexión íntima sobre lo sucedido (reflection).\n"
            "5. El mecanismo de defensa o estrategia de afrontamiento (coping_strategy) que desarrollaste.\n\n"
            "Responde UNICAMENTE con un JSON con este formato:\n"
            "{\n"
            '  "emotion": "<emocion>",\n'
            '  "psychological_impact": {"neuroticism": 0.05, "trust_in_people": -0.1},\n'
            '  "belief_formed": "<creencia formada>",\n'
            '  "reflection": "<reflexion intima>",\n'
            '  "coping_strategy": "<mecanismo>"\n'
            "}\n"
            "Recuerda: Responde SOLO con el JSON puro."
        )

        try:
            result = self._mm.generate(
                messages=[
                    {"role": "system", "content": "Eres la mente emocional del personaje. Responde SOLO con JSON válido sin markdown."},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                max_tokens=512,
                temperature=0.8,
            )
            text = result["choices"][0]["message"].get("content", "")
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                data = json.loads(text[start:end])
                return data
        except Exception as e:
            self._log_warning(f"Error en Character Mind para evento: {e}")

        rule_based = self._generate_reflection_rule_based(ev, self._soul_state)
        return {
            "emotion": ev.get("emotion", "neutral"),
            "psychological_impact": rule_based.get("emotional_shift", {}),
            "belief_formed": rule_based.get("belief_change", ""),
            "reflection": rule_based.get("thought", ""),
            "coping_strategy": rule_based.get("coping_strategy", "")
        }

    def _roll_random_chaos_event(self, age_years: int) -> Optional[dict]:
        """Roll anual de la Random Chaos Layer con variables de contexto geográfico e histórico."""
        roll = random.random()
        p_social = 0.20
        p_strong = 0.08
        p_life = 0.02

        if hasattr(self, '_genome') and self._genome:
            if self._genome.impulsivity > 0.7 or self._genome.risk_aversion < 0.3:
                p_strong += 0.04
            if self._genome.sociability > 0.7:
                p_social += 0.05

        if getattr(self, '_economy', 'stable') in ('poor', 'crisis'):
            p_life += 0.04
            p_strong += 0.02
        if getattr(self, '_family_income', 'middle_class') == 'poor':
            p_life += 0.05

        if roll < p_life:
            event_type = random.choice(["economic", "trauma", "loss", "crime", "existential"])
            importance = round(random.uniform(0.75, 0.95), 2)
            desc_pool = {
                "economic": f"Extreme financial hardship hit the family in {self._country} due to national crisis.",
                "trauma": "A major political instability forced relocation, leaving almost everything behind.",
                "loss": "Faced severe poverty and food shortages during a harsh economic winter.",
                "crime": "Witnessed or fell victim to a serious neighborhood crime.",
                "existential": "A historic event or epidemic swept through the region, disrupting daily life."
            }
            desc = desc_pool.get(event_type, "A major life-defining event occurred.")
        elif roll < p_life + p_strong:
            event_type = random.choice(["health", "accident", "trauma", "violence", "loss"])
            importance = round(random.uniform(0.55, 0.80), 2)
            desc_pool = {
                "health": "Suffered a serious illness that kept them bedridden for months.",
                "accident": "Survived a dangerous accident that left physical and emotional scars.",
                "trauma": "Experienced a deeply distressing event at school or home.",
                "violence": "Confronted a violent confrontation in the local neighborhood.",
                "loss": "Mourned the sudden loss of someone or something highly valued."
            }
            desc = desc_pool.get(event_type, "A strong, impactful event occurred.")
        elif roll < p_life + p_strong + p_social:
            event_type = random.choice(["betrayal", "romantic", "mentorship", "rivalry", "friendship"])
            importance = round(random.uniform(0.35, 0.65), 2)
            desc_pool = {
                "betrayal": "Discovered a close friend had shared private secrets.",
                "romantic": "Experienced the intense highs and lows of a first crush/romance.",
                "mentorship": "Met an older figure who offered guidance and new perspectives.",
                "rivalry": "Engaged in a fierce rivalry at school or work.",
                "friendship": "Formed an incredibly close bond with someone who shared their worldview."
            }
            desc = desc_pool.get(event_type, "A significant social event occurred.")
        else:
            return None

        event_year = self._birth_year + age_years
        desc += f" (Year {event_year} in {self._country})"

        return {
            "month": age_years * 12 + random.randint(0, 11),
            "type": event_type,
            "description": desc,
            "importance": importance,
            "people_involved": [],
            "location": self._country,
            "stage": next((s["name"] for s in LIFE_STAGES if s["start"] <= age_years * 12 < s["end"]), "adulthood")
        }

    def _pre_generate_stage_events(
        self,
        identity, personality, rules, speech,
        age_months: int,
        progress_callback: Optional[Callable],
        start_month: int = 0,
    ) -> list[dict]:
        """
        Genera eventos de vida usando el patrón Life Director (eventos objetivos)
        y luego los interpreta usando la Character Mind.
        """
        if not self._mm or not self._mm.is_loaded:
            self._log_warning("No hay LLM disponible. Usando generacion aleatoria.")
            return self._generate_random_events(age_months, start_month)

        self._has_llm = True
        all_events = []

        identity_name = getattr(identity, "name", "unknown")
        identity_role = getattr(identity, "role", "unknown")
        identity_background = getattr(identity, "background", "")
        identity_scenario = getattr(identity, "scenario", "")

        traits_str = ", ".join(personality.traits)
        flaws_str = ", ".join(personality.flaws)
        motivations_str = ", ".join(personality.motivations)
        speech_style = getattr(speech, "style", "")

        total_stages = sum(
            1 for s in LIFE_STAGES
            if s["start"] < age_months and s["end"] > start_month
        )
        stage_idx = 0

        for stage in LIFE_STAGES:
            if stage["start"] >= age_months:
                break
            if stage["end"] <= start_month:
                continue

            stage_idx += 1
            stage_start = max(stage["start"], start_month)
            stage_end = min(stage["end"], age_months)
            stage_years_start = stage_start // 12
            stage_years_end = stage_end // 12

            if progress_callback:
                base_progress = 5 + int((stage_idx / total_stages) * 70)
                progress_callback(
                    base_progress,
                    f"[Life Director] Generating stage {stage['label']} (age {stage_years_start}-{stage_years_end})...",
                )

            world_type = getattr(self, "_world_type", "real")
            use_historical = getattr(self, "_use_historical_context", False)
            fictional_lore = getattr(self, "_fictional_lore_reference", "")
            
            world_context_prompt = ""
            if world_type == "real":
                world_context_prompt = (
                    f"El mundo de este personaje es el MUNDO REAL.\n"
                    f"País/Región: {getattr(self, '_country', 'US')}\n"
                    f"Periodo de tiempo de esta etapa: Años {getattr(self, '_birth_year', 2000) + stage_years_start} a {getattr(self, '_birth_year', 2000) + stage_years_end}.\n"
                )
                if use_historical:
                    world_context_prompt += (
                        "DEBES basar e integrar los eventos del personaje de manera estricta y profunda en la situación histórica, crisis, tensiones políticas y acontecimientos reales que ocurrieron en ese país/región durante esos años exactos (por ejemplo, si el país es Cuba y la época son los años 1990, debes integrar los sucesos de la crisis del Período Especial en Cuba: escasez de alimentos, apagones constantes, tensiones sociales y familiares; si es EE.UU. en los años 2000, los ataques del 11 de septiembre, etc.). Las vivencias del personaje y sus recuerdos deben reflejar fielmente la atmósfera real de esa época y región."
                    )
                else:
                    world_context_prompt += "Usa el contexto general de este país, pero no es estrictamente obligatorio apegarse a acontecimientos históricos específicos."
            else:
                world_context_prompt = (
                    f"El mundo de este personaje es un MUNDO DE FICCIÓN/FANTASÍA.\n"
                    f"Reino/Mundo/Región: {getattr(self, '_country', 'US')}\n"
                    f"Periodo de tiempo en el mundo ficticio: Años o ciclo {getattr(self, '_birth_year', 2000) + stage_years_start} a {getattr(self, '_birth_year', 2000) + stage_years_end}.\n"
                )
                if fictional_lore:
                    world_context_prompt += (
                        f"DEBES basar e integrar los eventos en las leyes de la física/magia, lore y acontecimientos descritos de este mundo ficticio (Referencia de Lore/Libro: {fictional_lore}). "
                        f"Los recuerdos y vivencias cotidianas del personaje deben construirse sobre esta base y lore del mundo ficticio en esta era."
                    )
                else:
                    world_context_prompt += "Usa el contexto del mundo de fantasía sugerido por el nombre o el escenario, integrándolo en la vida cotidiana del personaje."

            # Prompter para el Life Director
            director_prompt = (
                f"Eres el Director de Vida (Life Director), un observador frío y lógico de la causalidad humana. "
                f"Tu tarea es decidir qué eventos objetivos ocurren en la vida de {identity_name} "
                f"para la etapa {stage['label']} (Edad {stage_years_start} a {stage_years_end} años).\n\n"
                f"TIPO DE MUNDO Y CONTEXTO HISTÓRICO:\n{world_context_prompt}\n\n"
                f"Situación económica local: {getattr(self, '_economy', 'stable')}\n"
                f"Ingresos de la familia: {getattr(self, '_family_income', 'middle_class')}\n"
                f"Descripción y reglas especiales del mundo: {getattr(self, '_world_description', 'Ninguna')}\n"
                f"Antecedentes del personaje: {identity_background}\n"
                f"DNA/Traits: {traits_str}\n\n"
                "Genera una lista de eventos puramente OBJETIVOS que suceden. "
                "NO menciones emociones, ni cambios psicológicos, ni heridas en la descripción. "
                "Solo describe lo que pasó físicamente en el mundo real, la fecha (en meses desde nacimiento), "
                "el tipo de evento (family, romantic, friendship, education, work, economic, health, trauma, accident, violence, loss, travel, success, failure, crime, etc.), "
                "la importancia (0.0 a 1.0), y el lugar/personas involucradas.\n"
                "IMPORTANTE: Si necesitas que el orquestador humano defina el resultado de una acción aleatoria, "
                "especifique un detalle familiar o responda una duda de lore específica para evitar alucinaciones, "
                "añade el campo opcional 'query_for_orchestrator' en el JSON del evento con la pregunta. La simulación "
                "se detendrá para preguntarle y el resultado se inyectará en la descripción del evento.\n\n"
                "Responde UNICAMENTE con un JSON con este formato:\n"
                "{\n"
                '  "events": [\n'
                "    {\n"
                '      "month": <int>,\n'
                '      "type": "<tipo>",\n'
                '      "description": "<descripción física y factual del suceso>",\n'
                '      "importance": <0.0-1.0>,\n'
                '      "location": "<lugar>",\n'
                '      "people_involved": ["<persona>"],\n'
                '      "query_for_orchestrator": "<pregunta opcional al orquestador>"\n'
                "    }\n"
                "  ]\n"
                "}"
            )

            try:
                result = self._mm.generate(
                    messages=[
                        {"role": "system", "content": SOUL_GENERATION_SYSTEM_PROMPT},
                        {"role": "user", "content": director_prompt},
                    ],
                    stream=False,
                    max_tokens=1536,
                    temperature=0.8,
                )
                response_text = result["choices"][0]["message"].get("content", "")
                stage_events = self._parse_events_from_json(response_text)
                
                if progress_callback:
                    progress_callback(base_progress + 1, f"[Character Mind] Analyzing {len(stage_events)} events for {stage['label']}...")
                
                # Ahora cada evento objetivo es interpretado por la Character Mind
                interpreted_events = []
                for i, ev in enumerate(stage_events):
                    ev["stage"] = stage["name"]
                    ev["month"] = max(stage_start, min(stage_end - 1, ev.get("month", stage_start)))
                    
                    # Interceptar consulta al orquestador si existe
                    query = ev.pop("query_for_orchestrator", None)
                    if query and getattr(self, '_interactive_mode', False) and getattr(self, '_interactive_callback', None):
                        # Llamamos al callback pasando la consulta
                        ans = self._interactive_callback(ev["month"] // 12, [{"type": "query", "query": query, "event": ev}])
                        if ans:
                            orig_desc = ev.get("description", "")
                            ev["description"] = f"{orig_desc} (Orchestrator details: {ans})"
                    
                    if progress_callback:
                        ev_type = ev.get("type", "event")
                        progress_callback(base_progress + 1, f"[Character Mind] Interpreting event {i+1}/{len(stage_events)} (Age {ev['month']//12} | {ev_type})...")
                    
                    # Llamar a Character Mind para rellenar psicología
                    mind_result = self._interpret_event_with_character_mind(
                        identity_name, traits_str, flaws_str, motivations_str, ev
                    )
                    ev.update(mind_result)
                    interpreted_events.append(ev)
                    
                all_events.extend(interpreted_events)

            except Exception as e:
                self._log_warning(f"Error en Life Director para {stage['name']}: {e}")
                fallback = self._generate_random_events_for_stage(stage, age_months)
                all_events.extend(fallback)

        return all_events

    def _parse_events_from_json(self, text: str) -> list[dict]:
        """Parsea JSON de eventos desde respuesta del LLM."""
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start == -1 or end <= start:
                return []
            data = json.loads(text[start:end])
            raw_events = data.get("events", [])
            if isinstance(raw_events, list):
                return raw_events
            return []
        except (json.JSONDecodeError, Exception):
            return []

    def _generate_random_events(self, age_months: int, start_month: int = 0) -> list[dict]:
        """Genera eventos aleatorios como fallback cuando no hay LLM."""
        events = []
        for stage in LIFE_STAGES:
            if stage["start"] >= age_months:
                break
            if stage["end"] <= start_month:
                continue
            stage_events = self._generate_random_events_for_stage(stage, age_months, start_month)
            events.extend(stage_events)
        return events

    def _generate_random_events_for_stage(self, stage: dict, age_months: int, start_month: int = 0) -> list[dict]:
        """Genera eventos aleatorios para una etapa especifica."""
        events = []
        stage_start = max(stage["start"], start_month)
        stage_end = min(stage["end"], age_months)
        density = stage["event_density"]
        num_events = max(1, int((stage_end - stage_start) / 12 * density))

        for _ in range(num_events):
            month = random.randint(stage_start, max(stage_start, stage_end - 1))
            ev_type = random.choice(EVENT_TYPES)
            importance = round(random.uniform(0.3, 0.9), 2)
            emotions = ["joy", "sadness", "anger", "fear", "surprise", "disgust", "trust", "anticipation"]
            event = {
                "month": month,
                "type": ev_type,
                "description": f"A {ev_type} event occurred (age {month//12}y {month%12}m)",
                "importance": importance,
                "emotion": random.choice(emotions),
                "people_involved": [],
                "location": "unknown",
                "personality_impact": "slight change",
                "stage": stage["name"],
            }
            events.append(event)
        return events

    # ==================================================================
    # FASE 2: SIMULACION MES A MES
    # ==================================================================

    def _simulate_life(
        self,
        age_months: int,
        stage_events: list[dict],
        start_month: int = 0,
        progress_path: Optional[Path] = None,
        progress_callback: Optional[Callable] = None,
        stop_flag: Optional[Callable] = None,
    ) -> dict:
        """
        Itera mes a mes la vida del personaje, procesando eventos,
        reflexiones, deriva de identidad, Random Chaos Layer y modo interactivo.
        """
        events_generated = 0
        last_checkpoint_month = 0

        # DNA text for Character Mind
        identity = self._cm.identity
        personality = self._cm.personality_dna
        traits_str = ", ".join(personality.traits)
        flaws_str = ", ".join(personality.flaws)
        motivations_str = ", ".join(personality.motivations)

        # Indexar eventos pre-generados por mes
        events_by_month: dict[int, list[dict]] = {}
        for ev in stage_events:
            m = ev.get("month", 0)
            if m not in events_by_month:
                events_by_month[m] = []
            events_by_month[m].append(ev)

        total_simulated = age_months - start_month
        if total_simulated <= 0:
            return {"status": "complete", "events_generated": len(stage_events)}

        for month in range(start_month, age_months):
            if stop_flag and stop_flag():
                self._save_checkpoint(
                    progress_path, month, self._soul_state,
                    character_name=self._cm.character_name,
                )
                pct = int((month / age_months) * 100)
                return {
                    "status": "paused",
                    "progress": pct,
                    "current_month": month,
                    "events_generated": events_generated,
                }

            year = month // 12

            # 1. Random Chaos Layer (Lanzamiento anual al iniciar el año)
            if month > 0 and month % 12 == 0:
                chaos_event = self._roll_random_chaos_event(year)
                if chaos_event:
                    # Si estamos en modo interactivo, pedir confirmación/modificación al orquestador
                    if getattr(self, '_interactive_mode', False) and getattr(self, '_interactive_callback', None):
                        # Llamamos al callback indicando que es un chaos roll
                        ans = self._interactive_callback(year, [{"type": "chaos_roll", "event": chaos_event}])
                        if ans and ans != "continue":
                            # El orquestador ha modificado la descripción o detalles
                            chaos_event["description"] = ans

                    # Interpretar con Character Mind
                    mind_res = self._interpret_event_with_character_mind(
                        self._cm.character_name, traits_str, flaws_str, motivations_str, chaos_event
                    )
                    chaos_event.update(mind_res)
                    m = chaos_event["month"]
                    if m not in events_by_month:
                        events_by_month[m] = []
                    events_by_month[m].append(chaos_event)

            # Procesar eventos de este mes
            month_events = events_by_month.get(month, [])
            for event in month_events:
                # Completar metadata del evento
                psy_impact = event.get("psychological_impact", {}) or {}
                event_meta = {
                    "age": month // 12,
                    "month": month,
                    "emotion": event.get("emotion", "neutral"),
                    "importance": event.get("importance", 0.5),
                    "event_type": event.get("type", "unknown"),
                    "emotional_weight": min(1.0, event.get("importance", 0.5) * 1.2),
                    "psychological_impact": json.dumps(psy_impact),
                    "belief_formed": event.get("belief_formed", ""),
                    "coping_strategy": event.get("coping_strategy", ""),
                }
                event_id = f"life_{month}_{uuid.uuid4().hex[:8]}"

                # Guardar en ChromaDB
                if self._chroma:
                    self._chroma.add_event(
                        event_id=event_id,
                        description=event.get("description", ""),
                        metadata=event_meta,
                    )

                events_generated += 1
                self._add_event_to_history(event_id, month, event, psy_impact)

                if progress_callback and event.get("importance", 0) > 0.35:
                    pct = 5 + int((month / age_months) * 85)
                    desc_short = event.get("description", "")
                    if len(desc_short) > 75: desc_short = desc_short[:72] + "..."
                    
                    ev_type = event.get("type", "unknown").upper()
                    emotion = event.get("emotion", "neutral")
                    
                    progress_callback(min(pct, 90), f"[Age {year} | {ev_type} | {emotion}] {desc_short}")
                    
                    if event.get("belief_formed"):
                        progress_callback(min(pct, 90), f"  ↳ [Belief] {event.get('belief_formed')[:75]}")
                    if event.get("coping_strategy"):
                        progress_callback(min(pct, 90), f"  ↳ [Coping] developed: {event.get('coping_strategy')}")

                # Reflexión sobre eventos importantes
                if event.get("importance", 0) > 0.65:
                    self._process_reflection(event, self._soul_state)
                    
                    if progress_callback and self._soul_state.internal_conflicts:
                        pct = 5 + int((month / age_months) * 85)
                        thought = self._soul_state.internal_conflicts[-1].get("thought", "")
                        if thought:
                            thought_short = thought
                            if len(thought_short) > 70: thought_short = thought_short[:67] + "..."
                            progress_callback(min(pct, 90), f"  ↳ [Reflection] {thought_short}")

                # Almacenar creencia si existe
                if event.get("belief_formed"):
                    self._soul_state.beliefs[event_id] = {
                        "content": event.get("belief_formed", ""),
                        "strength": event.get("importance", 0.5),
                        "source_event": event.get("description", "")[:100],
                    }

                # Actualizar estado economico segun eventos
                ev_type = event.get("type", "")
                if ev_type == "economic":
                    self._soul_state.economic_state["stability"] = max(
                        0.0, min(1.0,
                            self._soul_state.economic_state["stability"] +
                            random.uniform(-0.2, 0.2)
                        )
                    )

            # Eventos casuales pequeños si no hay eventos mayores
            if not month_events and random.random() < 0.08:
                micro = self._generate_micro_event(month)
                if micro:
                    micro_meta = {
                        "age": month // 12,
                        "month": month,
                        "emotion": micro.get("emotion", "neutral"),
                        "importance": micro.get("importance", 0.2),
                        "event_type": micro.get("type", "social"),
                        "emotional_weight": 0.2,
                    }
                    if self._chroma:
                        self._chroma.add_event(
                            event_id=f"micro_{month}_{uuid.uuid4().hex[:8]}",
                            description=micro.get("description", ""),
                            metadata=micro_meta,
                        )
                    events_generated += 1
                    self._add_event_to_history(f"micro_{month}_{uuid.uuid4().hex[:8]}", month, micro, {})

            # 2. Timeline Interactive Mode (Intervención al final de cada año)
            if month % 12 == 11 and getattr(self, '_interactive_mode', False) and getattr(self, '_interactive_callback', None):
                # Recopilar eventos del año actual
                year_start_month = year * 12
                year_events = []
                for m in range(year_start_month, year_start_month + 12):
                    year_events.extend(events_by_month.get(m, []))

                # Ejecutar callback interactivo
                cmd = self._interactive_callback(year, year_events)
                if cmd and cmd.startswith("inject:"):
                    # Formato: inject:<type>:<description>
                    parts = cmd.split(":", 2)
                    inj_type = parts[1]
                    inj_desc = parts[2]
                    
                    # Crear evento inyectado
                    inj_event = {
                        "month": month, # Inyectado al final del año
                        "type": inj_type,
                        "description": inj_desc,
                        "importance": 0.8,
                        "people_involved": [],
                        "location": self._country,
                        "stage": next((s["name"] for s in LIFE_STAGES if s["start"] <= month < s["end"]), "adulthood")
                    }
                    
                    # Interpretar con Character Mind
                    mind_res = self._interpret_event_with_character_mind(
                        self._cm.character_name, traits_str, flaws_str, motivations_str, inj_event
                    )
                    inj_event.update(mind_res)
                    
                    # Añadir a la simulación del mes actual
                    if month not in events_by_month:
                        events_by_month[month] = []
                    events_by_month[month].append(inj_event)
                    
                    # Procesar el evento inyectado de inmediato
                    psy_impact = inj_event.get("psychological_impact", {}) or {}
                    event_meta = {
                        "age": month // 12,
                        "month": month,
                        "emotion": inj_event.get("emotion", "neutral"),
                        "importance": inj_event.get("importance", 0.8),
                        "event_type": inj_event.get("type", "unknown"),
                        "emotional_weight": 0.9,
                        "psychological_impact": json.dumps(psy_impact),
                        "belief_formed": inj_event.get("belief_formed", ""),
                        "coping_strategy": inj_event.get("coping_strategy", ""),
                    }
                    event_id = f"injected_{month}_{uuid.uuid4().hex[:8]}"
                    if self._chroma:
                        self._chroma.add_event(event_id=event_id, description=inj_event.get("description", ""), metadata=event_meta)
                    events_generated += 1
                    self._add_event_to_history(event_id, month, inj_event, psy_impact)
                    
                    if inj_event.get("importance", 0) > 0.65:
                        self._process_reflection(inj_event, self._soul_state)
                    if inj_event.get("belief_formed"):
                        self._soul_state.beliefs[event_id] = {
                            "content": inj_event.get("belief_formed", ""),
                            "strength": inj_event.get("importance", 0.8),
                            "source_event": inj_event.get("description", "")[:100],
                        }

            # Identity Drift anual
            if month > 0 and month % 12 == 0:
                self._apply_identity_drift(month, self._soul_state)

            # Progreso
            if progress_callback and month % max(1, age_months // 100) == 0:
                pct = 5 + int((month / age_months) * 85)
                progress_callback(min(pct, 90), f"Age {year}: Processing life...")

            # Checkpoint cada 6 meses
            if progress_path and (month - last_checkpoint_month >= 6):
                self._save_checkpoint(
                    progress_path, month, self._soul_state,
                    character_name=self._cm.character_name,
                )
                last_checkpoint_month = month

        return {"status": "complete", "events_generated": events_generated}

    def _generate_micro_event(self, month: int) -> Optional[dict]:
        """Genera un micro-evento aleatorio (encuentro casual, pensamiento, etc)."""
        if random.random() < 0.3:
            return None

        micro_types = ["social", "hobby", "reflection", "discovery"]
        ev_type = random.choice(micro_types)
        emotions = ["contentment", "curiosity", "boredom", "amusement", "nostalgia", "melancholy"]

        descriptions = [
            f"Spent a quiet afternoon reflecting on life (age {month//12})",
            f"Had an unexpected conversation with a stranger that made me think",
            f"Discovered a new interest while browsing",
            f"Felt a sudden wave of nostalgia thinking about the past",
            f"Witnessed something beautiful that lifted the mood",
            f"A small disagreement reminded me of past conflicts",
        ]

        return {
            "month": month,
            "type": ev_type,
            "description": random.choice(descriptions),
            "importance": round(random.uniform(0.1, 0.35), 2),
            "emotion": random.choice(emotions),
            "people_involved": [],
            "location": "unknown",
        }

    # ==================================================================
    # FASE 6: REFLECTION ENGINE
    # ==================================================================

    def _process_reflection(self, event: dict, state: _SoulState) -> None:
        """Procesa una reflexion psicologica sobre un evento importante."""
        event_desc = event.get("description", "")
        importance = event.get("importance", 0.5)
        ev_type = event.get("type", "")

        if self._has_llm and importance > 0.75:
            reflection = self._generate_reflection_with_llm(event, state)
        else:
            reflection = self._generate_reflection_rule_based(event, state)

        if reflection:
            state.internal_conflicts.append(reflection)

            # Aplicar cambios psicologicos
            belief_change = reflection.get("belief_change", "")
            if belief_change:
                key = f"belief_{len(state.beliefs)}"
                state.beliefs[key] = belief_change

            emotional_shift = reflection.get("emotional_shift", {})
            if isinstance(emotional_shift, dict):
                for k, v in emotional_shift.items():
                    if k in state.mental_state:
                        delta = float(v) if isinstance(v, (int, float)) else 0.1
                        state.mental_state[k] = max(0.0, min(1.0, state.mental_state[k] + delta))

            coping = reflection.get("coping_strategy", "")
            if coping:
                state.skills[coping] = state.skills.get(coping, 0) + 0.1

    def _generate_reflection_with_llm(self, event: dict, state: _SoulState) -> dict:
        """Usa el LLM para generar una reflexion psicologica profunda."""
        prompt = (
            f"Eres un psicologo analizando el impacto de un evento en la psique de un personaje.\n\n"
            f"Evento: {event.get('description', '')}\n"
            f"Tipo: {event.get('type', '')}\n"
            f"Importancia: {event.get('importance', 0.5)}\n"
            f"Emocion: {event.get('emotion', '')}\n\n"
            f"Estado actual del personaje:\n"
            f"- Autoestima: {state.mental_state.get('self_esteem', 0.5):.2f}\n"
            f"- Ansiedad: {state.mental_state.get('anxiety', 0.3):.2f}\n"
            f"- Confianza: {state.mental_state.get('trust', 0.5):.2f}\n"
            f"- Valores: {', '.join(state.values) if state.values else 'en formacion'}\n\n"
            "Genera una reflexion interna realista en formato JSON:\n"
            "{\n"
            '  "thought": "aprendizaje interno del evento",\n'
            '  "belief_change": "nueva creencia formada",\n'
            '  "emotional_shift": {"trust": -0.1, "anxiety": 0.2},\n'
            '  "coping_strategy": "mecanismo de defensa"\n'
            "}\n"
            "Importante: los cambios emocionales deben ser sutiles (0.0 a 0.3), no extremos."
        )

        try:
            result = self._mm.generate(
                messages=[
                    {"role": "system", "content": "Eres un psicologo narrativo. Responde SOLO con JSON valido."},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                max_tokens=256,
                temperature=0.7,
            )
            text = result["choices"][0]["message"].get("content", "")
            reflection = self._parse_reflection_from_json(text)
            if reflection:
                return reflection
        except Exception:
            pass

        return self._generate_reflection_rule_based(event, state)

    def _generate_reflection_rule_based(self, event: dict, state: _SoulState) -> dict:
        """Reflexion basada en reglas cuando no hay LLM."""
        ev_type = event.get("type", "")
        emotion = event.get("emotion", "neutral")
        importance = event.get("importance", 0.5)

        reflection_map = {
            "loss": {
                "thought": "Learned that nothing lasts forever.",
                "belief_change": "Attachment leads to pain.",
                "emotional_shift": {"trust": -0.05, "anxiety": 0.05},
                "coping_strategy": "emotional_guarding",
            },
            "trauma": {
                "thought": "Some experiences leave permanent marks.",
                "belief_change": "The world can be dangerous.",
                "emotional_shift": {"trust": -0.1, "anxiety": 0.15, "self_esteem": -0.05},
                "coping_strategy": "hypervigilance",
            },
            "betrayal": {
                "thought": "Trust is a fragile thing.",
                "belief_change": "People are ultimately self-interested.",
                "emotional_shift": {"trust": -0.15, "self_esteem": -0.05},
                "coping_strategy": "hyper_independence",
            },
            "success": {
                "thought": "Hard work pays off.",
                "belief_change": "I am capable of achieving things.",
                "emotional_shift": {"self_esteem": 0.1, "happiness": 0.1},
                "coping_strategy": "self_affirmation",
            },
            "failure": {
                "thought": "Not everything works out, and that is okay.",
                "belief_change": "Failure is part of growth.",
                "emotional_shift": {"self_esteem": -0.05, "resilience": 0.05},
                "coping_strategy": "reframing",
            },
            "romantic": {
                "thought": "Love changes everything.",
                "belief_change": "Connection with others defines life.",
                "emotional_shift": {"happiness": 0.1, "trust": 0.05},
                "coping_strategy": "vulnerability",
            },
        }

        base = reflection_map.get(ev_type, {
            "thought": f"This {ev_type} experience was impactful.",
            "belief_change": f"Experiences shape who we become.",
            "emotional_shift": {},
            "coping_strategy": "reflection",
        })

        return dict(base)

    def _parse_reflection_from_json(self, text: str) -> Optional[dict]:
        """Parsea JSON de reflexion."""
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start == -1 or end <= start:
                return None
            data = json.loads(text[start:end])
            required = ["thought"]
            if all(k in data for k in required):
                return data
            return None
        except Exception:
            return None

    # ==================================================================
    # FASE 8: IDENTITY DRIFT
    # ==================================================================

    def _apply_identity_drift(self, current_month: int, state: _SoulState) -> None:
        """Aplica deriva de personalidad anual basada en eventos acumulados."""
        años_vividos = current_month // 12

        # Deriva natural: las personas cambian con el tiempo
        for trait in state.core_traits:
            drift = random.uniform(-0.03, 0.03)
            state.core_traits[trait] = max(0.05, min(0.95, state.core_traits[trait] + drift))

        # Los conflictos internos acumulados afectan la personalidad
        num_conflicts = len(state.internal_conflicts)
        if num_conflicts > 5:
            state.core_traits["neuroticism"] = min(0.95, state.core_traits["neuroticism"] + 0.02)
        if num_conflicts > 10:
            state.core_traits["neuroticism"] = min(0.95, state.core_traits["neuroticism"] + 0.01)

        # Eventos traumaticos reducen confianza
        trauma_count = sum(
            1 for c in state.internal_conflicts
            if "trauma" in c.get("coping_strategy", "") or "guarding" in c.get("coping_strategy", "")
        )
        if trauma_count > 3:
            state.core_traits["agreeableness"] = max(0.05, state.core_traits["agreeableness"] - 0.02)

        # La edad tiende a aumentar responsabilidad
        if años_vividos > 25:
            state.core_traits["conscientiousness"] = min(0.95, state.core_traits["conscientiousness"] + 0.01)

        self._log_debug("SOUL", f"Identity drift applied at age {años_vividos}")

    # ==================================================================
    # FASE 9: COMPRESION SEMANTICA
    # ==================================================================

    def _compress_soul(self, total_events: int) -> dict:
        """
        Comprime toda la vida simulada en soul.json.
        Usa el LLM si esta disponible, sino reglas heuristicas.
        """
        state = self._soul_state

        if self._has_llm and self._chroma and self._chroma.is_available:
            return self._compress_with_llm(state, total_events)

        return self._compress_heuristic(state, total_events)

    def _compress_with_llm(self, state: _SoulState, total_events: int) -> dict:
        """Usa el LLM para generar el nucleo psicologico comprimido."""
        events_sample = []
        if self._chroma and self._chroma.is_available:
            try:
                sample = self._chroma.search("most important life events", top_k=20)
                events_sample = [s["description"] for s in sample if s.get("description")]
            except Exception:
                events_sample = []

        traits_str = json.dumps(state.core_traits, indent=2)
        mental_str = json.dumps(state.mental_state, indent=2)
        values_str = ", ".join(state.values) if state.values else "developing"
        conflicts_str = json.dumps([
            c.get("thought", "") for c in state.internal_conflicts[-10:]
        ], indent=2) if state.internal_conflicts else "none yet"

        events_str = "\n".join(events_sample[:15]) if events_sample else "varied life experiences"

        prompt = (
            "Eres un escritor de ficcion especializado en crear perfiles psicologicos "
            "profundos y realistas. Analiza la siguiente vida simulada y genera un "
            "nucleo psicologico COMPRIMIDO pero RICO en matices.\n\n"
            f"Rasgos de personalidad actuales:\n{traits_str}\n\n"
            f"Estado mental:\n{mental_str}\n\n"
            f"Valores: {values_str}\n\n"
            f"Conflictos internos:\n{conflicts_str}\n\n"
            f"Eventos de vida representativos:\n{events_str}\n\n"
            "Genera un JSON con el siguiente esquema EXACTO:\n"
            "{\n"
            '  "core_identity": {"summary": "quien es, en 2-3 oraciones", "archetype": "arquetipo"},'
            '  "emotional_scars": ["herida 1", "herida 2"],'
            '  "hidden_desires": ["deseo 1", "deseo 2"],'
            '  "contradictions": ["contradiccion 1", "contradiccion 2"],'
            '  "worldview": {"optimism": 0.5, "morality": 0.5, "individualism": 0.5, "traditionalism": 0.5},'
            '  "behavior_biases": ["sesgo 1", "sesgo 2"],'
            '  "important_people": [],'
            '  "life_philosophy": "una linea que define su filosofia de vida",'
            '  "speech_bias": {"style": "como habla", "quirks": []},'
            '  "core_memories": ["recuerdo fundacional 1", "recuerdo fundacional 2"],'
            '  "secret_shame": "verguenza secreta",'
            '  "coping_mechanisms": ["mecanismo 1"]'
            "}\n\n"
            "REGLAS:\n"
            "- NO generes perfiles genericos o de Wikipedia\n"
            "- Debe sentirse como el nucleo psicologico REAL del personaje\n"
            "- Incluye contradicciones y ambiguedad\n"
            "- Los deseos ocultos deben ser especificos, no abstractos\n"
            "- Las heridas emocionales deben tener origen en eventos de vida\n"
            "- La filosofia de vida debe ser personal, no un cliche"
        )

        try:
            result = self._mm.generate(
                messages=[
                    {"role": "system", "content": "Eres un escritor de perfiles psicologicos. Responde SOLO con JSON valido."},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                max_tokens=2048,
                temperature=0.75,
            )
            text = result["choices"][0]["message"].get("content", "")
            compressed = self._parse_compressed_json(text)
            if compressed and compressed.get("core_identity"):
                compressed["_generated_by"] = "llm"
                return compressed
        except Exception as e:
            self._log_warning(f"Error en compresion con LLM: {e}")

        return self._compress_heuristic(state, total_events)

    def _compress_heuristic(self, state: _SoulState, total_events: int) -> dict:
        """Compresion basada en reglas cuando no hay LLM."""
        traits = state.core_traits
        mental = state.mental_state

        archetype = "The Seeker"
        if traits["conscientiousness"] > 0.7 and traits["neuroticism"] < 0.4:
            archetype = "The Pillar"
        elif traits["extraversion"] > 0.7:
            archetype = "The Socialite"
        elif traits["neuroticism"] > 0.7:
            archetype = "The Tormented"
        elif traits["openness"] > 0.7:
            archetype = "The Explorer"

        summary_parts = []
        if mental.get("happiness", 0.5) > 0.6:
            summary_parts.append("generally content")
        else:
            summary_parts.append("carries inner struggles")

        if mental.get("trust", 0.5) < 0.4:
            summary_parts.append("guarded and cautious with others")
        elif mental.get("trust", 0.5) > 0.7:
            summary_parts.append("open and trusting")

        if state.fears:
            summary_parts.append(f"haunted by {state.fears[0][:50]}")

        summary = f"A person who is {', '.join(summary_parts)}. "
        summary += f"Life has shaped them into {archetype.lower()}."

        return {
            "core_identity": {
                "summary": summary,
                "archetype": archetype,
            },
            "emotional_scars": [
                c.get("thought", "") for c in state.internal_conflicts[-5:]
                if "trust" in str(c.get("emotional_shift", {}))
            ] or ["Life experiences have left their mark"],
            "hidden_desires": state.values[:3] or ["To find meaning"],
            "contradictions": [
                "Wants connection but fears vulnerability",
                "Seeks stability but craves novelty",
            ],
            "worldview": state.worldview,
            "behavior_biases": [
                "Acts based on past experiences",
            ],
            "important_people": [],
            "life_philosophy": "Life is what happens while making other plans.",
            "speech_bias": {
                "style": "Reflective and measured",
                "quirks": ["Often references past experiences"],
            },
            "core_memories": [
                c.get("thought", "")[:100] for c in state.internal_conflicts[:3]
                if c.get("thought")
            ] or ["A life lived fully"],
            "secret_shame": "None disclosed",
            "coping_mechanisms": list(state.skills.keys())[:5] or ["reflection"],
            "_generated_by": "heuristic",
        }

    def _parse_compressed_json(self, text: str) -> Optional[dict]:
        """Parsea el JSON comprimido del alma."""
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start == -1 or end <= start:
                return None
            return json.loads(text[start:end])
        except Exception:
            return None

    # ==================================================================
    # CHECKPOINT SYSTEM
    # ==================================================================

    def _save_checkpoint(
        self,
        path: Optional[Path],
        current_month: int,
        state: _SoulState,
        character_name: str = "",
    ) -> None:
        """Guarda checkpoint para permitir reanudacion."""
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            cp = {
                "character_name": character_name,
                "current_month": current_month,
                "genome": asdict(self._genome) if hasattr(self, '_genome') and self._genome else None,
                "soul_state": {
                    "age_months": state.age_months,
                    "core_traits": state.core_traits,
                    "mental_state": state.mental_state,
                    "beliefs": state.beliefs,
                    "worldview": state.worldview,
                    "values": state.values,
                    "fears": state.fears,
                    "internal_conflicts": state.internal_conflicts[-50:],
                    "goals": state.goals,
                    "skills": state.skills,
                    "economic_state": state.economic_state,
                    "event_count": state.event_count,
                },
                "chroma_ready": self._chroma is not None and self._chroma.is_available,
                "timestamp": time.time(),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cp, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log_warning(f"Error guardando checkpoint: {e}")

    def _load_checkpoint(self, path: Path) -> Optional[dict]:
        """Carga checkpoint guardado."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _restore_soul_state(self, state_data: dict) -> None:
        """Restaura el estado del alma desde un checkpoint."""
        if not self._soul_state:
            self._soul_state = _SoulState()

        for key, val in state_data.items():
            if hasattr(self._soul_state, key):
                setattr(self._soul_state, key, val)

    def _cleanup_checkpoints(self, path: Optional[Path]) -> None:
        """Elimina archivos de checkpoint al completar."""
        if path and path.exists():
            try:
                path.unlink()
                self._log_debug("SOUL", "Checkpoints cleanup done.")
            except Exception:
                pass

    def _save_soul_json(self, path: Path, data: dict) -> None:
        """
        Guarda el soul.json final con estructura completa:
        - compressed: nucleo psicologico comprimido
        - events: eventos de vida con psychological_impact
        - beliefs: creencias formadas
        - genome: temperamento innato usado
        """
        soul_output = {
            "version": "2.0",
            "compressed": data.get("compressed", data),
            "events_count": data.get("events_generated", 0),
            "life_months": data.get("life_months",
                self._soul_state.age_months if self._soul_state else 0),
            "memory_loss_start_age": self._soul_state.memory_loss_start_age if self._soul_state else 0,
            "world_context": {
                "world_type": getattr(self, "_world_type", "real"),
                "country": getattr(self, "_country", "US"),
                "birth_year": getattr(self, "_birth_year", 2000),
                "economy": getattr(self, "_economy", "stable"),
                "family_income": getattr(self, "_family_income", "middle_class"),
                "world_description": getattr(self, "_world_description", ""),
                "use_historical_context": getattr(self, "_use_historical_context", False),
                "fictional_lore_reference": getattr(self, "_fictional_lore_reference", ""),
            }
        }

        # Incluir beliefs si existen
        if self._soul_state and hasattr(self._soul_state, 'beliefs') and self._soul_state.beliefs:
            beliefs_list = []
            for bid, bdata in self._soul_state.beliefs.items():
                if isinstance(bdata, dict):
                    beliefs_list.append({
                        "id": bid,
                        "content": bdata.get("content", ""),
                        "strength": bdata.get("strength", 0.5),
                        "source": bdata.get("source_event", ""),
                    })
            soul_output["beliefs"] = beliefs_list

        # Incluir genome si se cargo
        if hasattr(self, '_genome') and self._genome:
            genome_dict = {k: getattr(self._genome, k) for k in
                ["sociability", "emotional_sensitivity", "impulsivity",
                 "risk_aversion", "empathy", "curiosity", "security_need",
                 "independence", "creativity", "aggression",
                 "emotional_regulation", "persistence", "playfulness"]}
            soul_output["genome"] = genome_dict

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(soul_output, f, ensure_ascii=False, indent=2)
        self._log_info(f"Soul saved: {path}")

    def _add_event_to_history(self, event_id: str, month: int, event: dict, psy_impact: dict) -> None:
        """Agrega un evento procesado al historial en disco life_events.json."""
        if not getattr(self, "_save_events_history", True):
            return
        if not self._char_dir:
            return
        
        history_dir = self._char_dir / "memory"
        history_dir.mkdir(parents=True, exist_ok=True)
        history_path = history_dir / "life_events.json"
        
        event_history = []
        if history_path.exists():
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    event_history = json.load(f)
            except Exception:
                event_history = []
                
        # Evitar duplicados si por casualidad se procesa dos veces
        if any(e.get("event_id") == event_id for e in event_history):
            return
            
        history_entry = {
            "event_id": event_id,
            "month": month,
            "age_years": month // 12,
            "age_months": month % 12,
            "type": event.get("type", "unknown"),
            "description": event.get("description", ""),
            "importance": event.get("importance", 0.5),
            "emotion": event.get("emotion", "neutral"),
            "location": event.get("location", "unknown"),
            "people_involved": event.get("people_involved", []),
            "psychological_impact": psy_impact,
            "belief_formed": event.get("belief_formed", ""),
            "reflection": event.get("reflection", ""),
            "coping_strategy": event.get("coping_strategy", ""),
        }
        event_history.append(history_entry)
        
        try:
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(event_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log_warning(f"Error escribiendo life_events.json: {e}")


# ======================================================================
# FORWARD DECLARATION: RuntimeSoulAccessor
# ======================================================================

class RuntimeSoulAccessor:
    """
    Proporciona acceso en tiempo de ejecucion al sistema Soul.
    Se inicializa durante load_character() si existe soul.json.
    """

    def __init__(
        self,
        char_dir: Path,
        soul_generator: SoulGenerator,
        log_debug_fn: Callable = None,
    ):
        self._char_dir = char_dir
        self._generator = soul_generator
        self._log = log_debug_fn or (lambda t, m: None)

        self._soul_data: Optional[dict] = None
        self._chroma: Optional[ChromaStore] = None
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    def initialize(self) -> bool:
        """Carga soul.json e inicializa ChromaDB."""
        soul_path = self._char_dir / "soul.json"
        if not soul_path.exists():
            return False

        try:
            with open(soul_path, "r", encoding="utf-8") as f:
                self._soul_data = json.load(f)
        except Exception:
            return False

        # Inicializar ChromaDB
        self._chroma = ChromaStore(self._char_dir / "memory" / "life_timeline", "life_timeline", log_fn=lambda m: self._log("SOUL", m))
        chroma_ok = self._chroma.initialize()

        self._active = True
        self._log("SOUL", f"Soul accessor active. ChromaDB: {'OK' if chroma_ok else 'N/A'}")

        return True

    def get_soul_block(self) -> str:
        """
        Genera el bloque de texto del alma para inyectar en el system prompt.
        """
        if not self._active or not self._soul_data:
            return ""

        core = self._soul_data.get("core_identity", {})
        summary = core.get("summary", "")
        archetype = core.get("archetype", "")
        philosophy = self._soul_data.get("life_philosophy", "")

        parts = ["[SOUL SYSTEM - Nucleo Psicologico del Personaje]"]

        if summary:
            parts.append(f"Identidad: {summary}")
        if archetype:
            parts.append(f"Arquetipo: {archetype}")
        if philosophy:
            parts.append(f"Filosofia de Vida: {philosophy}")

        world = self._soul_data.get("world_context", {})
        if world:
            parts.append("Contexto del Mundo Natal en el que creció:")
            w_type_label = "Ficticio/Fantasía" if world.get("world_type") == "fictional" else "Mundo Real"
            parts.append(f"- Tipo de Mundo: {w_type_label}")
            parts.append(f"- País/Región/Reino: {world.get('country', 'US')}")
            parts.append(f"- Año de Nacimiento: {world.get('birth_year', 2000)}")
            parts.append(f"- Situación Económica: {world.get('economy', 'stable')}")
            parts.append(f"- Nivel de Ingresos Familiares: {world.get('family_income', 'middle_class')}")
            if world.get("world_type") == "real":
                parts.append(f"- Usar Contexto Histórico Real: {'Sí' if world.get('use_historical_context') else 'No'}")
            else:
                if world.get("fictional_lore_reference"):
                    parts.append(f"- Referencia de Lore/Libro: {world.get('fictional_lore_reference')}")
            if world.get("world_description"):
                parts.append(f"- Descripción y Leyes del Entorno: {world.get('world_description')}")

        scars = self._soul_data.get("emotional_scars", [])
        if scars:
            parts.append("Heridas Emocionales:")
            for s in scars[:3]:
                parts.append(f"- {s[:200]}")

        contradictions = self._soul_data.get("contradictions", [])
        if contradictions:
            parts.append("Contradicciones Internas:")
            for c in contradictions[:3]:
                parts.append(f"- {c}")

        desires = self._soul_data.get("hidden_desires", [])
        if desires:
            parts.append("Deseos Ocultos:")
            for d in desires[:3]:
                parts.append(f"- {d}")

        worldview = self._soul_data.get("worldview", {})
        if worldview:
            parts.append(
                f"Vision del Mundo: "
                f"Optimismo={worldview.get('optimism', 0.5):.1f}, "
                f"Moral={worldview.get('morality', 0.5):.1f}, "
                f"Individualismo={worldview.get('individualism', 0.5):.1f}"
            )

        speech_bias = self._soul_data.get("speech_bias", {})
        if speech_bias:
            style = speech_bias.get("style", "")
            quirks = speech_bias.get("quirks", [])
            if style:
                parts.append(f"Estilo de Habla (Influencia del Alma): {style}")
            if quirks:
                for q in quirks:
                    parts.append(f"- Particularidad: {q}")

        return "\n".join(parts)

    def retrieve_context(self, query: str, top_k: int = 3) -> str:
        """
        Recupera recuerdos relevantes del timeline de vida y los
        formatea para inyectar en el contexto.
        """
        if not self._active or not self._chroma or not self._chroma.is_available:
            return ""

        # Recuperar más candidatos para poder filtrar y ordenar por decaimiento
        results = self._chroma.search(query, top_k=top_k * 3)

        if not results:
            return ""

        scored = []
        for r in results:
            meta = r.get("metadata", {})
            similarity = r.get("similarity", 0.5)
            
            try:
                importance = float(meta.get("importance", 0.5))
            except (TypeError, ValueError):
                importance = 0.5
                
            try:
                emotional_weight = float(meta.get("emotional_weight", 0.5))
            except (TypeError, ValueError):
                emotional_weight = 0.5

            try:
                age_months = int(meta.get("age_months", meta.get("month", 0)))
            except (TypeError, ValueError):
                age_months = 0

            event_age_years = age_months / 12.0

            # Filtro de pérdida de memoria consciente (amnesia infantil)
            memory_loss_age = 0
            if self._soul_data:
                memory_loss_age = self._soul_data.get("memory_loss_start_age", 0)

            # 1. Amnesia Infantil Gradual
            if event_age_years < 3.0:
                continue  # Amnesia absoluta antes de los 3 años
            elif memory_loss_age > 0 and event_age_years < memory_loss_age:
                # Solo se recuerdan de forma consciente eventos de gran importancia/impacto
                if importance < 0.75 and emotional_weight < 0.75:
                    continue

            # 2. Decaimiento Temporal Exponencial (Fading)
            current_age_months = 1200
            if self._soul_data:
                try:
                    current_age_months = int(self._soul_data.get("life_months", 1200))
                except (TypeError, ValueError):
                    current_age_months = 1200
            
            elapsed_years = max(0.0, (current_age_months - age_months) / 12.0)
            
            max_importance = max(importance, emotional_weight)
            # El decaimiento disminuye según la importancia (importancia=1.0 -> sin decaimiento)
            decay_rate = 0.15 * ((1.0 - max_importance) ** 2)
            retention = math.exp(-decay_rate * elapsed_years)

            # Olvido completo si decae demasiado, a menos que sea muy importante (turning point)
            if retention < 0.15 and max_importance < 0.75:
                continue

            score = (
                similarity * 0.40 +
                importance * 0.25 +
                emotional_weight * 0.15 +
                retention * 0.20
            )
            scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        filtered_results = [r for _, r in scored[:top_k]]

        if not filtered_results:
            return ""

        parts = ["[RECUERDOS VIVIDOS — Recuperados por relevancia al contexto actual]"]
        for r in filtered_results:
            meta = r.get("metadata", {})
            try:
                imp = float(meta.get("importance", 0))
            except (TypeError, ValueError):
                imp = 0.5
            emotion = meta.get("emotion", "neutral")
            age = meta.get("age", "?")
            desc = r.get("description", "")
            # Solo incluir si hay contenido sustancial
            if desc and len(desc) > 10:
                imp_label = "★" if imp > 0.7 else "♦" if imp > 0.5 else "•"
                parts.append(f"{imp_label} (Edad {age}, {emotion}): {desc[:300]}")

        if len(parts) == 1:
            return ""

        return "\n".join(parts)
