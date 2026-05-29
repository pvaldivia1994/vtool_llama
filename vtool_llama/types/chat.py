"""
Tipos del Chat System: event store, contexto, ramas y secciones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChatMessage:
    id: int = 0
    conversation_id: str = ""
    branch_id: str = "main"
    message_index: int = 0
    parent_id: Optional[int] = None
    role: str = ""
    content: str = ""
    tool_calls: Optional[str] = None
    tool_call_id: Optional[str] = None
    status: str = "active"
    token_count: int = 0
    created_at: str = ""


@dataclass
class ConversationSummary:
    id: int = 0
    conversation_id: str = ""
    branch_id: str = "main"
    start_message_id: int = 0
    end_message_id: int = 0
    summary: str = ""
    semantic_topic: str = ""
    reason: str = "interval"
    embedding_id: Optional[str] = None
    created_at: str = ""


@dataclass
class SemanticMemory:
    id: int = 0
    conversation_id: str = ""
    type: str = ""
    content: str = ""
    importance: float = 0.5
    source_message_id: Optional[int] = None
    confidence: float = 1.0
    access_count: int = 0
    last_accessed: Optional[str] = None
    embedding_id: Optional[str] = None
    created_at: str = ""


@dataclass
class PromptSection:
    type: str = ""
    priority: int = 0
    tokens: int = 0
    messages: list[dict] = field(default_factory=list)


@dataclass
class Branch:
    id: str = ""
    conversation_id: str = ""
    parent_branch_id: Optional[str] = None
    created_from_message_id: Optional[int] = None
    label: str = ""
    created_at: str = ""


@dataclass
class Conversation:
    id: str = ""
    character_name: str = ""
    created_at: str = ""
    active_branch_id: str = "main"
    active_leaf_message_id: int = 0
