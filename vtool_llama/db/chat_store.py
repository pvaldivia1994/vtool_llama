"""
ChatStore — SQLite event store para historial conversacional.

Reemplaza a ChromaDB como source of truth para mensajes.
Soporta branching, rollback no destructivo, summaries,
memorias semánticas y snapshots de debug.

WAL mode activado por defecto para concurrencia segura.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from ..types import Branch, ChatMessage, Conversation, ConversationSummary

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    character_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active_branch_id TEXT NOT NULL DEFAULT 'main',
    active_leaf_message_id INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    branch_id TEXT NOT NULL DEFAULT 'main',
    message_index INTEGER NOT NULL,
    parent_id INTEGER,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tool_calls TEXT,
    tool_call_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    token_count INTEGER DEFAULT 0,
    speaker_tag TEXT DEFAULT '',
    thinking TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS branches (
    id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    parent_branch_id TEXT,
    created_from_message_id INTEGER,
    label TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (id, conversation_id)
);

CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    start_message_id INTEGER NOT NULL,
    end_message_id INTEGER NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    semantic_topic TEXT DEFAULT '',
    reason TEXT NOT NULL DEFAULT 'interval',
    embedding_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT,
    response_json TEXT,
    status TEXT DEFAULT 'pending',
    latency_ms REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS semantic_sync (
    conversation_id TEXT NOT NULL,
    last_synced_message_id INTEGER DEFAULT 0,
    last_synced_branch_id TEXT DEFAULT 'main',
    sync_hash TEXT DEFAULT '',
    dirty INTEGER DEFAULT 1,
    last_sync_at TEXT,
    PRIMARY KEY (conversation_id)
);

CREATE TABLE IF NOT EXISTS context_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    built_prompt TEXT NOT NULL,
    token_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    conversation_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (conversation_id, key)
);
"""


class ChatStore:
    """SQLite event store for chat history with branching support."""

    def __init__(self, db_path: str, log_fn: Optional[callable] = None):
        self._path = str(Path(db_path).resolve())
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._log = log_fn or (lambda tag, msg: None)
        self.ensure_schema()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._conn is None:
                self._conn = sqlite3.connect(self._path, check_same_thread=False)
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")
            yield self._conn
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def ensure_schema(self) -> None:
        with self._tx() as conn:
            conn.executescript(_SCHEMA_SQL)
            # Migracion v13: agregar speaker_tag
            try:
                conn.execute("ALTER TABLE messages ADD COLUMN speaker_tag TEXT DEFAULT ''")
            except Exception:
                pass
            # Migracion v19: agregar thinking
            try:
                conn.execute("ALTER TABLE messages ADD COLUMN thinking TEXT DEFAULT ''")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def get_or_create_conversation(self, character_name: str) -> Conversation:
        self._log("SQLITE", f"get_or_create_conversation character={character_name}")
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE character_name = ? ORDER BY rowid DESC LIMIT 1",
                (character_name,),
            ).fetchone()
            if row is not None:
                return Conversation(**dict(row))

            return self.create_conversation(character_name)

    def create_conversation(self, character_name: str) -> Conversation:
        with self._tx() as conn:
            conv_id = uuid.uuid4().hex[:12]
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO conversations (id, character_name, created_at) VALUES (?, ?, ?)",
                (conv_id, character_name, now),
            )
            # Crear branch main por defecto
            conn.execute(
                "INSERT INTO branches (id, conversation_id, label, created_at) VALUES (?, ?, ?, ?)",
                ("main", conv_id, "Principal", now),
            )
            return Conversation(
                id=conv_id,
                character_name=character_name,
                created_at=now,
                active_branch_id="main",
            )

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            return Conversation(**dict(row)) if row is not None else None

    def set_active_leaf(
        self, conversation_id: str, branch_id: str, message_id: int
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE conversations SET active_branch_id = ?, active_leaf_message_id = ? WHERE id = ?",
                (branch_id, message_id, conversation_id),
            )

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def add_message(
        self,
        conversation_id: str,
        branch_id: str,
        role: str,
        content: str,
        parent_id: Optional[int] = None,
        tool_calls: Optional[list[dict]] = None,
        tool_call_id: Optional[str] = None,
        token_count: int = 0,
        speaker_tag: str = "",
        thinking: str = "",
    ) -> int:
        self._log("SQLITE", f"add_message conv={conversation_id[:8]} role={role} speaker={speaker_tag} thinking='{(thinking or '')[:40]}' content='{(content or '')[:50]}'")
        with self._tx() as conn:
            last_idx = conn.execute(
                "SELECT COALESCE(MAX(message_index), 0) FROM messages WHERE conversation_id = ? AND branch_id = ?",
                (conversation_id, branch_id),
            ).fetchone()[0]
            next_idx = last_idx + 1

            now = datetime.now(timezone.utc).isoformat()
            tool_calls_json = json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None

            conn.execute(
                """INSERT INTO messages
                   (conversation_id, branch_id, message_index, parent_id,
                    role, content, tool_calls, tool_call_id, token_count, speaker_tag, thinking, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (conversation_id, branch_id, next_idx, parent_id,
                 role, content, tool_calls_json, tool_call_id, token_count, speaker_tag, thinking, now),
            )
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def get_message_path(self, leaf_message_id: int) -> list[ChatMessage]:
        """Reconstruye el camino desde la raíz del branch hasta leaf
        siguiendo parent_id."""
        with self._tx() as conn:
            result: list[ChatMessage] = []
            current_id: Optional[int] = leaf_message_id

            while current_id is not None:
                row = conn.execute(
                    "SELECT * FROM messages WHERE id = ?", (current_id,)
                ).fetchone()
                if row is None:
                    break
                result.insert(0, ChatMessage(**dict(row)))
                current_id = row["parent_id"]

            return result

    def get_branch_messages(
        self,
        conversation_id: str,
        branch_id: str,
        since_index: int = 0,
        limit: int = 100,
        status_filter: str = "active",
    ) -> list[ChatMessage]:
        with self._tx() as conn:
            rows = conn.execute(
                """SELECT * FROM messages
                   WHERE conversation_id = ? AND branch_id = ?
                     AND message_index > ? AND status = ?
                   ORDER BY message_index ASC
                   LIMIT ?""",
                (conversation_id, branch_id, since_index, status_filter, limit),
            ).fetchall()
            return [ChatMessage(**dict(r)) for r in rows]

    def get_messages_since(
        self, conversation_id: str, since_id: int = 0, limit: int = 50
    ) -> list[ChatMessage]:
        with self._tx() as conn:
            rows = conn.execute(
                """SELECT * FROM messages
                   WHERE conversation_id = ? AND id > ? AND status = 'active'
                   ORDER BY id ASC LIMIT ?""",
                (conversation_id, since_id, limit),
            ).fetchall()
            return [ChatMessage(**dict(r)) for r in rows]

    def get_branch_messages_since(
        self, conversation_id: str, branch_id: str, since_id: int = 0, limit: int = 50
    ) -> list[ChatMessage]:
        with self._tx() as conn:
            rows = conn.execute(
                """SELECT * FROM messages
                   WHERE conversation_id = ? AND branch_id = ?
                     AND id > ? AND status = 'active'
                   ORDER BY id ASC LIMIT ?""",
                (conversation_id, branch_id, since_id, limit),
            ).fetchall()
            return [ChatMessage(**dict(r)) for r in rows]

    def get_active_branch_messages(
        self, conversation_id: str, branch_id: str, leaf_id: int, limit: int = 50
    ) -> list[ChatMessage]:
        self._log("SQLITE", f"get_active_branch_messages conv={conversation_id[:8]} branch={branch_id} leaf={leaf_id}")
        """Retorna los mensajes activos del camino hasta leaf_id,
        hasta `limit` desde el final."""
        path = self.get_message_path(leaf_id)
        if not path:
            return []
        # Filtrar por branch_id y status activo
        path = [m for m in path if m.branch_id == branch_id and m.status == "active"]
        return path[-limit:]

    def soft_delete_message(self, message_id: int) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE messages SET status = 'deleted' WHERE id = ?",
                (message_id,),
            )

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    def _next_branch_id(self, conversation_id: str) -> str:
        with self._tx() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM branches WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            return f"br_{count + 1:03d}"

    def create_branch(
        self,
        conversation_id: str,
        from_message_id: int,
        label: str = "",
    ) -> str:
        with self._tx() as conn:
            branch_id = self._next_branch_id(conversation_id)
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO branches
                   (id, conversation_id, parent_branch_id, created_from_message_id, label, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (branch_id, conversation_id, None, from_message_id, label, now),
            )
            return branch_id

    def get_branches(self, conversation_id: str) -> list[Branch]:
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT * FROM branches WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
            return [Branch(**dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    def add_summary(
        self,
        conversation_id: str,
        branch_id: str,
        start_message_id: int,
        end_message_id: int,
        summary: str,
        topic: str = "",
        reason: str = "interval",
    ) -> int:
        self._log("SQLITE", f"add_summary conv={conversation_id[:8]} reason={reason}")
        with self._tx() as conn:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO summaries
                   (conversation_id, branch_id, start_message_id, end_message_id,
                    summary, semantic_topic, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (conversation_id, branch_id, start_message_id, end_message_id,
                 summary, topic, reason, now),
            )
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def get_summaries(
        self,
        conversation_id: str,
        branch_id: str,
        limit: int = 5,
    ) -> list[ConversationSummary]:
        with self._tx() as conn:
            rows = conn.execute(
                """SELECT * FROM summaries
                   WHERE conversation_id = ? AND branch_id = ?
                   ORDER BY end_message_id DESC
                   LIMIT ?""",
                (conversation_id, branch_id, limit),
            ).fetchall()
            return [ConversationSummary(**dict(r)) for r in rows]

    def get_summary_by_id(self, summary_id: int) -> Optional[ConversationSummary]:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM summaries WHERE id = ?", (summary_id,)
            ).fetchone()
            return ConversationSummary(**dict(row)) if row is not None else None

    def delete_summary(self, summary_id: int) -> bool:
        with self._tx() as conn:
            cur = conn.execute("DELETE FROM summaries WHERE id = ?", (summary_id,))
            return cur.rowcount > 0

    def update_summary_end(self, summary_id: int, end_message_id: int) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE summaries SET end_message_id = ? WHERE id = ?",
                (end_message_id, summary_id),
            )

    def mark_summary_delivered(self, summary_id: int, delivered_message_id: int) -> None:
        self.update_summary_end(summary_id, delivered_message_id)

    # ------------------------------------------------------------------
    # Semantic sync (ChromaDB indexación manual)
    # ------------------------------------------------------------------

    def get_semantic_sync(self, conversation_id: str) -> dict:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM semantic_sync WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if row is not None:
                return dict(row)
            return {
                "conversation_id": conversation_id,
                "last_synced_message_id": 0,
                "last_synced_branch_id": "main",
                "dirty": 1,
                "sync_hash": "",
                "last_sync_at": None,
            }

    def mark_semantic_dirty(self, conversation_id: str) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO semantic_sync (conversation_id, dirty)
                   VALUES (?, 1)
                   ON CONFLICT(conversation_id) DO UPDATE SET dirty = 1""",
                (conversation_id,),
            )

    def update_semantic_sync(
        self,
        conversation_id: str,
        last_message_id: int,
        branch_id: str,
        sync_hash: str = "",
    ) -> None:
        with self._tx() as conn:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO semantic_sync
                   (conversation_id, last_synced_message_id, last_synced_branch_id, sync_hash, dirty, last_sync_at)
                   VALUES (?, ?, ?, ?, 0, ?)
                   ON CONFLICT(conversation_id) DO UPDATE SET
                       last_synced_message_id = excluded.last_synced_message_id,
                       last_synced_branch_id = excluded.last_synced_branch_id,
                       sync_hash = excluded.sync_hash,
                       dirty = 0,
                       last_sync_at = excluded.last_sync_at""",
                (conversation_id, last_message_id, branch_id, sync_hash, now),
            )

    # ------------------------------------------------------------------
    # State (key-value store for session state)
    # ------------------------------------------------------------------

    def set_state(self, conversation_id: str, key: str, value: str) -> None:
        """Guarda un valor de estado para la conversación."""
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO state (conversation_id, key, value)
                   VALUES (?, ?, ?)
                   ON CONFLICT(conversation_id, key) DO UPDATE SET value = excluded.value""",
                (conversation_id, key, value),
            )

    def get_state(self, conversation_id: str, key: str, default: str = "") -> str:
        """Lee un valor de estado de la conversación."""
        with self._tx() as conn:
            row = conn.execute(
                "SELECT value FROM state WHERE conversation_id = ? AND key = ?",
                (conversation_id, key),
            ).fetchone()
            return row["value"] if row else default

    # ------------------------------------------------------------------
    # Checkout (rollback no destructivo)
    # ------------------------------------------------------------------

    def checkout(self, conversation_id: str, branch_id: str, leaf_message_id: int) -> None:
        """Cambia el puntero activo a un branch + mensaje específico.
        No borra nada. Equivalente a un checkout de Git."""
        with self._tx() as conn:
            conn.execute(
                """UPDATE conversations
                   SET active_branch_id = ?, active_leaf_message_id = ?
                   WHERE id = ?""",
                (branch_id, leaf_message_id, conversation_id),
            )

    # ------------------------------------------------------------------
    # Context snapshots (debug)
    # ------------------------------------------------------------------

    def save_context_snapshot(self, conversation_id: str, prompt_text: str, token_count: int = 0) -> None:
        with self._tx() as conn:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO context_snapshots (conversation_id, built_prompt, token_count, created_at) VALUES (?, ?, ?, ?)",
                (conversation_id, prompt_text, token_count, now),
            )

    # ------------------------------------------------------------------
    # Tool calls
    # ------------------------------------------------------------------

    def add_tool_call(
        self,
        message_id: int,
        tool_name: str,
        arguments_json: Optional[str] = None,
        response_json: Optional[str] = None,
        status: str = "pending",
        latency_ms: float = 0.0,
    ) -> int:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO tool_calls
                   (message_id, tool_name, arguments_json, response_json, status, latency_ms)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (message_id, tool_name, arguments_json, response_json, status, latency_ms),
            )
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def get_tool_calls(self, message_id: int) -> list[dict]:
        with self._tx() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM tool_calls WHERE message_id = ?", (message_id,)
            ).fetchall()
            return [dict(r) for r in rows]
