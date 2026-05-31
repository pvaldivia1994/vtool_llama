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
    if not self._char_dir:
        return []
    episodes_dir = self._char_dir / "_memory" / "episodes"
    if not episodes_dir.exists():
        return []

    result = []
    for path in sorted(episodes_dir.glob("episode_*.json")):
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            result.append({
                "file": path.name,
                "episode_id": data.get("episode_id", 0),
                "timestamp": data.get("timestamp", ""),
                "summary": data.get("summary", ""),
                "message_count": len(data.get("messages", [])),
            })
        except Exception:
            continue
    return result


CharacterManager.list_episodes = list_episodes


def load_episode(self: CharacterManager, episode_id: int) -> None:
    if not self._char_dir:
        raise RuntimeError("No hay personaje cargado.")
    path = self._char_dir / "_memory" / "episodes" / f"episode_{episode_id:03d}.json"
    if not path.exists():
        raise ValueError(f"Episodio #{episode_id} no encontrado.")
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    self.current_episode = EpisodeSnapshot(
        episode_id=data.get("episode_id", episode_id),
        timestamp=data.get("timestamp", ""),
        summary=data.get("summary", ""),
        messages=data.get("messages", []),
    )


CharacterManager.load_episode = load_episode


def delete_episode(self: CharacterManager, episode_id: int) -> bool:
    if not self._char_dir:
        return False
    path = self._char_dir / "_memory" / "episodes" / f"episode_{episode_id:03d}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


CharacterManager.delete_episode = delete_episode
