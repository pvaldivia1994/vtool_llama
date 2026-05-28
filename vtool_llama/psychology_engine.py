"""
Psychology Engine para vtool_llama.

Provee síntesis runtime de psicología emergente:
- PsychologySynthesizer: Genome + Soul + contexto → PsychologyState
- EmotionalDynamics: decaimiento, inercia, triggers emocionales
- PersonaCompiler: PsychologyState + contexto → PersonaState
- DriftDetector: feedback loop comportamiento→personalidad
- BeliefManager: formación y refuerzo de creencias

Flujo principal:
  load_character → PsychologySynthesizer.synthesize()
  cada N turnos → PsychologySynthesizer.tick()
  cada turno → PersonaCompiler.compile() 
  después de respuesta → DriftDetector.feed()
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .types import (
    BeliefEntry,
    DriftEntry,
    EmotionalState,
    Genome,
    PersonaState,
    PsychologyState,
    SoulEvent,
)


# ======================================================================
# EMOTIONAL DYNAMICS
# ======================================================================

class EmotionalDynamics:
    """
    Sistema emocional multi-eje con:
    - Valence/Arousal (circumplex de Russell)
    - Decaimiento temporal
    - Inercia emocional
    - Triggers por eventos
    """

    # Mapa de emociones a coordenadas valence/arousal
    EMOTION_MAP: dict[str, tuple[float, float]] = {
        "joy": (0.8, 0.6), "excitement": (0.6, 0.8),
        "contentment": (0.6, -0.3), "serenity": (0.4, -0.7),
        "hope": (0.5, 0.3), "pride": (0.6, 0.4),
        "love": (0.9, 0.5), "gratitude": (0.7, -0.1),
        "sadness": (-0.7, -0.4), "grief": (-0.9, -0.5),
        "melancholy": (-0.4, -0.6), "nostalgia": (0.1, -0.3),
        "anger": (-0.7, 0.8), "frustration": (-0.5, 0.6),
        "rage": (-0.9, 0.9), "annoyance": (-0.3, 0.4),
        "fear": (-0.6, 0.8), "anxiety": (-0.4, 0.6),
        "terror": (-0.9, 0.9), "worry": (-0.3, 0.4),
        "surprise": (0.1, 0.8), "shock": (-0.3, 0.9),
        "disgust": (-0.6, 0.3), "contempt": (-0.5, 0.2),
        "guilt": (-0.5, -0.2), "shame": (-0.7, -0.3),
        "trust": (0.5, -0.2), "acceptance": (0.4, -0.4),
        "anticipation": (0.2, 0.6), "interest": (0.4, 0.5),
        "boredom": (-0.3, -0.6), "apathy": (-0.2, -0.7),
        "neutral": (0.0, 0.0),
    }

    DECAY_RATE: float = 0.15
    SECONDARY_DECAY: float = 0.10
    INERTIA_MIN: float = 0.1
    INERTIA_MAX: float = 0.8

    def __init__(
        self,
        inertia: float = 0.3,
        log_fn: Optional[Callable] = None,
    ):
        self._inertia = max(self.INERTIA_MIN, min(self.INERTIA_MAX, inertia))
        self._log = log_fn or (lambda msg: None)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def create_default(self) -> EmotionalState:
        """Crea un estado emocional neutral."""
        now = datetime.now(timezone.utc).isoformat()
        return EmotionalState(
            valence=0.0,
            arousal=0.0,
            dominant_emotion="neutral",
            secondary_emotions={},
            last_update=now,
            emotional_inertia=self._inertia,
        )

    def decay(self, state: EmotionalState) -> EmotionalState:
        """
        Aplica decaimiento temporal al estado emocional.
        Las emociones tienden a neutral con el tiempo.
        """
        if not state.last_update:
            return state

        try:
            last = datetime.fromisoformat(state.last_update)
            now = datetime.now(timezone.utc)
            delta_hours = (now - last).total_seconds() / 3600.0
        except (ValueError, TypeError):
            delta_hours = 0.0

        if delta_hours <= 0:
            return state

        decay_factor = math.exp(-self.DECAY_RATE * delta_hours)

        new_valence = state.valence * decay_factor
        new_arousal = state.arousal * decay_factor

        # Decaimiento de emociones secundarias
        new_secondary = {}
        for k, v in state.secondary_emotions.items():
            new_v = v * math.exp(-self.SECONDARY_DECAY * delta_hours)
            if abs(new_v) > 0.05:
                new_secondary[k] = new_v

        # Si ambas están cerca de neutral, determinar emoción dominante
        if abs(new_valence) < 0.1 and abs(new_arousal) < 0.1:
            dominant = "neutral"
        else:
            dominant = self._valence_arousal_to_emotion(new_valence, new_arousal)

        state.valence = new_valence
        state.arousal = new_arousal
        state.dominant_emotion = dominant
        state.secondary_emotions = new_secondary
        state.last_update = datetime.now(timezone.utc).isoformat()

        return state

    def apply_trigger(
        self,
        state: EmotionalState,
        target_valence: float,
        target_arousal: float,
        trigger_emotion: Optional[str] = None,
    ) -> EmotionalState:
        """
        Aplica un cambio emocional con inercia.
        No cambia instantáneamente: respeta emotional_inertia.
        """
        inertia = state.emotional_inertia

        # Con inercia, el cambio es parcial
        if inertia > 0:
            delta_v = target_valence - state.valence
            delta_a = target_arousal - state.arousal
            new_valence = state.valence + delta_v * (1 - inertia)
            new_arousal = state.arousal + delta_a * (1 - inertia)
        else:
            new_valence = target_valence
            new_arousal = target_arousal

        # Clampear
        new_valence = max(-1.0, min(1.0, new_valence))
        new_arousal = max(-1.0, min(1.0, new_arousal))

        # Determinar emoción dominante
        if trigger_emotion and trigger_emotion in self.EMOTION_MAP:
            dominant = trigger_emotion
        else:
            dominant = self._valence_arousal_to_emotion(new_valence, new_arousal)

        # Si hay trigger_emotion, agregarla a secundarias
        new_secondary = dict(state.secondary_emotions)
        if trigger_emotion and trigger_emotion != dominant:
            current = new_secondary.get(trigger_emotion, 0.0)
            # Calcular intensidad desde la distancia
            coord = self.EMOTION_MAP.get(trigger_emotion, (0, 0))
            dist = math.sqrt(
                (coord[0] - new_valence) ** 2 +
                (coord[1] - new_arousal) ** 2
            )
            intensity = max(0.0, 1.0 - dist)
            new_secondary[trigger_emotion] = max(current, intensity * 0.5)

        state.valence = new_valence
        state.arousal = new_arousal
        state.dominant_emotion = dominant
        state.secondary_emotions = new_secondary
        state.last_update = datetime.now(timezone.utc).isoformat()

        return state

    def apply_text_trigger(
        self,
        state: EmotionalState,
        text: str,
    ) -> EmotionalState:
        """
        Analiza un texto (prompt del usuario) y aplica trigger emocional
        heurístico basado en palabras clave.
        """
        lower = text.lower()

        # Palabras clave positivas
        positive_words = [
            "gracias", "te quiero", "te amo", "feliz", "hermoso",
            "maravilloso", "genial", "excelente", "bien", "alegre",
            "love", "happy", "wonderful", "great", "amazing",
            "thank", "beautiful", "cute", "adorable", "nice",
        ]
        # Palabras clave negativas
        negative_words = [
            "odio", "detesto", "triste", "enojado", "furioso",
            "horrible", "terrible", "miedo", "asustado", "pésimo",
            "hate", "angry", "sad", "terrible", "horrible",
            "afraid", "scared", "upset", "furious", "awful",
        ]
        # Palabras de pérdida/trauma
        loss_words = [
            "murió", "perdi", "terminó", "adios", "nunca más",
            "dead", "die", "lost", "gone", "forever", "never",
        ]
        # Palabras agresivas
        aggressive_words = [
            "callate", "idiota", "estúpido", "imbécil", "vete",
            "shut up", "stupid", "idiot", "leave", "go away",
        ]

        positive_count = sum(1 for w in positive_words if w in lower)
        negative_count = sum(1 for w in negative_words if w in lower)
        loss_count = sum(1 for w in loss_words if w in lower)
        aggressive_count = sum(1 for w in aggressive_words if w in lower)

        # Calcular targets
        if aggressive_count >= 2:
            target_v = -0.6
            target_a = 0.7
            trigger = "anger"
        elif loss_count >= 1:
            target_v = -0.7
            target_a = -0.3
            trigger = "sadness"
        elif negative_count > positive_count:
            intensity = min(1.0, negative_count * 0.15)
            target_v = -0.3 * intensity
            target_a = 0.2 * intensity
            trigger = "sadness" if negative_count > 3 else "anxiety"
        elif positive_count > negative_count:
            intensity = min(1.0, positive_count * 0.12)
            target_v = 0.4 * intensity
            target_a = 0.1 * intensity
            trigger = "joy" if positive_count > 3 else "contentment"
        else:
            return state  # No trigger

        return self.apply_trigger(state, target_v, target_a, trigger)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _valence_arousal_to_emotion(self, v: float, a: float) -> str:
        """Encuentra la emoción más cercana en el circumplex."""
        best = "neutral"
        best_dist = float("inf")
        for emotion, (ev, ea) in self.EMOTION_MAP.items():
            dist = math.sqrt((v - ev) ** 2 + (a - ea) ** 2)
            if dist < best_dist:
                best_dist = dist
                best = emotion
        return best


# ======================================================================
# PSYCHOLOGY SYNTHESIZER
# ======================================================================

class PsychologySynthesizer:
    """
    Sintetiza PsychologyState desde Genome + Soul events + runtime data.

    Se llama:
    - Al cargar personaje (full synthesis)
    - Cada N turnos (tick synthesis, más barato)
    - Cuando ocurre un evento importante (triggered synthesis)
    """

    def __init__(
        self,
        log_debug_fn: Optional[Callable] = None,
        log_info_fn: Optional[Callable] = None,
    ):
        self._log_debug = log_debug_fn or (lambda t, m: None)
        self._log_info = log_info_fn or (lambda m: None)
        self._emotion = EmotionalDynamics(log_fn=log_debug_fn)

    # ------------------------------------------------------------------
    # Full synthesis (on load)
    # ------------------------------------------------------------------

    def synthesize(
        self,
        genome: Genome,
        soul_events: list[dict],
        beliefs: list[BeliefEntry],
        runtime_emotional: Optional[EmotionalState] = None,
    ) -> PsychologyState:
        """
        Síntesis completa: Genome + Soul events → PsychologyState.
        Se ejecuta al cargar personaje.

        Args:
            genome: temperamento innato
            soul_events: eventos de vida (dicts con psychological_impact opcional)
            beliefs: creencias formadas
            runtime_emotional: estado emocional actual (si existe)

        Returns:
            PsychologyState sintetizado
        """
        # 1. Big Five desde genome baseline
        big_five = self._genome_to_big_five(genome)

        # 2. Aplicar impactos de eventos de vida
        for event in soul_events:
            impact = event.get("psychological_impact", {}) or {}
            for axis, delta in impact.items():
                if axis in big_five:
                    big_five[axis] = max(0.05, min(0.95, big_five[axis] + delta))

        # 3. Determinar attachment style desde eventos tempranos
        attachment = self._compute_attachment(soul_events, beliefs)

        # 4. Computar worldview desde creencias + eventos
        worldview = self._compute_worldview(genome, beliefs, soul_events)

        # 5. Computar necesidades
        needs = self._compute_needs(genome, big_five, worldview)

        # 6. Heridas activas
        wounds = self._compute_active_wounds(soul_events, beliefs)

        # 7. Mecanismos de coping
        coping = self._compute_coping(soul_events)

        # 8. Conflictos internos
        conflicts = self._compute_conflicts(beliefs, big_five, worldview)

        # 9. Sesgos activos
        biases = self._compute_biases(genome, beliefs, soul_events)

        ps = PsychologyState(
            current_big_five=big_five,
            attachment_style=attachment,
            needs=needs,
            active_wounds=wounds,
            active_coping=coping,
            active_conflicts=conflicts,
            active_biases=biases,
            worldview=worldview,
            version=1,
        )

        self._log_debug("PSY", f"Psychology synthesized: big_five={big_five}, attachment={attachment}")

        return ps

    # ------------------------------------------------------------------
    # Tick synthesis (runtime, cheaper)
    # ------------------------------------------------------------------

    def tick(
        self,
        current: PsychologyState,
        genome: Genome,
        recent_interactions: list[dict],
        beliefs: list[BeliefEntry],
    ) -> PsychologyState:
        """
        Síntesis ligera para runtime.
        No regenera desde cero, solo aplica deriva ligera.
        """
        new = PsychologyState(**{
            k: (dict(v) if isinstance(v, dict) else
                list(v) if isinstance(v, list) else v)
            for k, v in asdict(current).items()
        })
        new.version = current.version + 1

        # Analizar interacciones recientes para detectar patrones
        if recent_interactions:
            valence_sum = 0
            arousal_sum = 0
            count = 0

            for interaction in recent_interactions[-10:]:
                text = interaction.get("response", "") or ""
                lower = text.lower()
                # Heurística simple: palabras positivas/negativas
                pos = sum(1 for w in ["gracias", "feliz", "bien", "mejor", "amo", "encanta"] if w in lower)
                neg = sum(1 for w in ["triste", "mal", "peor", "odio", "temo", "duele"] if w in lower)
                if pos > neg:
                    valence_sum += 0.05 * min(pos, 3)
                    arousal_sum += 0.02 * min(pos, 3)
                elif neg > pos:
                    valence_sum -= 0.05 * min(neg, 3)
                    arousal_sum += 0.03 * min(neg, 3)
                count += 1

            if count > 0:
                avg_valence = valence_sum / count
                avg_arousal = arousal_sum / count

                # Aplicar deriva ligera a worldview
                new.worldview["optimism"] = max(
                    0.05, min(0.95,
                        new.worldview["optimism"] + avg_valence * 0.1
                    )
                )
                new.worldview["trust_in_people"] = max(
                    0.05, min(0.95,
                        new.worldview["trust_in_people"] + avg_valence * 0.05
                    )
                )

                # Deriva en big five
                if abs(avg_valence) > 0.1:
                    new.current_big_five["neuroticism"] = max(
                        0.05, min(0.95,
                            new.current_big_five["neuroticism"] - avg_valence * 0.05
                        )
                    )

        self._log_debug("PSY", f"Psychology tick: version={new.version}")

        return new

    # ------------------------------------------------------------------
    # Event-based synthesis (por evento importante en runtime)
    # ------------------------------------------------------------------

    def process_event(
        self,
        current: PsychologyState,
        event: dict,
        genome: Genome,
        core_identity: Optional[Any] = None,
        beliefs: Optional[list] = None,
        age_months: int = 0,
    ) -> dict:
        """
        Pipeline causal completo de procesamiento psicológico de un evento.

        event
        → perception filter (via CoreIdentity)
        → emotional impact
        → belief creation / reinforcement
        → identity shift (turning point si importance > 0.8)
        → psychology update (Big Five + worldview)
        → persona adaptation signal

        Args:
            current: PsychologyState actual
            event: dict con event_type, description, importance, psychological_impact
            genome: Genome del personaje
            core_identity: CoreIdentity (opcional, para interpretación)
            beliefs: lista de BeliefEntry actuales
            age_months: edad en meses para contexto

        Returns:
            dict con:
            - psychology: PsychologyState actualizado
            - interpretation: cómo se interpretó el evento
            - belief_added: creencia nueva (o None)
            - is_turning_point: bool
            - emotion_trigger: emoción generada
            - wound_added: herida nueva (o None)
        """
        new = PsychologyState(**{
            k: (dict(v) if isinstance(v, dict) else
                list(v) if isinstance(v, list) else v)
            for k, v in asdict(current).items()
        })
        new.version = current.version + 1

        ev_type = event.get("event_type", "unknown")
        ev_desc = event.get("description", "")
        importance = event.get("importance", 0.5)
        raw_impact = event.get("psychological_impact", {}) or {}

        # ──────────────────────────────────────────────────────────
        # 1. PERCEPTION FILTER (via CoreIdentity)
        # ──────────────────────────────────────────────────────────
        interpretation = None
        if core_identity is not None and hasattr(core_identity, 'interpret_event'):
            interpretation = core_identity.interpret_event(ev_type, ev_desc, importance)
            # La interpretación modifica el impacto percibido
            perceived = interpretation.get("perceived_severity", importance)
            attribution = interpretation.get("attribution", "situation")
            generated_emotion = interpretation.get("emotion", event.get("emotion", "neutral"))
            belief_impact = interpretation.get("belief_impact", {})
        else:
            perceived = importance
            attribution = "situation"
            generated_emotion = event.get("emotion", "neutral")
            belief_impact = {}
            interpretation = {
                "perceived_severity": perceived,
                "attribution": attribution,
                "emotion": generated_emotion,
            }

        # ──────────────────────────────────────────────────────────
        # 2. TURNING POINT DETECTION
        # ──────────────────────────────────────────────────────────
        is_turning_point = False
        turning_point_multiplier = 1.0
        turning_point_obj = None

        if perceived > 0.8 and ev_type in (
            "trauma", "loss", "betrayal", "violence",
            "romantic", "success", "accident", "discovery",
            "existential", "responsibility",
        ):
            is_turning_point = True
            turning_point_multiplier = 2.0 + (perceived - 0.8) * 5.0

            # Generar meaning_assigned desde la interpretación
            if attribution == "self":
                meaning = "I am responsible for what happened"
            elif attribution == "others":
                meaning = "Others cannot be trusted to protect me"
            else:
                meaning = "Life is unpredictable and cruel"
            if generated_emotion == "shame":
                meaning = "There is something fundamentally wrong with me"
            elif generated_emotion == "anger":
                meaning = "The world is unfair and I must defend myself"

            # Construir TurningPoint real
            from .types import TurningPoint
            turning_point_obj = TurningPoint(
                age=max(0, age_months // 12),
                event=ev_desc[:200],
                intensity=perceived,
                positive=generated_emotion in ("joy", "love", "pride", "hope", "gratitude"),
                changed_traits=dict(raw_impact),
                emotional_memory=ev_desc[:200],
                meaning_assigned=meaning,
            )

            # Cambiar auto-narrativa por turning point
            if core_identity is not None and hasattr(core_identity, 'self_narrative'):
                if attribution == "self" and not core_identity.self_narrative:
                    old = core_identity.self_narrative
                    if perceived > 0.85:
                        core_identity.self_narrative = meaning[:100]
                    elif old and "must" in old:
                        core_identity.self_narrative = old + " But now I know better."

            # Los turning points redefinen creencias nucleares
            if core_identity is not None and hasattr(core_identity, 'self_beliefs'):
                if attribution == "self" and generated_emotion in ("shame", "guilt", "fear"):
                    for k in core_identity.self_beliefs:
                        drop = 0.15 * turning_point_multiplier
                        core_identity.self_beliefs[k] = max(0.05, core_identity.self_beliefs[k] - drop)
                elif attribution == "others" and generated_emotion == "anger":
                    if hasattr(core_identity, 'meaning_system'):
                        core_identity.meaning_system["people_are_good"] = max(
                            0.05, core_identity.meaning_system.get("people_are_good", 0.5) - 0.2
                        )

            # Agregar miedo desde turning point
            if core_identity is not None:
                fear_map = {
                    "betrayal": "trusting others",
                    "loss": "abandonment",
                    "trauma": "being hurt again",
                    "violence": "physical harm",
                }
                new_fear = fear_map.get(ev_type, "")
                if new_fear and new_fear not in getattr(core_identity, 'core_fears', []):
                    core_identity.core_fears.append(new_fear)
                    if len(getattr(core_identity, 'core_fears', [])) > 6:
                        core_identity.core_fears = core_identity.core_fears[-6:]

        # ──────────────────────────────────────────────────────────
        # 3. PSYCHOLOGY UPDATE (Big Five + Worldview)
        # ──────────────────────────────────────────────────────────
        impact = dict(raw_impact)
        for axis, delta in impact.items():
            adjusted = delta * turning_point_multiplier
            if axis in new.current_big_five:
                new.current_big_five[axis] = max(
                    0.05, min(0.95,
                        new.current_big_five[axis] + adjusted
                    )
                )
            if axis in new.worldview:
                new.worldview[axis] = max(
                    0.05, min(0.95,
                        new.worldview[axis] + adjusted
                    )
                )

        if belief_impact and core_identity is not None:
            for k, delta in belief_impact.items():
                if hasattr(core_identity, 'self_beliefs') and k in core_identity.self_beliefs:
                    adjusted = delta * turning_point_multiplier
                    core_identity.self_beliefs[k] = max(
                        0.05, min(0.95,
                            core_identity.self_beliefs[k] + adjusted
                        )
                    )

        # ──────────────────────────────────────────────────────────
        # 4. EMOTIONAL TRIGGER
        # ──────────────────────────────────────────────────────────
        emotion_trigger = generated_emotion
        if hasattr(self, '_emotion') and hasattr(self._emotion, 'EMOTION_MAP'):
            coords = self._emotion.EMOTION_MAP.get(generated_emotion, (0, 0))
        else:
            coords = (0, 0)

        # ──────────────────────────────────────────────────────────
        # 5. BELIEF CREATION
        # ──────────────────────────────────────────────────────────
        belief_added = None
        belief_content = event.get("belief_formed", "")
        if not belief_content and perceived > 0.65 and attribution != "situation":
            # Generar creencia desde la interpretación
            if attribution == "self":
                belief_content = f"I am responsible for bad things happening"
            elif attribution == "others":
                belief_content = "Others cannot be trusted"
            belief_content = belief_content or ""

        if belief_content:
            from .types import BeliefEntry
            belief_added = BeliefEntry(
                content=belief_content,
                source_event_id=event.get("id", ""),
                strength=min(1.0, perceived * 0.8),
                category=self._event_type_to_belief_category(ev_type),
            )

        # ──────────────────────────────────────────────────────────
        # 6. WOUND CREATION
        # ──────────────────────────────────────────────────────────
        wound_added = None
        if ev_type in ("trauma", "loss", "betrayal", "violence", "discrimination") and perceived > 0.65:
            wound_text = ev_desc[:100] if ev_desc else f"Deep wound from {ev_type}"
            if wound_text and wound_text not in new.active_wounds:
                new.active_wounds.append(wound_text)
                wound_added = wound_text
                # Mantener máximo 10 heridas
                if len(new.active_wounds) > 10:
                    new.active_wounds = new.active_wounds[-10:]

        # ──────────────────────────────────────────────────────────
        # 7. TURNING POINT: identity narrative shift
        # ──────────────────────────────────────────────────────────
        if is_turning_point and core_identity is not None:
            # Turning points pueden cambiar creencias nucleares
            if attribution == "self" and perceived > 0.85:
                if hasattr(core_identity, 'self_beliefs'):
                    for k in core_identity.self_beliefs:
                        core_identity.self_beliefs[k] = max(
                            0.05, core_identity.self_beliefs[k] - 0.15 * turning_point_multiplier
                        )
            elif attribution == "others" and perceived > 0.85:
                if hasattr(core_identity, 'meaning_system'):
                    core_identity.meaning_system["people_are_good"] = max(
                        0.05, core_identity.meaning_system.get("people_are_good", 0.5) - 0.2
                    )
                    core_identity.meaning_system["world_is_fair"] = max(
                        0.05, core_identity.meaning_system.get("world_is_fair", 0.5) - 0.15
                    )

            # Actualizar miedos si el evento es traumático
            if ev_type in ("trauma", "betrayal", "loss"):
                from .types import CoreIdentity as CID
                if isinstance(core_identity, CID):
                    # Agregar miedo basado en el evento
                    fear_map = {
                        "betrayal": "trusting others",
                        "loss": "abandonment",
                        "trauma": "being hurt",
                        "violence": "physical harm",
                    }
                    new_fear = fear_map.get(ev_type, "")
                    if new_fear and new_fear not in core_identity.core_fears:
                        core_identity.core_fears.append(new_fear)
                        core_identity.core_fears = core_identity.core_fears[:5]

        # ──────────────────────────────────────────────────────────
        # 8. EMOTIONAL MEMORY CREATION
        # ──────────────────────────────────────────────────────────
        emotional_memory = None
        memory_loss_age = getattr(core_identity, 'memory_loss_start_age', 0) if core_identity else 0
        event_age_years = age_months // 12

        if importance > 0.4 and (memory_loss_age == 0 or event_age_years >= memory_loss_age):
            from .types import EmotionalMemory
            # La versión recordada puede diferir de la original por distorsión
            remembered = ev_desc[:200]
            if attribution == "self" and generated_emotion in ("shame", "guilt"):
                remembered = f"I remember failing. {ev_desc[:120]}"
            elif attribution == "others" and generated_emotion == "anger":
                remembered = f"They did this to me. {ev_desc[:120]}"
            elif importance > 0.8:
                remembered = ev_desc[:200]

            emotional_memory = EmotionalMemory(
                original_event=ev_desc[:200],
                remembered_version=remembered,
                emotional_weight=importance,
                confidence=0.9 if importance > 0.7 else 0.6,
                distortion_level=0.3 if attribution != "situation" else 0.1,
                event_month=age_months,
            )

        return {
            "psychology": new,
            "interpretation": interpretation,
            "belief_added": belief_added,
            "is_turning_point": is_turning_point,
            "turning_point": turning_point_obj,
            "emotional_memory": emotional_memory,
            "emotion_trigger": emotion_trigger,
            "wound_added": wound_added,
        }

    # Backward compat alias
    apply_runtime_event = process_event

    def _event_type_to_belief_category(self, ev_type: str) -> str:
        """Mapea tipo de evento a categoría de creencia."""
        mapping = {
            "trauma": "self", "betrayal": "trust",
            "loss": "trust", "family": "trust",
            "romantic": "trust", "friendship": "trust",
            "success": "self", "failure": "self",
            "discrimination": "worldview", "violence": "worldview",
            "crime": "worldview", "political": "worldview",
        }
        return mapping.get(ev_type, "general")

    # ------------------------------------------------------------------
    # Persona Compiler (Psychology → PersonaState)
    # ------------------------------------------------------------------

    def compile_persona(
        self,
        psychology: PsychologyState,
        emotional: EmotionalState,
        genome: Genome,
    ) -> PersonaState:
        """
        Compila PersonaState desde PsychologyState + estado emocional.

        Cada rasgo de expresión se deriva de combinaciones de
        Big Five + emociones actuales + genome.
        """
        bf = psychology.current_big_five
        v = emotional.valence
        a = emotional.arousal

        persona = PersonaState()

        # Verbosity: extraversion alta + neuroticism baja + arousal baja = más verborrágico
        persona.verbosity = max(0.0, min(1.0,
            0.3
            + bf.get("extraversion", 0.5) * 0.3
            + (1.0 - bf.get("neuroticism", 0.5)) * 0.2
            + (1.0 - abs(a)) * 0.2
        ))

        # Sarcasm tendency: playfulness + aggression - agreeableness
        sarcasm = (
            genome.playfulness * 0.3
            + genome.aggression * 0.2
            + (1.0 - bf.get("agreeableness", 0.5)) * 0.3
            + max(0, v * -0.2)  # más sarcástico cuando está de mal humor
        )
        persona.sarcasm_tendency = max(0.0, min(1.0, sarcasm))

        # Warmth: agreeableness + empathy - defensiveness emocional
        warmth = (
            bf.get("agreeableness", 0.5) * 0.4
            + genome.empathy * 0.3
            - (bf.get("neuroticism", 0.5) - 0.5) * 0.2
            + max(0, v * 0.1)  # mejor humor = más calidez
        )
        persona.warmth = max(0.0, min(1.0, warmth))

        # Defensiveness: neuroticism + risk_aversion - trust_in_people
        defensiveness = (
            bf.get("neuroticism", 0.5) * 0.3
            + genome.risk_aversion * 0.2
            + (1.0 - psychology.worldview.get("trust_in_people", 0.5)) * 0.3
            + max(0, a * 0.1)  # más activado = más defensivo
        )
        persona.defensiveness = max(0.0, min(1.0, defensiveness))

        # Speech style según combinación de rasgos
        if bf.get("extraversion", 0.5) > 0.65 and a > 0.2:
            persona.speech_style = "animated"
        elif bf.get("extraversion", 0.5) < 0.35:
            persona.speech_style = "quiet"
        elif (1.0 - bf.get("conscientiousness", 0.5)) > 0.6 and genome.playfulness > 0.6:
            persona.speech_style = "casual"
        elif v < -0.3:
            persona.speech_style = "somber"
        elif v > 0.5 and a < 0:
            persona.speech_style = "warm"
        elif a > 0.5:
            persona.speech_style = "intense"
        else:
            persona.speech_style = "neutral"

        # Humor
        if genome.playfulness > 0.6 and v > 0.2:
            if bf.get("agreeableness", 0.5) > 0.6:
                persona.humor_style = "witty"
                persona.humor_frequency = genome.playfulness * 0.6
            elif bf.get("neuroticism", 0.5) > 0.6:
                persona.humor_style = "dark"
                persona.humor_frequency = genome.playfulness * 0.4
            else:
                persona.humor_style = "self_deprecating"
                persona.humor_frequency = genome.playfulness * 0.5
        elif v < -0.4:
            persona.humor_style = "none"
            persona.humor_frequency = 0.1

        # Emotional distance: inverso de calidez + defensiveness
        persona.emotional_distance = max(0.0, min(1.0,
            1.0 - persona.warmth * 0.5 + persona.defensiveness * 0.4
        ))

        # Self-disclosure: extraversion + trust_in_people - defensiveness
        self_disc = (
            bf.get("extraversion", 0.5) * 0.3
            + psychology.worldview.get("trust_in_people", 0.5) * 0.3
            - persona.defensiveness * 0.3
            + genome.independence * -0.1
        )
        persona.self_disclosure = max(0.0, min(1.0, self_disc))

        # Uses actions: roleplay mode indicator
        persona.uses_actions = True

        persona._synthesized_at = datetime.now(timezone.utc).isoformat()

        return persona

    # ------------------------------------------------------------------
    # Getters de sub-sistemas
    # ------------------------------------------------------------------

    @property
    def emotion(self) -> EmotionalDynamics:
        return self._emotion

    # ==================================================================
    # INTERNOS
    # ==================================================================

    def _genome_to_big_five(self, genome: Genome) -> dict[str, float]:
        """Traduce genome (13 ejes innatos) a Big Five."""
        return {
            "openness": (
                genome.curiosity * 0.3
                + genome.creativity * 0.3
                + (1.0 - genome.risk_aversion) * 0.2
                + genome.independence * 0.2
            ),
            "conscientiousness": (
                genome.persistence * 0.4
                + (1.0 - genome.impulsivity) * 0.3
                + genome.emotional_regulation * 0.3
            ),
            "extraversion": (
                genome.sociability * 0.4
                + (1.0 - genome.security_need) * 0.2
                + genome.playfulness * 0.2
                + (1.0 - genome.emotional_sensitivity) * 0.2
            ),
            "agreeableness": (
                genome.empathy * 0.4
                + (1.0 - genome.aggression) * 0.3
                + genome.sociability * 0.3
            ),
            "neuroticism": (
                (1.0 - genome.emotional_regulation) * 0.3
                + genome.emotional_sensitivity * 0.3
                + genome.risk_aversion * 0.2
                + (1.0 - genome.independence) * 0.2
            ),
        }

    def _compute_attachment(
        self,
        soul_events: list[dict],
        beliefs: list[BeliefEntry],
    ) -> str:
        """Determina estilo de apego desde eventos tempranos."""
        early_events = [e for e in soul_events if e.get("month", 999) < 60]
        if not early_events:
            return "secure"

        loss_count = sum(1 for e in early_events if e.get("event_type") in ("loss", "trauma", "betrayal"))
        neglect_count = sum(1 for e in early_events if e.get("event_type") == "family" and e.get("importance", 0) > 0.6)
        love_count = sum(1 for e in early_events if e.get("event_type") in ("family", "friendship") and e.get("emotion") in ("joy", "love", "trust"))

        if loss_count >= 3:
            return "disorganized"
        if loss_count >= 2 or (neglect_count >= 2 and love_count == 0):
            return "avoidant"
        if loss_count >= 1 and love_count < 2:
            return "anxious"

        return "secure"

    def _compute_worldview(
        self,
        genome: Genome,
        beliefs: list[BeliefEntry],
        soul_events: list[dict],
    ) -> dict[str, float]:
        """Computa worldview desde creencias + eventos."""
        optimism = genome.playfulness * 0.3 + 0.3
        trust = genome.empathy * 0.3 + 0.3
        control = genome.independence * 0.2 + 0.4
        meaning = genome.curiosity * 0.3 + 0.3

        # Ajustar por creencias
        for b in beliefs:
            if b.category == "trust":
                trust += (b.strength - 0.5) * 0.2
            elif b.category == "worldview":
                if "optimism" in b.content.lower() or "hope" in b.content.lower():
                    optimism += (b.strength - 0.5) * 0.2
                if "control" in b.content.lower() or "powerless" in b.content.lower():
                    control -= (b.strength - 0.5) * 0.2

        # Ajustar por eventos traumáticos
        trauma_count = sum(1 for e in soul_events if e.get("event_type") in ("trauma", "betrayal", "violence"))
        if trauma_count > 2:
            trust = max(0.05, trust - trauma_count * 0.05)
            optimism = max(0.05, optimism - trauma_count * 0.03)
            control = max(0.05, control - trauma_count * 0.02)

        return {
            "optimism": max(0.05, min(0.95, optimism)),
            "trust_in_people": max(0.05, min(0.95, trust)),
            "sense_of_control": max(0.05, min(0.95, control)),
            "meaningfulness": max(0.05, min(0.95, meaning)),
        }

    def _compute_needs(
        self,
        genome: Genome,
        big_five: dict[str, float],
        worldview: dict[str, float],
    ) -> dict[str, float]:
        """Computa necesidades actuales. Bajo = insatisfecho = busca activamente."""
        return {
            "safety": max(0.05, min(0.95,
                1.0 - genome.risk_aversion * 0.3
                + worldview.get("sense_of_control", 0.5) * 0.3
                - big_five.get("neuroticism", 0.5) * 0.3
            )),
            "belonging": max(0.05, min(0.95,
                genome.sociability * 0.4
                + (1.0 - genome.independence) * 0.3
                - big_five.get("extraversion", 0.5) * 0.2
            )),
            "esteem": max(0.05, min(0.95,
                big_five.get("conscientiousness", 0.5) * 0.3
                + (1.0 - big_five.get("neuroticism", 0.5)) * 0.3
                + worldview.get("optimism", 0.5) * 0.2
            )),
            "autonomy": max(0.05, min(0.95,
                genome.independence * 0.5
                + big_five.get("openness", 0.5) * 0.3
            )),
            "meaning": max(0.05, min(0.95,
                genome.curiosity * 0.4
                + worldview.get("meaningfulness", 0.5) * 0.3
                + (1.0 - big_five.get("neuroticism", 0.5)) * 0.2
            )),
        }

    def _compute_active_wounds(
        self,
        soul_events: list[dict],
        beliefs: list[BeliefEntry],
    ) -> list[str]:
        """Extrae heridas emocionales activas desde eventos importantes."""
        wounds = []
        for e in soul_events:
            if e.get("importance", 0) > 0.75:
                ev_type = e.get("event_type", "")
                if ev_type in ("trauma", "loss", "betrayal", "violence", "discrimination"):
                    desc = e.get("description", "")[:100]
                    if desc:
                        wounds.append(desc)
        return wounds[:5]

    def _compute_coping(self, soul_events: list[dict]) -> list[str]:
        """Extrae mecanismos de coping desde reflexiones de eventos."""
        coping_set: set[str] = set()
        for e in soul_events:
            strategy = e.get("coping_strategy", "")
            if strategy:
                coping_set.add(strategy)
        return list(coping_set)

    def _compute_conflicts(
        self,
        beliefs: list[BeliefEntry],
        big_five: dict[str, float],
        worldview: dict[str, float],
    ) -> list[str]:
        """Detecta conflictos internos entre creencias y rasgos."""
        conflicts = []

        # Conflicto: quiere confiar pero ha aprendido a no hacerlo
        if worldview.get("trust_in_people", 0.5) < 0.3 and big_five.get("agreeableness", 0.5) > 0.6:
            conflicts.append("Wants to trust but experience says otherwise")

        # Conflicto: necesita pertenencia pero evita intimidad
        if worldview.get("trust_in_people", 0.5) < 0.4 and big_five.get("extraversion", 0.5) > 0.6:
            conflicts.append("Craves connection yet fears vulnerability")

        # Conflicto: perfeccionismo vs fracaso
        if big_five.get("conscientiousness", 0.5) > 0.7 and big_five.get("neuroticism", 0.5) > 0.6:
            conflicts.append("Driven by high standards paralyzed by fear of failure")

        return conflicts[:3]

    def _compute_biases(
        self,
        genome: Genome,
        beliefs: list[BeliefEntry],
        soul_events: list[dict],
    ) -> list[str]:
        """Determina sesgos activos."""
        biases = []
        trauma_count = sum(1 for e in soul_events if e.get("event_type") in ("trauma", "betrayal", "violence"))

        if trauma_count > 2:
            biases.append("hypervigilance")
        if genome.risk_aversion > 0.7:
            biases.append("loss_aversion")
        if genome.emotional_sensitivity > 0.7:
            biases.append("emotional_amplification")
        # Cynicism: alta agresión + baja confianza
        worldview_val = self._compute_worldview(genome, beliefs, soul_events)
        if genome.aggression > 0.6 and worldview_val.get("trust_in_people", 0.5) < 0.35:
            biases.append("cynicism")

        return biases[:5]

    # ------------------------------------------------------------------
    # Belief Manager accessor
    # ------------------------------------------------------------------

    @property
    def belief_manager(self) -> BeliefManager:
        """Retorna un BeliefManager para formación de creencias."""
        if not hasattr(self, '_belief_mgr'):
            self._belief_mgr = BeliefManager()
        return self._belief_mgr


# ======================================================================
# DRIFT DETECTOR (feedback loop comportamiento → personalidad)
# ======================================================================

class DriftDetector:
    """
    Analiza las respuestas generadas por el LLM y detecta
    desviaciones sostenidas entre el comportamiento real
    y el estado psicológico esperado.

    Si la deriva es sostenida, ajusta PsychologyState.
    """

    def __init__(
        self,
        log_fn: Optional[Callable] = None,
        drift_threshold: float = 0.15,
        min_samples: int = 5,
    ):
        self._log = log_fn or (lambda msg: None)
        self._threshold = drift_threshold
        self._min_samples = min_samples
        self._recent_responses: list[dict] = []

    def feed(self, response_text: str, expected_persona: PersonaState) -> Optional[DriftEntry]:
        """
        Analiza una respuesta del LLM y compara con la persona esperada.

        Args:
            response_text: texto generado por el LLM
            expected_persona: PersonaState esperado según psicología

        Returns:
            DriftEntry si se detectó deriva significativa, None si no
        """
        lower = response_text.lower()

        # Heurísticas de análisis
        word_count = len(response_text.split())
        avg_word_len = sum(len(w) for w in response_text.split()) / max(1, word_count)

        # Detectar calidez real en la respuesta
        warmth_words = ["por favor", "gracias", "entiendo", "lamento", "siento",
                        "please", "thank", "understand", "sorry", "aprecio",
                        "cariño", "amable", "gentil", "corazón"]
        cold_words = ["no me importa", "como sea", "da igual", "cállate",
                      "whatever", "i don't care", "shut up", "leave me"]

        warmth_count = sum(1 for w in warmth_words if w in lower)
        cold_count = sum(1 for w in cold_words if w in lower)
        warmth_ratio = (warmth_count - cold_count) / max(1, word_count * 0.1)
        warmth_ratio = max(-1.0, min(1.0, warmth_ratio))

        # Detectar verbosidad real
        expected_verbosity = expected_persona.verbosity
        # Normalizar word_count: asumir ~20 palabras por turno como promedio
        actual_verbosity = min(1.0, word_count / 50.0)

        # Detectar sarcasmo
        sarcasm_markers = ["ah, claro", "por supuesto que no", "obviamente",
                           "oh really", "sure thing", "obviously", "yeah right",
                           "claro que sí", "cómo no"]
        sarcasm_count = sum(1 for m in sarcasm_markers if m in lower)
        actual_sarcasm = min(1.0, sarcasm_count * 0.25)

        # Calcular desviaciones
        verbosity_drift = abs(actual_verbosity - expected_verbosity)
        sarcasm_drift = abs(actual_sarcasm - expected_persona.sarcasm_tendency)
        warmth_drift = abs(warmth_ratio - (expected_persona.warmth * 2 - 1))

        # Registrar
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "word_count": word_count,
            "warmth_ratio": warmth_ratio,
            "actual_verbosity": actual_verbosity,
            "actual_sarcasm": actual_sarcasm,
            "verbosity_drift": verbosity_drift,
            "sarcasm_drift": sarcasm_drift,
            "warmth_drift": warmth_drift,
        }
        self._recent_responses.append(entry)

        # Mantener solo últimos N
        if len(self._recent_responses) > self._min_samples * 3:
            self._recent_responses = self._recent_responses[-self._min_samples * 3:]

        # Detectar deriva sostenida
        if len(self._recent_responses) >= self._min_samples:
            recent = self._recent_responses[-self._min_samples:]
            avg_verbosity_drift = sum(r["verbosity_drift"] for r in recent) / len(recent)
            avg_sarcasm_drift = sum(r["sarcasm_drift"] for r in recent) / len(recent)
            avg_warmth_drift = sum(r["warmth_drift"] for r in recent) / len(recent)

            max_drift = max(avg_verbosity_drift, avg_sarcasm_drift, avg_warmth_drift)
            if max_drift > self._threshold:
                # Determinar qué eje está derivando
                if avg_verbosity_drift > self._threshold:
                    axis = "verbosity"
                    old_val = expected_verbosity
                    new_val = actual_verbosity
                elif avg_sarcasm_drift > self._threshold:
                    axis = "sarcasm"
                    old_val = expected_persona.sarcasm_tendency
                    new_val = actual_sarcasm
                else:
                    axis = "warmth"
                    old_val = expected_persona.warmth
                    new_val = max(0.0, min(1.0, (warmth_ratio + 1) / 2))

                drift_entry = DriftEntry(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    axis=axis,
                    old_value=old_val,
                    new_value=new_val,
                    reason=f"Response drift detected: {axis} ({old_val:.2f} -> {new_val:.2f}) over {self._min_samples} samples",
                    source="feedback_loop",
                )
                self._log(f"Drift detected: {drift_entry.reason}")
                # Resetear buffer después de detectar
                self._recent_responses = []
                return drift_entry

        return None

    def clear(self) -> None:
        """Limpia el buffer de respuestas."""
        self._recent_responses = []


# ======================================================================
# BELIEF MANAGER
# ======================================================================

class BeliefManager:
    """
    Gestiona formación, refuerzo y decaimiento de creencias.
    """

    def __init__(self, log_fn: Optional[Callable] = None):
        self._log = log_fn or (lambda msg: None)

    def form_belief(
        self,
        content: str,
        source_event_id: str = "",
        category: str = "general",
        strength: float = 0.5,
        month: int = 0,
    ) -> BeliefEntry:
        """Crea una nueva creencia."""
        return BeliefEntry(
            content=content,
            source_event_id=source_event_id,
            strength=strength,
            category=category,
            formed_at_month=month,
        )

    def reinforce(self, belief: BeliefEntry, amount: float = 0.1) -> BeliefEntry:
        """Refuerza una creencia existente."""
        belief.strength = max(0.05, min(1.0, belief.strength + amount))
        return belief

    def weaken(self, belief: BeliefEntry, amount: float = 0.1) -> BeliefEntry:
        """Debilita una creencia."""
        belief.strength = max(0.05, min(1.0, belief.strength - amount))
        if belief.strength < 0.1:
            belief.content = f"(weakened) {belief.content}"
        return belief

    def decay_all(self, beliefs: list[BeliefEntry], factor: float = 0.02) -> list[BeliefEntry]:
        """Decaimiento general de todas las creencias no reforzadas."""
        for b in beliefs:
            b.strength = max(0.05, b.strength - factor)
        return [b for b in beliefs if b.strength > 0.05]


# ======================================================================
# RUNTIME SOUL MANAGER (evolución del alma en runtime)
# ======================================================================

class RuntimeSoulManager:
    """
    Permite que el alma evolucione durante la conversación.

    - add_runtime_event: agrega una experiencia vivida CON el usuario
    - add_belief: forma una nueva creencia
    - synthesize: regenera PsychologyState desde el alma actualizada
    - get_context_for_prompt: prepara el bloque soul para el prompt
    """

    def __init__(
        self,
        char_dir: Path,
        genome: Genome,
        synthesizer: PsychologySynthesizer,
        log_debug_fn: Optional[Callable] = None,
        log_info_fn: Optional[Callable] = None,
    ):
        self._char_dir = char_dir
        self._genome = genome
        self._synth = synthesizer
        self._log_debug = log_debug_fn or (lambda t, m: None)
        self._log_info = log_info_fn or (lambda m: None)

        self._soul_events: list[dict] = []
        self._beliefs: list[BeliefEntry] = []
        self._psychology: Optional[PsychologyState] = None
        self._persona: Optional[PersonaState] = None
        self._emotional: Optional[EmotionalState] = None
        self._core_identity: Optional[Any] = None
        self._turning_points: list[Any] = []
        self._emotional_memories: list[Any] = []
        self._version: int = 0

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Carga alma + psicología desde disco."""
        soul_path = self._char_dir / "soul" / "soul.json"
        psych_path = self._char_dir / "psychology" / "current_state.json"
        beliefs_path = self._char_dir / "soul" / "beliefs.json"
        emotional_path = self._char_dir / "psychology" / "emotional_state.json"

        # Cargar soul events
        if soul_path.exists():
            try:
                with open(soul_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._soul_events = data.get("events", [])
                self._log_debug("SOUL", f"Loaded {len(self._soul_events)} soul events")
            except Exception as e:
                self._log_debug("SOUL", f"Error loading soul: {e}")

        # Cargar creencias
        if beliefs_path.exists():
            try:
                with open(beliefs_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._beliefs = [BeliefEntry(**b) for b in data.get("beliefs", [])]
                self._log_debug("SOUL", f"Loaded {len(self._beliefs)} beliefs")
            except Exception as e:
                self._log_debug("SOUL", f"Error loading beliefs: {e}")

        # Cargar psicología
        if psych_path.exists():
            try:
                with open(psych_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._psychology = PsychologyState(**data)
            except Exception:
                self._psychology = None

        # Cargar emocional
        if emotional_path.exists():
            try:
                with open(emotional_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._emotional = EmotionalState(**data)
            except Exception:
                self._emotional = None

    def save(self) -> None:
        """Persiste todo el estado a disco."""
        (self._char_dir / "soul").mkdir(parents=True, exist_ok=True)
        (self._char_dir / "psychology").mkdir(parents=True, exist_ok=True)

        # Guardar creencias
        beliefs_data = {
            "beliefs": [asdict(b) for b in self._beliefs],
            "version": self._version,
        }
        with open(self._char_dir / "soul" / "beliefs.json", "w", encoding="utf-8") as f:
            json.dump(beliefs_data, f, ensure_ascii=False, indent=2)

        # Guardar psicología
        if self._psychology:
            with open(self._char_dir / "psychology" / "current_state.json", "w", encoding="utf-8") as f:
                json.dump(asdict(self._psychology), f, ensure_ascii=False, indent=2)

        # Guardar emocional
        if self._emotional:
            with open(self._char_dir / "psychology" / "emotional_state.json", "w", encoding="utf-8") as f:
                json.dump(asdict(self._emotional), f, ensure_ascii=False, indent=2)

        self._log_debug("SOUL", "Runtime soul state saved")

    # ------------------------------------------------------------------
    # Psychology synthesis
    # ------------------------------------------------------------------

    def synthesize_psychology(self) -> PsychologyState:
        """Sintetiza psicología desde genome + soul events + beliefs."""
        self._psychology = self._synth.synthesize(
            genome=self._genome,
            soul_events=self._soul_events,
            beliefs=self._beliefs,
        )
        self._version += 1
        return self._psychology

    def synthesize_persona(self) -> PersonaState:
        """Compila PersonaState desde psychology actual + estado emocional."""
        if not self._psychology:
            self.synthesize_psychology()
        if not self._emotional:
            self._emotional = self._synth.emotion.create_default()

        # Aplicar decaimiento emocional
        self._emotional = self._synth.emotion.decay(self._emotional)

        self._persona = self._synth.compile_persona(
            psychology=self._psychology,
            emotional=self._emotional,
            genome=self._genome,
        )
        return self._persona

    def tick(self, recent_interactions: list[dict]) -> None:
        """Tick periódico: deriva ligera + actualización emocional."""
        if self._psychology:
            self._psychology = self._synth.tick(
                current=self._psychology,
                genome=self._genome,
                recent_interactions=recent_interactions,
                beliefs=self._beliefs,
            )
        self._version += 1

    # ------------------------------------------------------------------
    # Runtime evolution
    # ------------------------------------------------------------------

    def add_runtime_event(self, event: dict) -> dict:
        """Agrega un evento runtime usando el pipeline causal completo.

        process_event pipeline:
          event → perception filter (CoreIdentity) → emotional impact
          → belief creation → identity shift → psychology update
        """
        event["id"] = f"runtime_{len(self._soul_events)}_{event.get('month', 0)}"
        self._soul_events.append(event)

        result = {"event_id": event["id"]}

        if self._psychology:
            proc_result = self._synth.process_event(
                current=self._psychology,
                event=event,
                genome=self._genome,
                core_identity=self._core_identity,
                beliefs=self._beliefs,
            )
            self._psychology = proc_result["psychology"]

            # Agregar creencia si se formó
            belief_added = proc_result.get("belief_added")
            if belief_added:
                self._beliefs.append(belief_added)
                result["belief_added"] = belief_added.content

            # Trigger emocional
            if proc_result.get("emotion_trigger"):
                emo = proc_result["emotion_trigger"]
                emotion_coords = self._synth.emotion.EMOTION_MAP.get(emo, (0, 0))
                if self._emotional:
                    self._emotional = self._synth.emotion.apply_trigger(
                        self._emotional, emotion_coords[0], emotion_coords[1], emo,
                    )

            # Almacenar turning point si existe
            tp = proc_result.get("turning_point")
            if tp:
                self._turning_points.append(tp)

            # Almacenar memoria emocional si existe
            em = proc_result.get("emotional_memory")
            if em:
                self._emotional_memories.append(em)

            result["is_turning_point"] = proc_result.get("is_turning_point", False)
            result["interpretation"] = proc_result.get("interpretation", {})

        self._version += 1
        desc = event.get('description', '')[:60]
        tp = " [TURNING POINT]" if result.get("is_turning_point") else ""
        self._log_debug("SOUL", f"Runtime event added: {desc}{tp}")
        return result

    def add_belief(self, content: str, category: str = "general", strength: float = 0.5) -> BeliefEntry:
        """Forma una nueva creencia."""
        belief = self._synth.belief_manager.form_belief(
            content=content,
            category=category,
            strength=strength,
        )
        self._beliefs.append(belief)
        self._version += 1
        return belief

    def apply_emotional_trigger(self, text: str) -> EmotionalState:
        """Aplica trigger emocional desde texto del usuario."""
        if not self._emotional:
            self._emotional = self._synth.emotion.create_default()
        self._emotional = self._synth.emotion.apply_text_trigger(self._emotional, text)
        return self._emotional

    # ------------------------------------------------------------------
    # Prompt block generation
    # ------------------------------------------------------------------

    def get_psychology_block(self) -> str:
        """Genera el bloque de psicología para el prompt."""
        if not self._psychology:
            return ""

        bf = self._psychology.current_big_five
        parts = ["[PSYCHOLOGY STATE — Estado psicológico actual]"]

        # Big Five
        parts.append(
            f"Personalidad: "
            f"Apertura={bf.get('openness', 0.5):.1f}, "
            f"Escrupulosidad={bf.get('conscientiousness', 0.5):.1f}, "
            f"Extraversión={bf.get('extraversion', 0.5):.1f}, "
            f"Amabilidad={bf.get('agreeableness', 0.5):.1f}, "
            f"Neuroticismo={bf.get('neuroticism', 0.5):.1f}"
        )

        # Apego
        parts.append(f"Apego: {self._psychology.attachment_style.capitalize()}")

        # Necesidades insatisfechas (las que están bajas)
        unsatisfied = [k for k, v in self._psychology.needs.items() if v < 0.35]
        if unsatisfied:
            parts.append(f"Necesidades activas: " + ", ".join(unsatisfied))

        # Heridas activas
        if self._psychology.active_wounds:
            wounds = self._psychology.active_wounds[:3]
            parts.append("Heridas emocionales activas:")
            for w in wounds:
                parts.append(f"- {w[:120]}")

        # Conflictos internos
        if self._psychology.active_conflicts:
            parts.append("Conflictos internos:")
            for c in self._psychology.active_conflicts[:2]:
                parts.append(f"- {c}")

        # Coping activo
        if self._psychology.active_coping:
            parts.append(f"Mecanismos de afrontamiento: {', '.join(self._psychology.active_coping[:3])}")

        return "\n".join(parts)

    def get_persona_block(self) -> str:
        """Genera el bloque de persona (expresión) para el prompt."""
        if not self._persona:
            if not self._psychology:
                self.synthesize_psychology()
            self.synthesize_persona()

        parts = ["[EXPRESSION STATE — Cómo se expresa actualmente]"]

        style_map = {
            "animated": "Animado, expresivo",
            "quiet": "Tranquilo, reservado",
            "casual": "Relajado, informal",
            "somber": "Serio, sobrio",
            "warm": "Cálido, acogedor",
            "intense": "Intenso, apasionado",
            "neutral": "Neutral, directo",
        }

        style_desc = style_map.get(self._persona.speech_style, "Neutral")
        parts.append(f"Estilo de habla: {style_desc} ({self._persona.speech_style})")

        parts.append(f"Verbosidad: {'Alta' if self._persona.verbosity > 0.65 else 'Media' if self._persona.verbosity > 0.35 else 'Baja'}")
        parts.append(f"Sarcasmo: {'Frecuente' if self._persona.sarcasm_tendency > 0.6 else 'Ocasional' if self._persona.sarcasm_tendency > 0.3 else 'Raro'}")
        parts.append(f"Calidez: {'Alta' if self._persona.warmth > 0.6 else 'Media' if self._persona.warmth > 0.35 else 'Baja'}")
        parts.append(f"Defensividad: {'Alta' if self._persona.defensiveness > 0.6 else 'Media' if self._persona.defensiveness > 0.35 else 'Baja'}")

        if self._persona.humor_style != "none":
            parts.append(f"Humor: {self._persona.humor_style.replace('_', ' ')} ({self._persona.humor_frequency:.0%} del tiempo)")

        if self._persona.emotional_distance > 0.6:
            parts.append("Distancia emocional: Mantiene distancia")
        elif self._persona.emotional_distance < 0.3:
            parts.append("Distancia emocional: Cercano, accesible")

        # Emoción actual
        if self._emotional:
            em = self._emotional.dominant_emotion
            parts.append(f"Estado de ánimo actual: {em.capitalize()}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # /timeline — Línea de vida con turning points
    # ------------------------------------------------------------------

    def get_timeline_block(self) -> str:
        """Línea de vida mostrando turning points y eventos clave."""
        parts = ["[TIMELINE — Línea de vida del personaje]"]

        memory_loss = getattr(self._core_identity, 'memory_loss_start_age', 0) if self._core_identity else 0
        if memory_loss > 0:
            parts.append(f"(No recuerda nada antes de los {memory_loss} años)")

        # Turning points ordenados por edad
        tps = sorted(self._turning_points, key=lambda t: getattr(t, 'age', 0))
        for tp in tps:
            age = getattr(tp, 'age', '?')
            event = getattr(tp, 'event', '')[:100]
            intensity = getattr(tp, 'intensity', 0)
            meaning = getattr(tp, 'meaning_assigned', '')
            bar = "█" * int(intensity * 20) + "░" * (20 - int(intensity * 20))
            parts.append(f"\n  Age {age} [{bar}]")
            if event:
                parts.append(f"  {event}")
            if meaning:
                parts.append(f"  → {meaning}")

        # Memoria emocional con distorsión
        if self._emotional_memories:
            parts.append("\n  Recuerdos (pueden estar distorsionados por el tiempo):")
            for em in self._emotional_memories[-3:]:
                original = getattr(em, 'original_event', '')[:80]
                remembered = getattr(em, 'remembered_version', '')[:80]
                distortion = getattr(em, 'distortion_level', 0)
                if distortion > 0.4:
                    parts.append(f"  ∼ Recuerda: {remembered}")
                    parts.append(f"    (Realidad: {original})")
                else:
                    parts.append(f"  • {original}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # /why — Explicación psicológica
    # ------------------------------------------------------------------

    def get_why_block(self, trigger_context: str = "") -> str:
        """
        Genera una explicación de "por qué soy como soy" que el
        personaje puede usar en conversación. Para comando /why.

        Conecta:
        - evento(s) relevante(s)
        - interpretación (filter por CoreIdentity)
        - creencia formada
        - estado psicológico actual

        Returns:
            texto narrativo para que el personaje lo use como respuesta
        """
        if not self._psychology or not self._genome:
            return ""

        psych = self._psychology
        bf = psych.current_big_five

        parts = ["[RAZÓN DE SER — Por qué soy como soy]"]

        # 1. Turning points (eventos que redefinieron identidad)
        if self._turning_points:
            parts.append("Momentos que me cambiaron:")
            for tp in self._turning_points[-3:]:
                sign = "+" if getattr(tp, 'positive', True) else "-"
                age = getattr(tp, 'age', '?')
                meaning = getattr(tp, 'meaning_assigned', '')
                emo_mem = getattr(tp, 'emotional_memory', '')[:80]
                parts.append(f"  [{sign}] Age {age}: {emo_mem}")
                if meaning:
                    parts.append(f"      → {meaning}")

        # 2. Eventos formativos (top-2 más importantes, si no hay TPs)
        elif self._soul_events:
            important_events = sorted(
                [e for e in self._soul_events if e.get("importance", 0) > 0.7],
                key=lambda e: e.get("importance", 0), reverse=True,
            )
            if important_events:
                parts.append("Experiencias que me marcaron:")
                for ev in important_events[:2]:
                    desc = ev.get("description", "")[:120]
                    imp = ev.get("importance", 0)
                    parts.append(f"- [{imp:.0%}] {desc}")

        # 2. Creencias actuales
        if self._beliefs:
            strong_beliefs = [b for b in self._beliefs if b.strength > 0.6]
            if strong_beliefs:
                parts.append("Creencias que aprendí:")
                for b in strong_beliefs[:2]:
                    parts.append(f"- {b.content[:100]}")

        # 3. Auto-narrativa
        if self._core_identity:
            narrative = getattr(self._core_identity, 'self_narrative', '')
            if narrative:
                parts.append(f"Lo que pienso de mí mismo: {narrative}")

        # 4. Conflictos internos
        if psych.active_conflicts:
            parts.append("Mis contradicciones:")
            for c in psych.active_conflicts[:2]:
                parts.append(f"- {c}")

        # 5. Necesidades insatisfechas
        unsatisfied = [k for k, v in psych.needs.items() if v < 0.35]
        if unsatisfied:
            parts.append(f"Lo que necesito y no tengo: {', '.join(unsatisfied)}")

        # 6. Cómo me afecta esto hoy
        if bf.get("neuroticism", 0.5) > 0.65:
            parts.append("Vivo con mucha intensidad emocional. Las cosas me afectan profundamente.")
        elif bf.get("neuroticism", 0.5) < 0.35:
            parts.append("Soy emocionalmente estable. Cuesta sacarme de mis casillas.")
        if bf.get("extraversion", 0.5) < 0.35:
            parts.append("Necesito mi espacio. La gente me agota si no tengo tiempo a solas.")
        elif bf.get("extraversion", 0.5) > 0.65:
            parts.append("Me energiza estar con gente. La soledad me pesa.")

        if psych.active_wounds and trigger_context:
            # Buscar si algún trigger coincide con heridas
            for w in psych.active_wounds:
                if any(word in trigger_context.lower() for word in w.lower().split()[:3]):
                    parts.append(f"(Esto me toca una herida: {w[:80]})")
                    break

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def psychology(self) -> Optional[PsychologyState]:
        return self._psychology

    @property
    def persona(self) -> Optional[PersonaState]:
        return self._persona

    @property
    def emotional(self) -> Optional[EmotionalState]:
        return self._emotional

    @property
    def genome(self) -> Genome:
        return self._genome

    @property
    def is_loaded(self) -> bool:
        return self._psychology is not None

    @property
    def active(self) -> bool:
        """El sistema está activo si hay genome (siempre hay, hasta en modo legacy)."""
        return True


# ======================================================================
# LEGACY ADAPTER: PersonalityDNA → Genome
# ======================================================================

def dna_traits_to_genome(personality_dna: Any) -> Genome:
    """
    Convierte PersonalityDNA (traits, flaws, motivations) a Genome.
    Usado para backward compatibility cuando no existe genome.json.
    """
    traits_lower = [t.lower() for t in getattr(personality_dna, 'traits', [])]
    flaws_lower = [f.lower() for f in getattr(personality_dna, 'flaws', [])]
    motivations_lower = [m.lower() for m in getattr(personality_dna, 'motivations', [])]

    all_desc = traits_lower + flaws_lower + motivations_lower

    return Genome(
        sociability=_keyword_val(all_desc, ["sociable", "outgoing", "shy", "reserved",
            "introvert", "extrovert", "friendly", "talkative"]),
        emotional_sensitivity=_keyword_val(all_desc, ["sensitive", "emotional", "delicate",
            "easily hurt", "perceptive", "intuitive", "empathic"]),
        impulsivity=_keyword_val(all_desc, ["impulsive", "reckless", "spontaneous",
            "careful", "cautious", "patient", "thoughtful"]),
        risk_aversion=_keyword_val(all_desc, ["cautious", "careful", "timid", "brave",
            "daring", "fearless", "adventurous", "fear of"]),
        empathy=_keyword_val(all_desc, ["empathetic", "compassionate", "kind", "caring",
            "cold", "distant", "detached", "understanding"]),
        curiosity=_keyword_val(all_desc, ["curious", "inquisitive", "wonder", "explore",
            "inquisitive", "questioning", "interested"]),
        security_need=_keyword_val(all_desc, ["security", "safe", "comfort", "stable",
            "routine", "predictable", "familiar"]),
        independence=_keyword_val(all_desc, ["independent", "self-reliant", "loner",
            "alone", "solitary", "autonomous", "self-sufficient"]),
        creativity=_keyword_val(all_desc, ["creative", "artistic", "imaginative",
            "innovative", "inventive", "original", "visionary"]),
        aggression=_keyword_val(all_desc, ["aggressive", "angry", "hostile", "violent",
            "confrontational", "fierce", "intense", "competitive"]),
        emotional_regulation=_keyword_val(all_desc, ["calm", "stoic", "controlled",
            "stable", "balanced", "level-headed", "serene", "patient"]),
        persistence=_keyword_val(all_desc, ["persistent", "determined", "stubborn",
            "resilient", "tenacious", "committed", "dedicated", "patient"]),
        playfulness=_keyword_val(all_desc, ["playful", "humorous", "funny", "cheerful",
            "lighthearted", "jovial", "witty", "silly"]),
    )


def _keyword_val(texts: list[str], keywords: list[str]) -> float:
    """
    Evalúa qué tan fuerte aparece un conjunto de keywords en los textos.
    Retorna 0.0 a 1.0.
    """
    if not texts:
        return 0.5
    score = 0.0
    for kw in keywords:
        for t in texts:
            if kw in t:
                score += 0.15
    return max(0.05, min(0.95, 0.5 + score))
