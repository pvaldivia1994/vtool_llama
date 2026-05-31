"""
ContextInjector — Gestión de entradas de contexto inyectables.

Cada entrada se guarda en la tabla `summaries` con reason='ctx_{tipo}'.
El ContextBuilder las recolecta y las inyecta como system messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import ChatStore

CONTEXT_TYPES = {
    "scene": "[CONTEXT][SCENE]",
    "character": "[CONTEXT][CHARACTER]",
    "thoughts": "[CONTEXT][THOUGHTS]",
    "goals": "[CONTEXT][GOALS]",
    "player": "[CONTEXT][PLAYER]",
    "time": "[CONTEXT][TIME]",
    "world": "[CONTEXT][WORLD]",
    "memory": "[CONTEXT][MEMORY]",
    "custom": "[CONTEXT][CUSTOM]",
}

CONTEXT_DEFINITIONS = {
    "scene": "[CONTEXT][SCENE] Current scene, location, present characters, and active events.",
    "character": "[CONTEXT][CHARACTER] Current emotional, mental, and physical state of the character.",
    "thoughts": "[CONTEXT][THOUGHTS] Private thoughts, intentions, motivations, and internal feelings.",
    "goals": "[CONTEXT][GOALS] Active objectives, missions, and desired outcomes.",
    "player": "[CONTEXT][PLAYER] Current action or behavior of the player. The character should react to this.",
    "time": "[CONTEXT][TIME] Time, date, weather, season, and passage of time.",
    "world": "[CONTEXT][WORLD] Relevant world events, politics, conflicts, and environmental changes.",
    "memory": "[CONTEXT][MEMORY] Important long-term facts, relationships, and past events that remain relevant.",
    "custom": "[CONTEXT][CUSTOM] Additional user-defined contextual information.",
}

CONTEXT_HEADER = (
    "[CONTEXT]\n\n"
    "Dynamic contextual information describing the current state of the story, character, "
    "world, and ongoing events. Context tags provide factual information and should be used "
    "to maintain consistency. When context conflicts, prioritize the most recent and "
    "currently active information."
)


@dataclass
class ContextEntry:
    id: int = 0
    ctx_type: str = "custom"
    content: str = ""
    tag: str = "[CUSTOM]"
    order: int = 0
    created_at: str = ""


class ContextInjector:
    """Maneja el CRUD de entradas de contexto en SQLite."""

    def __init__(self, store: ChatStore, conversation_id: str, branch_id: str = "main"):
        self._store = store
        self._conversation_id = conversation_id
        self._branch_id = branch_id

    @staticmethod
    def reason_for_type(ctx_type: str) -> str:
        return f"ctx_{ctx_type}"

    @staticmethod
    def tag_for_type(ctx_type: str) -> str:
        return CONTEXT_TYPES.get(ctx_type, "[CUSTOM]")

    def _next_order(self) -> int:
        """Calcula el próximo número de orden."""
        max_order = 0
        summaries = self._store.get_summaries(self._conversation_id, self._branch_id, limit=500)
        for s in summaries:
            if s.reason.startswith("ctx_") and s.start_message_id > max_order:
                max_order = s.start_message_id
        return max_order + 1

    def _new_id(self) -> int:
        max_id = 0
        for s in self._store.get_summaries(self._conversation_id, self._branch_id, limit=500):
            if s.reason.startswith("ctx_") and s.id > max_id:
                max_id = s.id
        return max_id + 1

    def add(self, ctx_type: str, content: str, order: int | None = None) -> int:
        """Agrega una entrada de contexto ACTIVA (no entregada)."""
        reason = self.reason_for_type(ctx_type)
        tag = self.tag_for_type(ctx_type)
        summary = f"{tag} {content}"
        ord_val = order if order is not None else self._next_order()
        return self._store.add_summary(
            conversation_id=self._conversation_id,
            branch_id=self._branch_id,
            start_message_id=ord_val,
            end_message_id=0,  # 0 = activa (no entregada)
            summary=summary,
            reason=reason,
        )

    def list(self, only_active: bool = True) -> list[ContextEntry]:
        """Lista entradas de contexto. Si only_active, solo las no entregadas."""
        entries: list[ContextEntry] = []
        for ctx_type in CONTEXT_TYPES:
            reason = self.reason_for_type(ctx_type)
            summaries = self._store.get_summaries(
                self._conversation_id, self._branch_id, limit=200
            )
            for s in summaries:
                if s.reason == reason:
                    if only_active and s.end_message_id != 0:
                        continue
                    tag = self.tag_for_type(ctx_type)
                    content = s.summary
                    if content.startswith(tag):
                        content = content[len(tag):].strip()
                    entries.append(ContextEntry(
                        id=s.id,
                        ctx_type=ctx_type,
                        content=content,
                        tag=tag,
                        order=s.start_message_id,
                        created_at=s.created_at,
                    ))
        entries.sort(key=lambda e: e.order)
        return entries

    def remove(self, entry_id: int) -> bool:
        return self._store.delete_summary(entry_id)

    def clear(self) -> int:
        removed = 0
        for entry in self.list(only_active=False):
            if self._store.delete_summary(entry.id):
                removed += 1
        return removed

    def mark_delivered(self, entry_ids: list[int]) -> None:
        """Marca entradas como entregadas y las inserta como mensajes
        en el historial de chat (role='context') para mantener
        la secuencia cronológica."""
        for eid in entry_ids:
            delivered_id = 0
            # Obtener la entrada antes de marcarla
            for s in self._store.get_summaries(self._conversation_id, self._branch_id, limit=500):
                if s.id == eid:
                    delivered_id = self._store.add_message(
                        conversation_id=self._conversation_id,
                        branch_id=self._branch_id,
                        role="context",
                        content=s.summary,
                        parent_id=None,
                        token_count=0,
                    )
                    break
            if delivered_id:
                self._store.mark_summary_delivered(eid, delivered_id)

    def get_active_contexts(self, include_scene: bool = True) -> list[str]:
        """Solo entradas ACTIVAS (no entregadas)."""
        lines: list[str] = []
        for entry in self.list(only_active=True):
            if not include_scene and entry.ctx_type == "scene":
                continue
            line = f"{entry.tag} {entry.content}"
            if line not in lines:
                lines.append(line)
        return lines

    def get_history_contexts(self) -> list[str]:
        """Entradas ya entregadas (históricas, para contexto de conversación)."""
        lines: list[str] = []
        for entry in self.list(only_active=False):
            if entry.ctx_type == "scene":
                continue
            if entry.order > 0 and entry.id > 0:
                continue
            line = f"{entry.tag} {entry.content}"
            if line not in lines:
                lines.append(line)
        return lines

    # ── Escena ──────────────────────────────────────────────────────

    def save_scene(self, scene_text: str) -> int | None:
        if not self._conversation_id:
            return None
        for s in self._store.get_summaries(self._conversation_id, self._branch_id, limit=10):
            if s.reason == "ctx_scene":
                self._store.delete_summary(s.id)
        return self.add("scene", scene_text, order=self._next_order())

    def get_scene(self) -> str | None:
        lines = [e for e in self.get_active_contexts() if e.startswith("[CONTEXT][SCENE]")]
        return lines[0] if lines else None
