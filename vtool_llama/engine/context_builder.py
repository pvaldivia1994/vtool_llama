"""
ContextBuilder — Orquestador de construcción de contexto.

No implementa retrieval directamente. Delega en estrategias
(RetrievalStrategy) y consolida los resultados respetando
el presupuesto de tokens.

Flujo:
  1. System prompt → PromptSection priority=0
  2. Cada estrategia retrieve() ordenada por priority
  3. Consolidar en list[dict] para el LLM
  4. Guardar context_snapshot si debug
"""

from __future__ import annotations

from typing import Optional

from ..types import PromptSection
from .retrieval import RetrievalStrategy


class ContextBuilder:
    def __init__(
        self,
        store,
        token_counter,
        strategies: Optional[list[RetrievalStrategy]] = None,
    ):
        self._store = store
        self._token_counter = token_counter
        self._strategies = sorted(strategies or [], key=lambda s: s.priority)

    def build(
        self,
        conversation_id: str,
        branch_id: str,
        leaf_message_id: int,
        token_budget: int,
        system_prompt: str = "",
        user_prompt: str = "",   # ← v9: para retrieval semántico
    ) -> list[PromptSection]:
        sections: list[PromptSection] = []

        # 1. System prompt
        if system_prompt:
            sys_tokens = self._token_counter.count_text(system_prompt)
            sections.append(PromptSection(
                type="system",
                priority=0,
                tokens=sys_tokens,
                messages=[{"role": "system", "content": system_prompt}],
            ))
            remaining = token_budget - sys_tokens
        else:
            remaining = token_budget

        # 2. Estrategias en orden de prioridad
        for strategy in self._strategies:
            if remaining <= 0:
                break
            section = strategy.retrieve(
                self._store,
                self._token_counter,
                conversation_id,
                branch_id,
                leaf_message_id,
                remaining,
                user_prompt=user_prompt,   # ← v9
            )
            if section.messages:
                sections.append(section)
                remaining -= section.tokens

        return sections

    def build_messages(
        self,
        conversation_id: str,
        branch_id: str,
        leaf_message_id: int,
        token_budget: int,
        system_prompt: str = "",
        user_prompt: str = "",
    ) -> list[dict]:
        """Wrapper que retorna directamente list[dict] para el LLM."""
        sections = self.build(
            conversation_id, branch_id, leaf_message_id, token_budget,
            system_prompt, user_prompt=user_prompt,
        )
        messages: list[dict] = []
        for s in sections:
            messages.extend(s.messages)
        return messages

    def get_section_breakdown(
        self,
        conversation_id: str,
        branch_id: str,
        leaf_message_id: int,
        token_budget: int,
        system_prompt: str = "",
    ) -> list[dict]:
        """Retorna desglose de tokens por sección (útil para debugging)."""
        sections = self.build(
            conversation_id, branch_id, leaf_message_id, token_budget, system_prompt
        )
        return [
            {"type": s.type, "tokens": s.tokens, "messages": len(s.messages)}
            for s in sections
        ]
