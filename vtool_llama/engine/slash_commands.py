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
    self._slash_commands.register(
        "history", self._cmd_history,
        "Muestra los últimos mensajes del chat. Uso: /history [N=10]",
    )
    self._slash_commands.register(
        "autosave", self._cmd_autosave,
        "Activa auto-guardado cada N mensajes. Uso: /autosave <N> (0 = desactivar)",
    )
    self._slash_commands.register(
        "semantic", self._cmd_semantic,
        "Indexa la conversación en ChromaDB. Uso: /semantic [rebuild]",
    )
    self._slash_commands.register(
        "clean", self._cmd_clean,
        "Limpia todo el historial de chat de la sesión actual.",
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
            self.load_episode(ep_id)
            return f"✓ Episodio #{ep_id} restaurado (checkout no destructivo)."
        except (ValueError, Exception) as e:
            return f"Error: {e}"

    if len(parts) == 2 and parts[0] == "delete":
        try:
            ep_id = int(parts[1])
            ok = self.delete_episode(ep_id)
            return f"✓ Episodio #{ep_id} eliminado." if ok else f"Episodio #{ep_id} no encontrado."
        except (ValueError, Exception) as e:
            return f"Error: {e}"

    episodes = self.list_episodes()
    if not episodes:
        return "No hay episodios guardados."
    lines = ["📋 Episodios guardados:"]
    for ep in episodes:
        ts = ep.get('timestamp', '')
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(ts)
            fecha = dt.strftime("%d/%m/%y %H:%M")
        except Exception:
            fecha = ts[:16] if ts else "?"

        topic = f" [{ep.get('topic', '')}]" if ep.get('topic') else ""
        msgs = ep.get('message_count', 0)
        summary = ep['summary'] + "…" if len(ep['summary']) >= 80 else ep['summary']
        lines.append(f"  #{ep['episode_id']:03d}  {fecha}{topic}  ({msgs} msgs)")
        lines.append(f"      {summary}")
    lines.append("")
    lines.append("  /episodes load N   — Volver al episodio N")
    lines.append("  /episodes delete N — Eliminar episodio N")
    return "\n".join(lines)

VToolLlama._cmd_episodes = _cmd_episodes


def _cmd_history(self: VToolLlama, args: str) -> str:
    try:
        n = max(1, min(50, int(args.strip()))) if args.strip() else 10
    except ValueError:
        n = 10

    history = self.get_chat_history(limit=n)
    if not history:
        return "No hay historial de chat."

    lines = [f"📜 Últimos {len(history)} mensajes:"]
    for msg in history:
        role = "👤" if msg["role"] == "user" else "🤖" if msg["role"] == "assistant" else "🔧"
        content = msg["content"][:120] + "…" if len(msg["content"]) > 120 else msg["content"]
        lines.append(f"  {role} {content}")
    return "\n".join(lines)

VToolLlama._cmd_history = _cmd_history


def _cmd_autosave(self: VToolLlama, args: str) -> str:
    try:
        n = int(args.strip())
    except (ValueError, AttributeError):
        return "Uso: /autosave <N> (cada N mensajes, 0 = desactivar)"

    self.active_auto_save_at(n)
    return f"✓ Auto-save {'activado' if n > 0 else 'desactivado'} cada {n} mensajes." if n > 0 else "✓ Auto-save desactivado."

VToolLlama._cmd_autosave = _cmd_autosave


def _cmd_semantic(self: VToolLlama, args: str) -> str:
    if not self._semantic_chroma:
        return "ChromaDB no configurado. Usá semantic_memory=True al cargar el personaje."

    rebuild = args.strip().lower() == "rebuild"
    try:
        count = self.index_conversation(incremental=not rebuild)
        return f"✓ Indexados {count} chunks semánticos{' (rebuild completo)' if rebuild else ''}."
    except Exception as e:
        return f"Error indexando: {e}"

VToolLlama._cmd_semantic = _cmd_semantic


def _cmd_clean(self: VToolLlama, args: str) -> str:
    # 1) Limpiar RAM
    self._memory.clear()

    # 2) Limpiar SQLite (soft-delete todos los mensajes activos)
    if self._chat_store and self._memory._conversation_id:
        msgs = self._chat_store.get_branch_messages(
            self._memory._conversation_id, self._memory._branch_id, limit=5000
        )
        for m in msgs:
            if m.status == "active":
                self._chat_store.soft_delete_message(m.id)
        self._chat_store.mark_semantic_dirty(self._memory._conversation_id)

    # 3) Limpiar ChromaDB semántico
    if self._semantic_chroma and self._semantic_chroma.is_available:
        self._semantic_chroma.clear()

    # 4) Limpiar memorias persistentes (long_term.json)
    if self._character_manager:
        self._character_manager.memories.clear()
        self._character_manager._needs_rebuild = True
        self._character_manager.save_state()

    # 5) Resetear active_leaf
    if self._memory._conversation_id and self._chat_store:
        self._chat_store.set_active_leaf(
            self._memory._conversation_id, self._memory._branch_id, 0
        )
    self._memory._active_leaf_id = 0

    self._log_info("Memoria limpiada completamente (RAM + SQLite + ChromaDB + long_term).")
    return "🧹 Memoria limpiada completamente."

VToolLlama._cmd_clean = _cmd_clean
