"""kv_cache.py — Gestión de KV Cache (warmup, save, load)."""

from __future__ import annotations

import os

from .manager import ModelManager


def save_kv_state(self: ModelManager, filepath: str) -> None:
    with self._lock:
        if not self._model:
            return
        import pickle
        state = self._model.save_state()
        with open(filepath, "wb") as f:
            pickle.dump(state, f)
        self._log("MODEL", f"KV Cache guardado en {filepath}")

ModelManager.save_kv_state = save_kv_state


def load_kv_state(self: ModelManager, filepath: str) -> bool:
    with self._lock:
        if not self._model:
            return False
        if not os.path.exists(filepath):
            return False
        try:
            import pickle
            with open(filepath, "rb") as f:
                state = pickle.load(f)
            self._model.load_state(state)
            self._log("MODEL", f"KV Cache cargado desde {filepath}")
            return True
        except Exception as e:
            self._error(f"Error cargando KV Cache {filepath}: {e}")
            return False

ModelManager.load_kv_state = load_kv_state


def warmup_system_prompt(self: ModelManager, system_prompt: str) -> None:
    with self._lock:
        if not self._model:
            return
        self._log("MODEL", "Ejecutando warmup del system prompt (KV Cache)...")
        self._model.create_chat_completion(
            messages=[{"role": "system", "content": system_prompt}],
            max_tokens=1,
        )
        self._log("MODEL", "Warmup completado.")

ModelManager.warmup_system_prompt = warmup_system_prompt
