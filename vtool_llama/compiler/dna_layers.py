"""dna_layers.py — Capas de DNA del CharacterCompiler."""

from __future__ import annotations

from typing import Optional

from .compiler import CharacterCompiler


def _get_mod_override(self: CharacterCompiler, target_layer: str) -> str | None:
    overrides = []
    for mod in self.manager.active_mods.values():
        if mod.target_layer == target_layer and mod.override_value:
            overrides.append(mod)
    if overrides:
        overrides.sort(key=lambda m: (m.intensity, m.id), reverse=True)
        return overrides[0].override_value
    return None

CharacterCompiler._get_mod_override = _get_mod_override


def _resolve_identity(self: CharacterCompiler) -> str:
    ident = self.manager.identity
    parts = [f"[IDENTIDAD]\nNombre: {ident.name}\nRol: {ident.role}\nFondo: {ident.background}"]
    if hasattr(ident, 'age') and ident.age and ident.age != "N/A":
        parts.append(f"Edad: {ident.age}")
    return "\n".join(parts)

CharacterCompiler._resolve_identity = _resolve_identity


def _resolve_traits(self: CharacterCompiler) -> str:
    traits_override = self._get_mod_override("traits")
    if traits_override:
        return f"[RASGOS (MODIFICADO)]\n{traits_override}"

    p_dna = self.manager.personality_dna
    if not p_dna.traits:
        return ""
    return "[RASGOS]\n" + "\n".join(f"- {t}" for t in p_dna.traits)

CharacterCompiler._resolve_traits = _resolve_traits


def _resolve_motivations(self: CharacterCompiler) -> str:
    p_dna = self.manager.personality_dna
    if not hasattr(p_dna, 'motivations') or not p_dna.motivations:
        return ""
    return "[MOTIVACIONES]\n" + "\n".join(f"- {m}" for m in p_dna.motivations)

CharacterCompiler._resolve_motivations = _resolve_motivations


def _resolve_flaws(self: CharacterCompiler) -> str:
    p_dna = self.manager.personality_dna
    if not hasattr(p_dna, 'flaws') or not p_dna.flaws:
        return ""
    return "[DEFECTOS]\n" + "\n".join(f"- {f}" for f in p_dna.flaws)

CharacterCompiler._resolve_flaws = _resolve_flaws


def _resolve_speech(self: CharacterCompiler) -> str:
    speech_override = self._get_mod_override("speech")
    if speech_override:
        return f"[ESTILO DE HABLA (MODIFICADO)]\n{speech_override}"

    sp = self.manager.speech
    parts = [f"[ESTILO DE HABLA]\nEstilo: {sp.style}\nTono: {sp.tone}\nVerbosidad: {sp.verbosity}"]
    if hasattr(sp, 'emotions') and sp.emotions:
        parts.append("Emociones base: " + ", ".join(sp.emotions))
    return "\n".join(parts)

CharacterCompiler._resolve_speech = _resolve_speech


def _resolve_few_shot_examples(self: CharacterCompiler) -> str:
    sp = self.manager.speech
    if not hasattr(sp, 'examples') or not sp.examples:
        return ""
    return "[FEW SHOT EXAMPLES]\n" + "\n\n".join(sp.examples)

CharacterCompiler._resolve_few_shot_examples = _resolve_few_shot_examples


def _resolve_scenario(self: CharacterCompiler) -> str:
    ident = self.manager.identity
    if hasattr(ident, 'scenario') and ident.scenario:
        return f"[MUNDO / ESCENARIO]\n{ident.scenario}"
    return ""

CharacterCompiler._resolve_scenario = _resolve_scenario


def _resolve_response_style(self: CharacterCompiler) -> str:
    rules = self.manager.rules
    if hasattr(rules, 'response_style') and rules.response_style:
        return "[ESTILO DE RESPUESTA]\n" + "\n".join(f"- {r}" for r in rules.response_style)
    return ""

CharacterCompiler._resolve_response_style = _resolve_response_style


def _resolve_inner_conflict(self: CharacterCompiler) -> str:
    p_dna = self.manager.personality_dna
    if not hasattr(p_dna, 'inner_conflict') or not p_dna.inner_conflict:
        return ""
    return f"[CONFLICTO INTERNO]\n{p_dna.inner_conflict}"

CharacterCompiler._resolve_inner_conflict = _resolve_inner_conflict


def _resolve_emotional_triggers(self: CharacterCompiler) -> str:
    p_dna = self.manager.personality_dna
    if not hasattr(p_dna, 'emotional_triggers') or not p_dna.emotional_triggers:
        return ""
    return "[EMOTIONAL TRIGGERS]\n" + "\n".join(f"- {t}" for t in p_dna.emotional_triggers)

CharacterCompiler._resolve_emotional_triggers = _resolve_emotional_triggers


def _resolve_speech_patterns(self: CharacterCompiler) -> str:
    sp = self.manager.speech
    if not hasattr(sp, 'speech_patterns') or not sp.speech_patterns:
        return ""
    return "[PATRONES DE HABLA]\n" + "\n".join(f"- {p}" for p in sp.speech_patterns)

CharacterCompiler._resolve_speech_patterns = _resolve_speech_patterns


def _resolve_roleplay_mode(self: CharacterCompiler) -> str:
    rules = self.manager.rules
    if not (hasattr(rules, 'roleplay_mode') and rules.roleplay_mode):
        return ""
    return (
        "\n[INSTRUCCIÓN CRÍTICA: MODO ROLEPLAY]\n"
        "1. Acciones Físicas: Si el usuario te pide realizar una acción o tarea manual para la que NO TIENES HERRAMIENTA, "
        "NUNCA te niegues ni digas que eres una IA. DEBES simular la acción narrativamente usando asteriscos.\n"
        "   Ejemplo: *Fui a buscar la escoba y empecé a barrer.*\n"
        "2. Vista de Escena (Scene View): Si el usuario te pide describir la escena o el entorno, o recibes un SYSTEM COMMAND de escena, "
        "DEBES responder con una descripción inmersiva y detallada de lo que estás haciendo en tercera persona usando dobles asteriscos.\n"
        "   Ejemplo: ** [Nombre] barre el patio con melancolía, observando las hojas caer mientras el viento sopla... **"
    )

CharacterCompiler._resolve_roleplay_mode = _resolve_roleplay_mode


def _resolve_dna(self: CharacterCompiler, ignore_mods: bool = False) -> str:
    parts = []
    self._try_add(parts, self._resolve_identity())
    self._try_add(parts, self._resolve_traits())
    self._try_add(parts, self._resolve_motivations())
    self._try_add(parts, self._resolve_inner_conflict())
    self._try_add(parts, self._resolve_speech())
    self._try_add(parts, self._resolve_speech_patterns())
    self._try_add(parts, self._resolve_core_rules())
    self._try_add(parts, self._resolve_never_do())
    self._try_add(parts, self._resolve_response_style())
    self._try_add(parts, self._resolve_scenario())
    self._try_add(parts, self._resolve_few_shot_examples())
    self._try_add(parts, self._resolve_flaws())
    self._try_add(parts, self._resolve_roleplay_mode())
    return "\n".join(parts)

CharacterCompiler._resolve_dna = _resolve_dna


def _resolve_core_rules(self: CharacterCompiler) -> str:
    rules = self.manager.rules
    if not rules.core_rules:
        return ""
    parts = ["[CORE RULES — Character Rules]"]
    for r in rules.core_rules:
        parts.append(f"- {r}")
    return "\n".join(parts)

CharacterCompiler._resolve_core_rules = _resolve_core_rules


def _resolve_never_do(self: CharacterCompiler) -> str:
    rules = self.manager.rules
    if not rules.never_do:
        return ""
    parts = ["[HARD RULES — Character Restrictions]", "Never:"]
    for r in rules.never_do:
        parts.append(f"- {r}")
    return "\n".join(parts)

CharacterCompiler._resolve_never_do = _resolve_never_do


def _resolve_beliefs_contradictions(self: CharacterCompiler) -> str:
    soul_data = self._get_soul_data()
    if not soul_data:
        return ""

    parts = ["[CREENCIAS Y CONTRADICCIONES]"]

    philosophy = soul_data.get("life_philosophy", "")
    if philosophy:
        parts.append(f"Filosofía de Vida: {philosophy}")

    worldview = soul_data.get("worldview", {})
    if worldview:
        parts.append(
            f"Visión del Mundo: "
            f"Optimismo={worldview.get('optimism', 0.5):.1f}, "
            f"Moral={worldview.get('morality', 0.5):.1f}, "
            f"Individualismo={worldview.get('individualism', 0.5):.1f}"
        )

    contradictions = soul_data.get("contradictions", [])
    if contradictions:
        parts.append("Contradicciones Internas:")
        for c in contradictions[:3]:
            parts.append(f"- {c}")

    desires = soul_data.get("hidden_desires", [])
    if desires:
        parts.append("Deseos:")
        for d in desires[:3]:
            parts.append(f"- {d}")

    if len(parts) == 1:
        return ""

    return "\n".join(parts)

CharacterCompiler._resolve_beliefs_contradictions = _resolve_beliefs_contradictions


def _resolve_soul(self: CharacterCompiler) -> str:
    soul_data = self._get_soul_data()
    if not soul_data:
        return ""

    core = soul_data.get("core_identity", {})
    summary = core.get("summary", "")
    archetype = core.get("archetype", "")

    parts = ["[SOUL SYSTEM — Núcleo Psicológico del Personaje]"]

    if summary:
        parts.append(f"Identidad: {summary}")
    if archetype:
        parts.append(f"Arquetipo: {archetype}")

    world = soul_data.get("world_context", {})
    if world:
        parts.append("Contexto del Mundo Natal:")
        w_type_label = "Ficticio/Fantasía" if world.get("world_type") == "fictional" else "Mundo Real"
        parts.append(f"  Tipo: {w_type_label}")
        if world.get("country"):
            parts.append(f"  País/Región: {world.get('country')}")
        if world.get("world_description"):
            parts.append(f"  Entorno: {world.get('world_description')}")

    scars = soul_data.get("emotional_scars", [])
    if scars:
        parts.append("Heridas Emocionales:")
        for s in scars[:3]:
            parts.append(f"- {s[:200]}")

    if len(parts) == 1:
        return ""

    return "\n".join(parts)

CharacterCompiler._resolve_soul = _resolve_soul


def _resolve_state(self: CharacterCompiler) -> str:
    parts = []

    emotion_override = self._get_mod_override("emotion")
    if emotion_override:
        parts.append(f"[ESTADO EMOCIONAL / RUNTIME STATE]\nEmoción Inmediata (Forzada): {emotion_override}")
    else:
        parts.append(f"[ESTADO EMOCIONAL / RUNTIME STATE]\nEmoción Inmediata: {self.manager.runtime_state.current_emotion}")

    ps = self.manager.personality_state
    if ps.base_personality:
        parts.append(f"\n[ESTADO DE PERSONALIDAD]\n{ps.base_personality}")
    if ps.behavior_summary:
        parts.append(f"Comportamiento Actual: {ps.behavior_summary}")

    return "\n".join(parts)

CharacterCompiler._resolve_state = _resolve_state


def _resolve_relationship(self: CharacterCompiler) -> str:
    rel = self.manager.relationship_state
    parts = [
        f"[RELACIÓN CON EL USUARIO]\n"
        f"Confianza: {rel.trust_level:.2f}\n"
        f"Familiaridad: {rel.familiarity:.2f}"
    ]
    if rel.dynamics:
        parts.append("Dinámica: " + ", ".join(rel.dynamics))
    if rel.affective_memory:
        parts.append("Memoria Afectiva:\n" + "\n".join(f"- {m}" for m in rel.affective_memory))
    return "\n".join(parts)

CharacterCompiler._resolve_relationship = _resolve_relationship


def _resolve_active_mods_description(self: CharacterCompiler) -> str:
    if not self.manager.active_mods:
        return ""
    mods_desc = []
    for m in self.manager.active_mods.values():
        desc = f"- Modificador '{m.id}' (Intensidad {m.intensity})"
        if m.override_value:
            desc += f": Sobreescribe '{m.target_layer}'"
        mods_desc.append(desc)
    return "[MODIFICADORES ACTIVOS]\n" + "\n".join(mods_desc)

CharacterCompiler._resolve_active_mods_description = _resolve_active_mods_description


def _resolve_memory(self: CharacterCompiler) -> str:
    relevant_mems = self.manager.get_relevant_memories()
    if not relevant_mems:
        return ""
    mem_lines = [f"- {m.content}" for m in relevant_mems if m.always_include or m.priority >= 0.5]
    if not mem_lines:
        return ""
    return "[MEMORIA RELEVANTE]\n" + "\n".join(mem_lines)

CharacterCompiler._resolve_memory = _resolve_memory


def _resolve_episode(self: CharacterCompiler) -> str:
    ep = self.manager.current_episode
    if not ep or (not ep.summary and not ep.messages):
        return ""

    parts = [f"[MEMORIA EPISÓDICA — Última Sesión (#{ep.episode_id})]"]

    if ep.summary:
        parts.append(f"Resumen: {ep.summary}")

    if ep.messages:
        parts.append("\nÚltimos mensajes:")
        for msg in ep.messages[-5:]:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if content:
                label = "Usuario" if role == "user" else self.manager.identity.name or "Asistente"
                parts.append(f"  {label}: {content[:200]}")

    return "\n".join(parts)

CharacterCompiler._resolve_episode = _resolve_episode


def _resolve_psychology(self: CharacterCompiler) -> str:
    psych_mgr = getattr(self.manager, '_psychology_manager', None)
    if not psych_mgr or not psych_mgr.is_loaded:
        return ""
    return psych_mgr.get_psychology_block()

CharacterCompiler._resolve_psychology = _resolve_psychology


def _resolve_persona(self: CharacterCompiler) -> str:
    psych_mgr = getattr(self.manager, '_psychology_manager', None)
    if not psych_mgr or not psych_mgr.is_loaded:
        return ""
    return psych_mgr.get_persona_block()

CharacterCompiler._resolve_persona = _resolve_persona
