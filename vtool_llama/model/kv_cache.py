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


def reset_keep(self: ModelManager) -> None:
    """Borra el KV cache después de n_keep. El core del system prompt queda intacto.

    - Si _n_keep es None: reset completo (legacy).
    - Si _n_keep > 0 y n_tokens > n_keep: usa kv_cache_seq_rm para borrar solo
      posiciones [n_keep, n_tokens). El core [0..n_keep) queda intacto.
    - Si n_tokens <= n_keep: no hay nada que borrar.
    - Si la API de bajo nivel no está disponible: fallback a reset() completo.
    """
    if self._n_keep is None or self._n_keep <= 0:
        if hasattr(self._model, "reset") and callable(self._model.reset):
            self._model.reset()
        return

    n_tokens = getattr(self._model, "n_tokens", 0)
    if n_tokens <= self._n_keep:
        return  # Todo es core, no hay nada que borrar

    try:
        ctx = getattr(self._model, "_ctx", None) or getattr(self._model, "ctx", None)
        if ctx is not None and hasattr(ctx, "kv_cache_seq_rm"):
            ctx.kv_cache_seq_rm(-1, self._n_keep, n_tokens)
            self._model.n_tokens = self._n_keep
            self._log(
                "MODEL",
                f"reset_keep: core intacto ({self._n_keep} tokens, "
                f"liberados {n_tokens - self._n_keep})",
            )
            return

        # Fallback: API no disponible
        if hasattr(self._model, "reset") and callable(self._model.reset):
            self._model.reset()
            self._log("MODEL", "reset_keep: API kv_cache_seq_rm no disponible, reset completo")
    except Exception as e:
        self._log("MODEL", f"reset_keep: error ({e}), fallback a reset completo")
        if hasattr(self._model, "reset") and callable(self._model.reset):
            self._model.reset()


ModelManager.reset_keep = reset_keep
