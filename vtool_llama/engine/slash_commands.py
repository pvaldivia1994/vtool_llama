"""slash_commands.py — VToolLlama slash command handlers."""

from __future__ import annotations

import json
from typing import Optional

from .base import VToolLlama


def _handle_slash_command(self: VToolLlama, text: str) -> Optional[str]:
    if not text or not text.startswith("/"):
        return None

    if self._slash_commands.is_slash_command(text):
        self._log_debug("SLASH", f"Ejecutando comando: {text}")
        result = self._slash_commands.handle(text)
        return result

    return None

VToolLlama._handle_slash_command = _handle_slash_command


def _register_default_slash_commands(self: VToolLlama) -> None:
    self._slash_commands.register(
        "mem", self._cmd_mem,
        "Agrega una memoria persistente. Uso: /mem <texto>",
    )
    self._slash_commands.register(
        "rebuild", self._cmd_rebuild,
        "Reconstruye el estado de personalidad del agente.",
    )
    self._slash_commands.register(
        "state", self._cmd_state,
        "Muestra el estado actual del agente.",
    )
    self._slash_commands.register(
        "memories", self._cmd_memories,
        "Lista todas las memorias persistentes.",
    )
    self._slash_commands.register(
        "mood", self._cmd_mood,
        "Cambia un valor de mood. Uso: /mood <key> <value>",
    )
    self._slash_commands.register(
        "rel", self._cmd_rel,
        "Modifica o consulta el relationship state. Uso: /rel <trust> <familiarity>",
    )
    self._slash_commands.register(
        "help", self._cmd_help,
        "Muestra la lista de comandos disponibles.",
    )
    self._slash_commands.register(
        "scene_view", lambda _: "Comando procesado por el motor interno.",
        "Obliga al personaje a describir la escena actual, el entorno y sus acciones en detalle inmersivo.",
    )
    self._slash_commands.register(
        "save_episode", self._cmd_save_episode,
        "Guarda un snapshot de la conversación actual como episodio versionado.",
    )
    self._slash_commands.register(
        "episodes", self._cmd_episodes,
        "Lista todos los episodios guardados. Uso: /episodes [load N | delete N]",
    )

VToolLlama._register_default_slash_commands = _register_default_slash_commands


def _cmd_mem(self: VToolLlama, args: str) -> str:
    if not args.strip():
        return "Uso: /mem <texto a recordar>"
    entry = self._character_manager.add_memory(
        content=args.strip(),
        always_include=True,
        priority=1.0,
    )
    return f"✓ Memoria guardada (id: {entry.id}): {entry.content}"

VToolLlama._cmd_mem = _cmd_mem


def _cmd_rebuild(self: VToolLlama, args: str) -> str:
    self.rebuild_personality_state()
    return "✓ Estado de personalidad reconstruido."

VToolLlama._cmd_rebuild = _cmd_rebuild


def _cmd_state(self: VToolLlama, args: str) -> str:
    state = self.get_state_info()
    return json.dumps(state, ensure_ascii=False, indent=2)

VToolLlama._cmd_state = _cmd_state


def _cmd_memories(self: VToolLlama, args: str) -> str:
    memories = self._character_manager.memories
    if not memories:
        return "No hay memorias guardadas."
    lines = []
    for m in memories:
        tags = f" [{', '.join(m.tags)}]" if m.tags else ""
        pin = " 📌" if m.always_include else ""
        lines.append(f"  [{m.id}] {m.content}{tags}{pin}")
    return "Memorias:\n" + "\n".join(lines)

VToolLlama._cmd_memories = _cmd_memories


def _cmd_mood(self: VToolLlama, args: str) -> str:
    if not args:
        return "Uso: /mood <layer> <value> [intensity] (ej: /mood speech silencioso 1.0)"
    parts = args.split()
    if len(parts) < 2:
        return "Error: Formato incorrecto. Uso: /mood <layer> <value>"

    layer = parts[0]
    value = " ".join(parts[1:])
    intensity = 1.0
    if len(parts) >= 3:
        try:
            intensity = float(parts[-1])
            value = " ".join(parts[1:-1])
        except ValueError:
            pass

    from ..types import CharacterMod
    mod = CharacterMod(id=f"temp_{layer}", target_layer=layer, override_value=value, intensity=intensity)
    self._character_manager.set_mod(mod)
    self._inject_personality_into_system_prompt()
    return f"✓ Mod aplicado a '{layer}': {value} (Intensidad {intensity:.1f})"

VToolLlama._cmd_mood = _cmd_mood


def _cmd_rel(self: VToolLlama, args: str) -> str:
    if not args:
        rel = self._character_manager.relationship_state
        return f"Estado de relación actual:\nConfianza: {rel.trust_level:.2f}\nFamiliaridad: {rel.familiarity:.2f}"

    parts = args.split()
    if len(parts) == 2:
        try:
            trust = float(parts[0])
            fam = float(parts[1])
            self._character_manager.relationship_state.trust_level = trust
            self._character_manager.relationship_state.familiarity = fam
            self._character_manager.save_state()
            return f"✓ Relación actualizada: Trust={trust:.2f}, Familiarity={fam:.2f}"
        except ValueError:
            pass
    return "Uso: /rel <trust> <familiarity> (ej: /rel 0.8 0.5)"

VToolLlama._cmd_rel = _cmd_rel


def _cmd_help(self: VToolLlama, args: str) -> str:
    return self._slash_commands.get_help_text()

VToolLlama._cmd_help = _cmd_help


def _cmd_save_episode(self: VToolLlama, args: str) -> str:
    try:
        episode = self.save_episode()
        return f"✓ Episodio #{episode.episode_id} guardado. Resumen: {episode.summary[:100]}..."
    except Exception as e:
        return f"Error al guardar episodio: {e}"

VToolLlama._cmd_save_episode = _cmd_save_episode


def _cmd_episodes(self: VToolLlama, args: str) -> str:
    parts = args.strip().split() if args else []

    if len(parts) == 2 and parts[0] == "load":
        try:
            ep_id = int(parts[1])
            self._character_manager.load_episode(ep_id)
            self._inject_personality_into_system_prompt()
            return f"✓ Episodio #{ep_id} restaurado (rollback)."
        except (ValueError, Exception) as e:
            return f"Error: {e}"

    if len(parts) == 2 and parts[0] == "delete":
        try:
            ep_id = int(parts[1])
            ok = self._character_manager.delete_episode(ep_id)
            return f"✓ Episodio #{ep_id} eliminado." if ok else f"Episodio #{ep_id} no encontrado."
        except (ValueError, Exception) as e:
            return f"Error: {e}"

    episodes = self._character_manager.list_episodes()
    if not episodes:
        return "No hay episodios guardados."
    lines = ["Episodios guardados:"]
    for ep in episodes:
        current = " ← actual" if (self._character_manager.current_episode and ep["episode_id"] == self._character_manager.current_episode.episode_id) else ""
        lines.append(f"  #{ep['episode_id']:03d} [{ep['timestamp'][:16]}] ({ep['message_count']} msgs) {ep['summary']}{current}")
    lines.append("\nUso: /episodes load N | /episodes delete N")
    return "\n".join(lines)

VToolLlama._cmd_episodes = _cmd_episodes
