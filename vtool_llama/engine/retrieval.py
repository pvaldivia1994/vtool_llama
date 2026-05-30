"""
Estrategias de recuperación simplificadas para el ContextBuilder.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from ..types import PromptSection

if TYPE_CHECKING:
    from ..db import ChatStore
    from ..utils import TokenCounter


class RetrievalStrategy(ABC):
    def __init__(self, priority: int = 100):
        self.priority = priority

    @abstractmethod
    def retrieve(
        self,
        store: ChatStore,
        token_counter: TokenCounter,
        conversation_id: str,
        branch_id: str,
        leaf_message_id: int,
        budget: int,
    ) -> PromptSection:
        ...


class RecentMessagesStrategy(RetrievalStrategy):
    """Últimos mensajes activos del camino hasta leaf_message_id."""

    def __init__(self, max_messages: int = 25, priority: int = 50):
        super().__init__(priority=priority)
        self._max_messages = max_messages

    def retrieve(
        self,
        store: ChatStore,
        token_counter: TokenCounter,
        conversation_id: str,
        branch_id: str,
        leaf_message_id: int,
        budget: int,
    ) -> PromptSection:
        path = store.get_active_branch_messages(
            conversation_id, branch_id, leaf_message_id, limit=self._max_messages
        )
        if not path:
            return PromptSection(type="history", priority=self.priority, tokens=0, messages=[])

        messages: list[dict] = []
        running = 0

        for m in reversed(path):
            msg_dict: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.tool_calls:
                msg_dict["tool_calls"] = json.loads(m.tool_calls)
            if m.tool_call_id:
                msg_dict["tool_call_id"] = m.tool_call_id

            tokens = token_counter.count_text(m.content)
            if running + tokens > budget and running > 0:
                break
            messages.insert(0, msg_dict)
            running += tokens

        return PromptSection(
            type="history",
            priority=self.priority,
            tokens=running,
            messages=messages,
        )


class SemanticRetrievalStrategy(RetrievalStrategy):
    """Retrieval semántico desde ChromaDB (conversation chunks manuales).
    Solo activo si hay chroma_store configurado."""

    def __init__(self, chroma_store=None, min_similarity: float = 0.3, priority: int = 20):
        super().__init__(priority=priority)
        self._chroma_store = chroma_store
        self._min_similarity = min_similarity

    def retrieve(
        self,
        store: ChatStore,
        token_counter: TokenCounter,
        conversation_id: str,
        branch_id: str,
        leaf_message_id: int,
        budget: int,
    ) -> PromptSection:
        if not self._chroma_store or not self._chroma_store.is_available:
            return PromptSection(type="semantic", priority=self.priority, tokens=0, messages=[])

        # Obtener los últimos 3 mensajes como contexto para la query semántica
        path = store.get_active_branch_messages(conversation_id, branch_id, leaf_message_id, limit=3)
        query_parts = [m.content for m in path if m.content]
        query = " ".join(query_parts) if query_parts else ""

        if not query:
            return PromptSection(type="semantic", priority=self.priority, tokens=0, messages=[])

        results = self._chroma_store.search(query, top_k=3)
        if not results:
            return PromptSection(type="semantic", priority=self.priority, tokens=0, messages=[])

        lines: list[str] = []
        running = 0

        for r in results:
            # Filtrar por similaridad mínima para evitar falsos positivos irrelevantes
            if r.get("similarity", 0.0) < self._min_similarity:
                continue
            doc = r.get("document", "")
            if not doc:
                continue
            tokens = token_counter.count_text(doc)
            if running + tokens > budget and running > 0:
                break
            lines.append(doc)
            running += tokens

        content = "\n\n---\n\n".join(lines) if lines else ""
        return PromptSection(
            type="semantic",
            priority=self.priority,
            tokens=running,
            messages=[{"role": "system", "content": f"[MEMORIA SEMÁNTICA]\n{content}"}] if content else [],
        )


# Las estrategias SceneContextStrategy y ContextInjectionStrategy
# se movieron a orquestador/strategies.py
