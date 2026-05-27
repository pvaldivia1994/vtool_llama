"""
Compilador de prompts del Character System para vtool_llama.

Ensambla el system prompt final combinando todas las capas del personaje
con un sistema de resolución de conflictos por prioridad: MODS > STATE > DNA.

Pipeline de compilación:
1. Base prompt (config.system_prompt)
2. DNA: identity, personality, speech, rules (con overrides de Mods)
3. State: runtime_state, personality_state (con overrides de Mods)
4. Relationship: trust_level, familiarity, affective_memory
5. Mods activos (descripción explícita)
6. Memory: long_term memorias relevantes
7. Episodic Memory: resumen de la última sesión

Regla de oro: Los Mods activos pueden sobreescribir cualquier capa del DNA
o State en tiempo real sin modificar los archivos originales.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .character_manager import CharacterManager
    from .types import MemoryEntry


class CharacterCompiler:
    """
    Ensambla el prompt del personaje resolviendo conflictos
    con el sistema de prioridad: MODS > STATE > DNA.

    El compilador recorre el pipeline de capas en orden de prioridad
    ascendente: primero el DNA base, luego el State dinámico, luego
    los Mods temporales que pueden sobreescribir cualquier capa anterior.
    """

    def __init__(self, manager: CharacterManager):
        self.manager = manager

    def compile_prompt(self, base_system_prompt: str) -> str:
        """
        Ejecuta el pipeline completo de compilación.

        Construye el system prompt combinando todas las capas del
        personaje en orden de prioridad ascendente.

        Args:
            base_system_prompt: prompt base del config.json

        Returns:
            system prompt completo con todas las capas del personaje
        """
        if not self.manager.is_loaded:
            return base_system_prompt

        parts = [base_system_prompt]

        # 1. DNA — capa base inmutable del personaje
        dna_block = self._resolve_dna(ignore_mods=False)
        if dna_block:
            parts.append(dna_block)

        # 2. State — estado dinámico en tiempo de ejecución
        state_block = self._resolve_state()
        if state_block:
            parts.append(state_block)

        # 3. Relationship — relación afectiva con el usuario
        rel_block = self._resolve_relationship()
        if rel_block:
            parts.append(rel_block)

        # 4. Mods activos — modificadores temporales explícitos
        mods_block = self._resolve_active_mods_description()
        if mods_block:
            parts.append(mods_block)

        # 5. Memory — memorias persistentes de largo plazo
        mem_block = self._resolve_memory()
        if mem_block:
            parts.append(mem_block)

        # 6. Episodic Memory — contexto de la sesión anterior
        ep_block = self._resolve_episode()
        if ep_block:
            parts.append(ep_block)

        return "\n".join(parts)

    def compile_base_prompt(self, base_system_prompt: str) -> str:
        """
        Ensambla solo la parte inmutable del prompt (DNA puro).
        No incluye estado, memoria, ni mods.

        Se usa para generar el KV Cache Base, que representa los
        tensores pre-evaluados de la personalidad sin contexto dinámico.

        Args:
            base_system_prompt: prompt base del config.json

        Returns:
            prompt solo con DNA, sin estado ni memoria
        """
        if not self.manager.is_loaded:
            return base_system_prompt

        parts = [base_system_prompt]

        # Resolve DNA puro ignorando Mods (para el cache base)
        dna_block = self._resolve_dna(ignore_mods=True)
        if dna_block:
            parts.append(dna_block)

        return "\n".join(parts)

    def _get_mod_override(self, target_layer: str) -> str | None:
        """
        Busca si hay un Mod activo que sobreescriba una capa específica.

        Si hay múltiples mods apuntando a la misma capa, se toma el
        de mayor intensidad (resolución por prioridad).

        Args:
            target_layer: nombre de la capa a buscar (traits, speech, emotion)

        Returns:
            valor de override si existe, None si no hay mods activos
        """
        overrides = []
        for mod in self.manager.active_mods.values():
            if mod.target_layer == target_layer and mod.override_value:
                overrides.append(mod)
        if overrides:
            # Resolver por intensidad: el mod más intenso gana
            overrides.sort(key=lambda m: m.intensity, reverse=True)
            return overrides[0].override_value
        return None

    def _resolve_dna(self, ignore_mods: bool = False) -> str:
        """
        Compila la capa de DNA: identidad, personalidad, reglas y habla.

        Si ignore_mods=True, salta los overrides de mods (usado para
        generar el KV Cache Base).

        Args:
            ignore_mods: si es True, ignora los mods activos

        Returns:
            bloque de texto con el DNA compilado
        """
        parts = []

        # --- Identidad ---
        ident = self.manager.identity
        parts.append(f"[IDENTIDAD]\nNombre: {ident.name}\nRol: {ident.role}\nFondo: {ident.background}")
        if hasattr(ident, 'scenario') and ident.scenario:
            parts.append(f"\n[MUNDO / ESCENARIO]\n{ident.scenario}")

        # --- Personalidad (traits, motivations, flaws) ---
        # Los mods pueden sobreescribir traits
        traits_override = self._get_mod_override("traits") if not ignore_mods else None
        if traits_override:
            parts.append(f"\n[RASGOS (MODIFICADO)]\n{traits_override}")
        else:
            p_dna = self.manager.personality_dna
            if p_dna.traits:
                parts.append(f"\n[RASGOS]\n" + "\n".join(f"- {t}" for t in p_dna.traits))
            if hasattr(p_dna, 'motivations') and p_dna.motivations:
                parts.append(f"\n[MOTIVACIONES]\n" + "\n".join(f"- {m}" for m in p_dna.motivations))
            if hasattr(p_dna, 'flaws') and p_dna.flaws:
                parts.append(f"\n[DEFECTOS]\n" + "\n".join(f"- {f}" for f in p_dna.flaws))

        # --- Reglas ---
        rules = self.manager.rules
        if rules.core_rules:
            parts.append(f"\n[REGLAS CORE]\n" + "\n".join(f"- {r}" for r in rules.core_rules))
        if rules.never_do:
            parts.append(f"\n[NUNCA DEBES]\n" + "\n".join(f"- {r}" for r in rules.never_do))
        if hasattr(rules, 'response_style') and rules.response_style:
            parts.append(f"\n[ESTILO DE RESPUESTA]\n" + "\n".join(f"- {r}" for r in rules.response_style))

        # Rolpeplay mode — instrucción crítica para simular acciones físicas
        if hasattr(rules, 'roleplay_mode') and rules.roleplay_mode:
            parts.append(
                "\n[INSTRUCCIÓN CRÍTICA: MODO ROLEPLAY]\n"
                "1. Acciones Físicas: Si el usuario te pide realizar una acción o tarea manual para la que NO TIENES HERRAMIENTA, "
                "NUNCA te niegues ni digas que eres una IA. DEBES simular la acción narrativamente usando asteriscos.\n"
                "   Ejemplo: *Fui a buscar la escoba y empecé a barrer.*\n"
                "2. Vista de Escena (Scene View): Si el usuario te pide describir la escena o el entorno, o recibes un SYSTEM COMMAND de escena, "
                "DEBES responder con una descripción inmersiva y detallada de lo que estás haciendo en tercera persona usando dobles asteriscos.\n"
                "   Ejemplo: ** [Nombre] barre el patio con melancolía, observando las hojas caer mientras el viento sopla... **"
            )

        # --- Estilo de habla (speech) ---
        # Los mods pueden sobreescribir el speech
        speech_override = self._get_mod_override("speech") if not ignore_mods else None
        if speech_override:
            parts.append(f"\n[ESTILO DE HABLA (MODIFICADO)]\n{speech_override}")
        else:
            sp = self.manager.speech
            parts.append(f"\n[ESTILO DE HABLA]\nEstilo: {sp.style}\nTono: {sp.tone}\nVerbosidad: {sp.verbosity}")
            if hasattr(sp, 'emotions') and sp.emotions:
                parts.append(f"Emociones base: " + ", ".join(sp.emotions))
            if hasattr(sp, 'examples') and sp.examples:
                parts.append(f"\n[FEW SHOT EXAMPLES]\n" + "\n\n".join(sp.examples))

        return "\n".join(parts)

    def _resolve_state(self) -> str:
        """
        Compila la capa de State: runtime_state + personality_state.

        Incluye la emoción actual (posiblemente forzada por un Mod activo)
        y el resumen de personalidad compilado por rebuild_personality_state.

        Returns:
            bloque de texto con el estado actual
        """
        parts = []

        # Emoción actual (puede ser overrideada por un Mod)
        emotion_override = self._get_mod_override("emotion")
        if emotion_override:
            parts.append(f"[RUNTIME STATE]\nEmoción Inmediata (Forzada): {emotion_override}")
        else:
            parts.append(f"[RUNTIME STATE]\nEmoción Inmediata: {self.manager.runtime_state.current_emotion}")

        # Personalidad compilada (resultado de rebuild)
        ps = self.manager.personality_state
        if ps.base_personality:
            parts.append(f"\n[ESTADO DE PERSONALIDAD]\n{ps.base_personality}")
        if ps.behavior_summary:
            parts.append(f"Comportamiento Actual: {ps.behavior_summary}")

        return "\n".join(parts)

    def _resolve_relationship(self) -> str:
        """
        Compila la capa de relación con el usuario.

        Incluye trust_level, familiarity, dinámicas detectadas
        y memoria afectiva de interacciones pasadas.

        Returns:
            bloque de texto con el estado relacional
        """
        rel = self.manager.relationship_state
        parts = []
        parts.append(f"[RELACIÓN CON EL USUARIO]\nConfianza: {rel.trust_level:.2f}\nFamiliaridad: {rel.familiarity:.2f}")
        if rel.dynamics:
            parts.append("Dinámica: " + ", ".join(rel.dynamics))
        if rel.affective_memory:
            parts.append("Memoria Afectiva:\n" + "\n".join(f"- {m}" for m in rel.affective_memory))
        return "\n".join(parts)

    def _resolve_active_mods_description(self) -> str:
        """
        Compila una descripción de todos los Mods activos actualmente.

        Cada Mod se muestra con su ID, intensidad, y la capa que
        está sobreescribiendo.

        Returns:
            bloque de texto con los mods activos, o string vacío
        """
        if not self.manager.active_mods:
            return ""
        mods_desc = []
        for m in self.manager.active_mods.values():
            desc = f"- Modificador '{m.id}' (Intensidad {m.intensity})"
            if m.override_value:
                desc += f": Sobreescribe '{m.target_layer}'"
            mods_desc.append(desc)
        return "[MODIFICADORES ACTIVOS]\n" + "\n".join(mods_desc)

    def _resolve_memory(self) -> str:
        """
        Compila las memorias relevantes del personaje.

        Solo se incluyen memorias con priority >= 0.5 o que tengan
        always_include=True. Se ordenan por prioridad descendente.

        Returns:
            bloque de texto con las memorias, o string vacío
        """
        relevant_mems = self.manager.get_relevant_memories()
        if not relevant_mems:
            return ""
        mem_lines = [f"- {m.content}" for m in relevant_mems if m.always_include or m.priority >= 0.5]
        if not mem_lines:
            return ""
        return "[MEMORIA RELEVANTE]\n" + "\n".join(mem_lines)

    def _resolve_episode(self) -> str:
        """Inyecta el contexto del último episodio en el prompt."""
        ep = self.manager.current_episode
        if not ep or (not ep.summary and not ep.messages):
            return ""
        
        parts = [f"[MEMORIA EPISÓDICA — Última Sesión (#{ep.episode_id})]"]
        
        if ep.summary:
            parts.append(f"Resumen: {ep.summary}")
        
        if ep.messages:
            parts.append("\nÚltimos mensajes:")
            # Solo los últimos 5 para no saturar contexto
            for msg in ep.messages[-5:]:
                role = msg.get("role", "?")
                content = msg.get("content", "")
                if content:
                    label = "Usuario" if role == "user" else self.manager.identity.name or "Asistente"
                    parts.append(f"  {label}: {content[:200]}")
        
        return "\n".join(parts)
