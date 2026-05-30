"""
Estrategias de retrieval para el orquestador de contexto.

Se usan desde engine/retrieval.py o directamente desde ContextBuilder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..types import PromptSection

if TYPE_CHECKING:
    from ..db import ChatStore
    from ..utils import TokenCounter
    from .context_injector import ContextInjector


class SceneContextStrategy:
    """Inyecta la última escena guardada con /scene_view."""

    priority = 15

    def retrieve(
        self,
        store: ChatStore,
        token_counter: TokenCounter,
        conversation_id: str,
        branch_id: str,
        leaf_message_id: int,
        budget: int,
    ) -> PromptSection:
        from .context_injector import ContextInjector

        injector = ContextInjector(store, conversation_id, branch_id)
        scene = injector.get_scene()
        if not scene:
            return PromptSection(type="scene", priority=self.priority, tokens=0, messages=[])

        tokens = token_counter.count_text(scene)
        return PromptSection(
            type="scene", priority=self.priority, tokens=tokens,
            messages=[{"role": "system", "content": scene}],
        )


class ContextInjectionStrategy:
    """Inyecta las entradas de contexto activas (definiciones van en el prompt compilado)."""

    priority = 10

    def retrieve(
        self,
        store: ChatStore,
        token_counter: TokenCounter,
        conversation_id: str,
        branch_id: str,
        leaf_message_id: int,
        budget: int,
    ) -> PromptSection:
        from .context_injector import ContextInjector

        injector = ContextInjector(store, conversation_id, branch_id)
        contexts = injector.get_active_contexts()
        if not contexts:
            return PromptSection(type="context", priority=self.priority, tokens=0, messages=[])

        lines: list[str] = []
        running = 0
        for ctx in contexts:
            tokens = token_counter.count_text(ctx)
            if running + tokens > budget and running > 0:
                break
            lines.append(ctx)
            running += tokens

        content = "\n".join(lines)
        return PromptSection(
            type="context", priority=self.priority, tokens=running,
            messages=[{"role": "system", "content": content}] if content else [],
        )
