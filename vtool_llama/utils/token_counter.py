"""
Contador centralizado de tokens para evitar dispersión en ChatMemory,
ContextBuilder, summaries, etc.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..types import PromptSection

# Fallback: ~4 chars por token (estimación conservadora para modelos
# tipo Llama/Qwen con BPE/tokenización similar)
_CHARS_PER_TOKEN = 4.0


class TokenCounter:
    def __init__(
        self,
        tokenize_fn: Optional[Callable[[str], int]] = None,
    ):
        self._tokenize_fn = tokenize_fn

    @property
    def has_tokenizer(self) -> bool:
        return self._tokenize_fn is not None

    def count_text(self, text: Optional[str]) -> int:
        if not text:
            return 0
        if self._tokenize_fn:
            return self._tokenize_fn(text)
        return max(1, round(len(text) / _CHARS_PER_TOKEN))

    def count_messages(self, messages: list[dict]) -> int:
        total = 0
        for m in messages:
            total += self.count_text(m.get("content", ""))
            tool_calls = m.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    total += self.count_text(tc.get("function", {}).get("arguments", ""))
        return total

    def estimate_prompt(self, sections: list[PromptSection]) -> int:
        return sum(s.tokens for s in sections)

    def truncate_to_budget(
        self,
        messages: list[dict],
        budget: int,
        preserve_last: int = 1,
    ) -> list[dict]:
        """Recorta mensajes hasta que quepan en budget, preservando
        los últimos `preserve_last` mensajes."""
        if budget <= 0:
            return messages[-preserve_last:] if messages else []

        # Primero contar los que hay que preservar sí o sí
        preserved = messages[-preserve_last:] if preserve_last else []
        preserved_tokens = self.count_messages(preserved)

        rest = messages[:-preserve_last] if preserve_last else list(messages)
        result: list[dict] = []
        running = 0

        # Agregar desde el más reciente hacia atrás
        for m in reversed(rest):
            tokens = self.count_text(m.get("content", ""))
            if running + tokens + preserved_tokens > budget:
                break
            result.insert(0, m)
            running += tokens

        result.extend(preserved)
        return result
