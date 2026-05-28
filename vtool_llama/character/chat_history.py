"""chat_history.py — Historial de chat en ChromaDB."""

from __future__ import annotations

from .base import CharacterManager


def _init_chat_chroma(self: CharacterManager) -> None:
    if not self._char_dir:
        return
    from ..db.chroma_store import ChromaStore, HAS_CHROMA
    if not HAS_CHROMA:
        self._log("CHAR", "ChromaDB no disponible para memoria de chat.")
        return
    self._chat_chroma = ChromaStore(
        db_path=self._char_dir / "memory" / "chat_history",
        collection_name="chat_history",
        log_fn=lambda m: self._log("CHAR", m),
    )
    if self._chat_chroma.initialize():
        self._log("CHAR", "Chat Memory ChromaDB inicializado.")
    else:
        self._chat_chroma = None

CharacterManager._init_chat_chroma = _init_chat_chroma


def save_chat_turn(self: CharacterManager, user_prompt: str, assistant_response: str) -> None:
    if not self._chat_chroma or not self._chat_chroma.is_available:
        return

    turn_text = f"Usuario: {user_prompt}\nPersonaje: {assistant_response}"
    import uuid
    from datetime import datetime
    doc_id = uuid.uuid4().hex[:12]
    metadata = {
        "timestamp": datetime.now().isoformat(),
        "type": "chat_turn",
    }
    self._chat_chroma.add_document(doc_id, turn_text, metadata)

CharacterManager.save_chat_turn = save_chat_turn


def retrieve_relevant_chat(self: CharacterManager, query: str, top_k: int = 3) -> list[dict]:
    if not self._chat_chroma or not self._chat_chroma.is_available:
        return []
    return self._chat_chroma.search(query, top_k=top_k)

CharacterManager.retrieve_relevant_chat = retrieve_relevant_chat
