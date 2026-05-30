"""episodes.py — Gestión de memoria episódica versionada."""

from __future__ import annotations

from dataclasses import asdict

from .base import CharacterManager
from ..types import EpisodeSnapshot


def _load_latest_episode(self: CharacterManager) -> None:
    if not self._char_dir:
        return
    episodes_dir = self._char_dir / "_memory" / "episodes"
    if not episodes_dir.exists():
        self.current_episode = None
        return

    episode_files = sorted(episodes_dir.glob("episode_*.json"))
    if not episode_files:
        self.current_episode = None
        return

    latest = episode_files[-1]
    data = self._read_json_dict(latest)
    self.current_episode = EpisodeSnapshot(
        episode_id=data.get("episode_id", 0),
        timestamp=data.get("timestamp", ""),
        summary=data.get("summary", ""),
        messages=data.get("messages", []),
    )
    self._log("EPISODE", f"Episodio #{self.current_episode.episode_id} cargado ({latest.name})")

CharacterManager._load_latest_episode = _load_latest_episode


def save_episode(self: CharacterManager, messages: list[dict], summary: str) -> EpisodeSnapshot:
    if not self._char_dir:
        raise RuntimeError("No hay personaje cargado.")
    with self._lock:
        episodes_dir = self._char_dir / "_memory" / "episodes"
        self._ensure_dir(episodes_dir)

        existing = sorted(episodes_dir.glob("episode_*.json"))
        next_id = 1
        if existing:
            try:
                last_id = int(existing[-1].stem.split("_")[-1])
                next_id = last_id + 1
            except ValueError:
                next_id = len(existing) + 1

        filename = f"episode_{next_id:03d}.json"

        episode = EpisodeSnapshot(
            episode_id=next_id,
            summary=summary,
            messages=messages,
        )
        self._write_json(episodes_dir / filename, asdict(episode))
        self.current_episode = episode
        self._prompt_dirty = True
        self._log("EPISODE", f"Episodio #{next_id} guardado ({filename})")
        return episode

CharacterManager.save_episode = save_episode


def list_episodes(self: CharacterManager) -> list[dict]:
    if not self._char_dir:
        return []
    episodes_dir = self._char_dir / "_memory" / "episodes"
    if not episodes_dir.exists():
        return []

    results = []
    for f in sorted(episodes_dir.glob("episode_*.json")):
        data = self._read_json_dict(f)
        results.append({
            "file": f.name,
            "episode_id": data.get("episode_id", 0),
            "timestamp": data.get("timestamp", ""),
            "summary": data.get("summary", "")[:80],
            "message_count": len(data.get("messages", [])),
        })
    return results

CharacterManager.list_episodes = list_episodes


def load_episode(self: CharacterManager, episode_id: int) -> None:
    if not self._char_dir:
        raise RuntimeError("No hay personaje cargado.")

    filename = f"episode_{episode_id:03d}.json"
    filepath = self._char_dir / "_memory" / "episodes" / filename
    if not filepath.exists():
        raise ValueError(f"Episodio #{episode_id} no encontrado.")

    data = self._read_json_dict(filepath)
    self.current_episode = EpisodeSnapshot(
        episode_id=data.get("episode_id", episode_id),
        timestamp=data.get("timestamp", ""),
        summary=data.get("summary", ""),
        messages=data.get("messages", []),
    )
    self._prompt_dirty = True
    self._log("EPISODE", f"Episodio #{episode_id} restaurado (rollback).")

    target_timestamp = self.current_episode.timestamp
    if target_timestamp and self._chat_chroma and self._chat_chroma.is_available:
        self._log("EPISODE", f"Ejecutando rollback de ChromaDB a partir del timestamp: {target_timestamp}")
        self._chat_chroma.delete_by_metadata(where={"timestamp": {"$gt": target_timestamp}})

CharacterManager.load_episode = load_episode


def delete_episode(self: CharacterManager, episode_id: int) -> bool:
    if not self._char_dir:
        return False
    filename = f"episode_{episode_id:03d}.json"
    filepath = self._char_dir / "_memory" / "episodes" / filename
    if filepath.exists():
        filepath.unlink()
        self._log("EPISODE", f"Episodio #{episode_id} eliminado.")
        if self.current_episode and self.current_episode.episode_id == episode_id:
            self._load_latest_episode()
        return True
    return False

CharacterManager.delete_episode = delete_episode
