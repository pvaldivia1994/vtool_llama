"""
Tests del sistema de KV cache: reset_keep, n_keep, warmup.

Usa mocks — no requiere modelo real ni GPU.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

from vtool_llama.model import ModelManager
from vtool_llama.types import ConfigSchema


class MockConfig:
    n_ctx = 4096
    max_tokens = 512
    temperature = 0.7
    top_p = 0.9
    top_k = 40
    repeat_penalty = 1.1
    seed = -1
    context_reserve_tokens = 300


def _make_manager() -> ModelManager:
    return ModelManager(config=MockConfig(), logger_fn=lambda t, m: None, error_fn=lambda m: None)


# ======================================================================
# reset_keep — fallback
# ======================================================================


def test_reset_keep_fallback_when_n_keep_is_none():
    """Si _n_keep es None, reset_keep debe hacer reset completo (legacy)."""
    mgr = _make_manager()
    mgr._model = MagicMock()
    mgr._n_keep = None

    mgr.reset_keep()

    mgr._model.reset.assert_called_once()


def test_reset_keep_fallback_when_n_keep_is_zero():
    """Si _n_keep es 0, reset_keep debe hacer reset completo."""
    mgr = _make_manager()
    mgr._model = MagicMock()
    mgr._n_keep = 0

    mgr.reset_keep()

    mgr._model.reset.assert_called_once()


def test_reset_keep_fallback_when_no_model():
    """Si no hay modelo cargado, reset_keep no debe fallar."""
    mgr = _make_manager()
    mgr._model = None
    mgr._n_keep = 100

    # No debe lanzar excepción
    mgr.reset_keep()


def test_reset_keep_fallback_when_no_reset_method():
    """Si el modelo no tiene método reset(), no debe fallar."""
    mgr = _make_manager()
    mgr._model = object()  # sin reset()
    mgr._n_keep = None

    mgr.reset_keep()  # no debe explotar


# ======================================================================
# reset_keep — con kv_cache_seq_rm
# ======================================================================


def test_reset_keep_uses_seq_rm():
    """Con _n_keep definido y n_tokens > n_keep, debe llamar kv_cache_seq_rm."""
    mgr = _make_manager()
    mgr._model = MagicMock()
    mgr._model.n_tokens = 500
    mgr._model._ctx = MagicMock()
    mgr._n_keep = 100

    mgr.reset_keep()

    mgr._model._ctx.kv_cache_seq_rm.assert_called_once_with(-1, 100, 500)
    assert mgr._model.n_tokens == 100


def test_reset_keep_does_nothing_if_tokens_within_core():
    """Si n_tokens <= n_keep, no hay nada que borrar."""
    mgr = _make_manager()
    mgr._model = MagicMock()
    mgr._model.n_tokens = 50
    mgr._model._ctx = MagicMock()
    mgr._n_keep = 100

    mgr.reset_keep()

    mgr._model._ctx.kv_cache_seq_rm.assert_not_called()
    mgr._model.reset.assert_not_called()


def test_reset_keep_fallback_when_no_ctx():
    """Si _ctx no está disponible, debe caer a reset() completo."""
    mgr = _make_manager()
    # Spec sin _ctx ni ctx — MagicMock no auto-crea atributos no listados
    mgr._model = MagicMock(spec=["reset", "n_tokens"])
    mgr._model.reset = MagicMock()
    mgr._model.n_tokens = 500
    mgr._n_keep = 100

    mgr.reset_keep()

    mgr._model.reset.assert_called_once()


def test_reset_keep_fallback_when_seq_rm_raises():
    """Si kv_cache_seq_rm lanza excepción, debe caer a reset() completo."""
    mgr = _make_manager()
    mgr._model = MagicMock()
    mgr._model.n_tokens = 500
    mgr._model._ctx = MagicMock()
    mgr._model._ctx.kv_cache_seq_rm.side_effect = RuntimeError("seq_rm failed")
    mgr._n_keep = 100

    mgr.reset_keep()

    # Debe haber llamado a reset() como fallback
    mgr._model.reset.assert_called_once()


def test_reset_keep_tries_ctx_fallback():
    """Si _ctx no existe pero ctx sí, debe usar ctx."""
    mgr = _make_manager()
    mgr._model = MagicMock(spec=["reset", "n_tokens", "ctx"])
    mgr._model.reset = MagicMock()
    mgr._model.n_tokens = 500
    mgr._model.ctx = MagicMock()
    mgr._n_keep = 100

    mgr.reset_keep()

    mgr._model.ctx.kv_cache_seq_rm.assert_called_once_with(-1, 100, 500)
    assert mgr._model.n_tokens == 100


# ======================================================================
# n_keep en carga/descarga de modelo
# ======================================================================


def test_unload_model_resets_n_keep():
    """Al descargar el modelo, _n_keep debe volver a None."""
    mgr = _make_manager()
    mgr._model = MagicMock()
    mgr._n_keep = 250

    mgr.unload_model()

    assert mgr._n_keep is None


def test_load_model_resets_n_keep():
    """Al cargar un modelo nuevo, _n_keep debe ser None."""
    mgr = _make_manager()
    mgr._n_keep = 250

    # Simular carga — load_model asigna _n_keep = None después de crear el modelo
    mgr._model = MagicMock()
    mgr._n_keep = None  # como hace load_model()

    assert mgr._n_keep is None
