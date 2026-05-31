"""
CharacterDebugLogger — Log de depuración por personaje.

Cuando enable_logging=true en config, escribe character_log.md
en el directorio _memory/ del personaje con el historial completo
de cada turno: mensajes enviados al modelo, contexto, trims, etc.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..types import ConfigSchema


class CharacterDebugLogger:
    """Log de depuración por personaje. Se activa con enable_logging=true."""

    def __init__(self, char_dir: Optional[Path] = None, config: Optional[ConfigSchema] = None):
        self._char_dir = char_dir
        self._enabled = bool(getattr(config, "enable_logging", False)) if config else False
        self._log_path: Optional[Path] = None
        self._turn = 0
        # Para comprimir system prompts repetidos
        self._last_system_prompt: Optional[str] = None
        self._last_ctx_info: Optional[str] = None

        if self._enabled and char_dir:
            self._log_path = char_dir / "_memory" / "character_log.md"
            if not self._log_path.exists():
                self._write_header()
            else:
                self._append(f"\n---\n# Nueva sesión: {datetime.now().isoformat()}\n\n")

    def _write_header(self) -> None:
        if not self._log_path:
            return
        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.write(f"# Character Debug Log\n")
                f.write(f"Creado: {datetime.now().isoformat()}\n")
                f.write(f"Directorio: {self._char_dir}\n\n")
                f.write("---\n\n")
        except Exception:
            self._log_path = None

    def _append(self, text: str) -> None:
        if not self._log_path:
            return
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            # Si no podemos escribir al log, lo desactivamos silenciosamente
            self._log_path = None

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def log_turn_start(self, user_prompt: str) -> None:
        """Registra el inicio de un turno con el prompt del usuario."""
        if not self._enabled:
            return
        self._turn += 1
        self._append(f"---\n### Turno {self._turn} [{self._ts()}]\n\n")
        self._append(f"**Usuario**: {user_prompt}\n\n")

    def log_messages_sent_to_model(self, messages: list[dict]) -> None:
        """Registra los mensajes enviados al modelo.

        Si el system prompt es igual al del turno anterior,
        se reemplaza por [IGUAL AL ANTERIOR] para no repetir 2000 líneas.
        """
        if not self._enabled:
            return
        self._append("### Mensajes enviados al modelo\n\n")

        # Comprimir system prompts: primera vez muestra [Cargado de base_prompt.yaml],
        # repeticiones muestran [IGUAL AL ANTERIOR]
        current_system = None
        compressed = copy.deepcopy(messages)
        for msg in compressed:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if current_system is None:
                    current_system = content
                    msg["content"] = "[Cargado de base_prompt.yaml]"
                elif self._last_system_prompt is not None and content == self._last_system_prompt:
                    msg["content"] = "[IGUAL AL ANTERIOR]"

        if current_system is not None:
            self._last_system_prompt = current_system

        log_text = json.dumps(compressed, ensure_ascii=False, indent=2)
        self._append(f"```json\n{log_text}\n```\n\n")

    def log_model_response(self, response: str) -> None:
        """Registra la respuesta del modelo."""
        if not self._enabled:
            return
        self._append(f"**Modelo**: {response}\n\n")

    def log_context_info(self, usage: dict) -> None:
        """Registra info del contexto post-inferencia."""
        if not self._enabled:
            return
        self._append("### Estado del contexto\n\n")
        self._append(f"| Métrica | Valor |\n")
        self._append(f"|---------|-------|\n")
        for k in ("total_tokens", "max_tokens", "usage_pct",
                   "n_keep", "kv_cache_tokens", "messages",
                   "prompt_budget_available", "history_tokens",
                   "system_tokens", "n_keep", "kv_cache_usage_pct"):
            if k in usage:
                self._append(f"| {k} | {usage[k]} |\n")
        self._append("\n")

    def log_trim(self, removed_count: int, reason: str = "") -> None:
        """Registra un evento de trim."""
        if not self._enabled:
            return
        self._append(f"**TRIM**: {removed_count} mensaje(s) eliminados. {reason}\n\n")

    def log_chroma_search(self, query: str, results: list, collection: str) -> None:
        """Registra una búsqueda en ChromaDB con resultados."""
        if not self._enabled:
            return
        self._append(f"### ChromaDB Search ({collection})\n\n")
        self._append(f"Query: `{query[:100]}`\n\n")
        if results:
            self._append(f"| # | Similitud | Documento |\n")
            self._append(f"|---|-----------|-----------|\n")
            for i, r in enumerate(results):
                sim = r.get("similarity", 0)
                doc = (r.get("document", "") or "")[:120]
                self._append(f"| {i} | {sim:.3f} | {doc} |\n")
            self._append("\n")
        else:
            self._append("Sin resultados.\n\n")

    def log_retrieval(self, strategy_name: str, fragments: list[dict]) -> None:
        """Registra fragmentos recuperados por estrategias de retrieval."""
        if not self._enabled:
            return
        if not fragments:
            return
        self._append(f"### Retrieval: {strategy_name}\n\n")
        for i, f in enumerate(fragments):
            content = str(f.get("content", "") or "")[:150]
            self._append(f"- **#{i}**: {content}\n")
        self._append("\n")

    def log_charcore_indexed(self, sections: list[str]) -> None:
        """Registra qué secciones del personaje se indexaron en ChromaDB."""
        if not self._enabled:
            return
        self._append(f"### Personaje indexado en ChromaDB\n\n")
        for s in sections:
            self._append(f"- {s}\n")
        self._append("\n")

    def log_reset_keep(self, n_keep: int, freed: int) -> None:
        """Registra un reset_keep con tokens liberados."""
        if not self._enabled:
            return
        self._append(f"**reset_keep**: core={n_keep}, liberados={freed}\n\n")

    def log_warning(self, msg: str) -> None:
        """Registra una advertencia."""
        if not self._enabled:
            return
        self._append(f"**WARN**: {msg}\n\n")

    def log_event(self, tag: str, msg: str) -> None:
        """Registra un evento genérico."""
        if not self._enabled:
            return
        self._append(f"[{self._ts()}] [{tag}] {msg}\n\n")

    def log_error(self, tag: str, msg: str) -> None:
        """Registra un error."""
        if not self._enabled:
            return
        self._append(f"[{self._ts()}] **ERROR [{tag}]**: {msg}\n\n")
