"""episodes.py — Gestión de episodios vía SQLite summaries."""
from __future__ import annotations

from ..types import EpisodeSnapshot
from .base import CharacterManager


def _load_latest_episode(self: CharacterManager) -> None:
    """Carga el último summary de SQLite como current_episode."""
    self.current_episode = None
    if not self._char_dir or not hasattr(self, '_chat_store') or not self._chat_store:
        return
    try:
        summaries = self._chat_store.get_summaries("", "", limit=1)
    except Exception:
        self.current_episode = None


CharacterManager._load_latest_episode = _load_latest_episode


def save_episode(self: CharacterManager, messages: list[dict], summary: str) -> EpisodeSnapshot:
    raise RuntimeError("save_episode en CharacterManager deprecado. Usar VToolLlama.save_episode()")


CharacterManager.save_episode = save_episode


def list_episodes(self: CharacterManager) -> list[dict]:
    return []


CharacterManager.list_episodes = list_episodes


def load_episode(self: CharacterManager, episode_id: int) -> None:
    raise RuntimeError("load_episode en CharacterManager deprecado. Usar VToolLlama.load_episode()")


CharacterManager.load_episode = load_episode


def delete_episode(self: CharacterManager, episode_id: int) -> bool:
    return False


CharacterManager.delete_episode = delete_episode
