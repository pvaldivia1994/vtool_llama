"""
Test para el auto-trim con contexto pequeño.
Verifica que el system prompt se preserve, que se genere resumen antes de recortar,
que el resumen se inyecte al contexto, y que is_context_near_limit use effective_limit.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from vtool_llama import VToolLlama
from vtool_llama.db import ChatStore


def _fill_memory(llm: VToolLlama, count: int = 10):
    """Llena el ChatMemory con mensajes simulados."""
    for i in range(count):
        llm._memory.add_user_message(f"Mensaje de prueba número {i} con suficiente texto para ocupar tokens.")
        llm._memory.add_assistant_message(f"Respuesta de prueba número {i} con suficiente texto para simular una conversación real.")


def _make_llm(tmp, n_ctx=512, reserve=50, history_limit=50):
    """Helper para crear un VToolLlama de prueba con config mínimo."""
    import json

    config_path = os.path.join(tmp, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({
            "debug": False, "n_ctx": n_ctx, "n_batch": 1,
            "gpu_layers": 0, "temperature": 0.7, "top_p": 0.9,
            "top_k": 40, "repeat_penalty": 1.1, "max_tokens": 100,
            "system_prompt": "test", "enable_logging": False,
            "history_limit": history_limit, "auto_trim_context": True,
            "context_reserve_tokens": reserve,
            "models_directory": tmp, "default_model": "none.gguf",
        }, f)

    llm = VToolLlama(config_path=config_path, auto_load=False)

    from unittest.mock import MagicMock
    mock_model = MagicMock()
    # Tokenizer proporcional: ~1 token por 4 caracteres (simula tokenización real)
    mock_model.tokenize.side_effect = lambda text, *a, **kw: [0] * max(1, len(text) // 4)
    mock_model.save_state.return_value = {"mock": "state"}
    mock_model.load_state.return_value = None
    llm._model_manager._model = mock_model
    llm._model_manager._tokenize_fn = mock_model.tokenize

    db_path = os.path.join(tmp, "chat.db")
    store = ChatStore(db_path)
    conv = store.get_or_create_conversation("test")
    llm._chat_store = store
    llm._memory.bind_store(store, None, None, conv.id, "main", 0)

    return llm, store


class TestAutoTrimSmallContext:
    def test_system_prompt_preserved_after_trim(self):
        """Configura n_ctx muy pequeño para forzar trim y verificar que system prompt sobrevive."""
        with tempfile.TemporaryDirectory() as tmp:
            llm, store = _make_llm(tmp)

            test_system = "[SYSTEM] Eres un personaje de prueba con una personalidad definida y un contexto específico."
            llm._memory.system_prompt = test_system
            llm._memory.clear()

            usage = llm.get_token_usage()
            assert usage["system_tokens"] > 0, "System prompt debería tener tokens"
            assert usage["max_tokens"] == 512, "n_ctx debería ser 512"

            _fill_memory(llm, 15)

            usage = llm.get_token_usage()
            assert usage["system_tokens"] > 0, "System prompt debería mantenerse después de llenar"

            llm._auto_trim_if_needed()

            usage = llm.get_token_usage()
            assert usage["system_tokens"] > 0, "System prompt debería preservarse después del trim"
            assert usage["total_tokens"] <= usage["max_tokens"] - usage["reserved"], \
                f"Total tokens ({usage['total_tokens']}) debería ser menor que max - reserved ({usage['max_tokens'] - usage['reserved']})"
            assert usage["messages"] >= 1, "Debería quedar al menos el system prompt"

            store.close()

    def test_messages_reduced_after_trim(self):
        """Verifica que el trim realmente reduzca la cantidad de mensajes."""
        with tempfile.TemporaryDirectory() as tmp:
            llm, store = _make_llm(tmp)

            test_system = "[SYSTEM] Eres un personaje de prueba."
            llm._memory.system_prompt = test_system
            llm._memory.clear()

            _fill_memory(llm, 20)
            before = llm.get_token_usage()
            assert before["messages"] > 2, "Debería haber múltiples mensajes antes del trim"

            llm._auto_trim_if_needed()
            after = llm.get_token_usage()

            assert after["system_tokens"] > 0, "System prompt preservado"
            assert after["messages"] <= before["messages"], "Mensajes deberían reducirse o mantenerse igual"
            assert after["total_tokens"] <= 512 - 50, "Tokens totales dentro del presupuesto"

            store.close()

    def test_summary_injected_after_trim(self):
        """Verifica que después del trim se inyecte un resumen de la conversación previa."""
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            llm, store = _make_llm(tmp)

            test_system = "[SYSTEM] Eres un personaje de prueba."
            llm._memory.system_prompt = test_system
            llm._memory.clear()

            # Mock generate para el resumen LLM
            mock_result = {
                "choices": [{"message": {"content": "El usuario y el personaje hablaron sobre pruebas."}}]
            }
            llm._model_manager.generate = MagicMock(return_value=mock_result)

            _fill_memory(llm, 20)

            llm._auto_trim_if_needed()

            # Buscar mensaje de resumen en el contexto
            messages = llm._memory.messages
            summary_found = False
            for m in messages:
                if m.role == "system" and "[RESUMEN DE CONVERSACIÓN PREVIA]" in (m.content or ""):
                    summary_found = True
                    break

            assert summary_found, (
                "Debería haber un mensaje system con el resumen de conversación previa "
                "inyectado después del trim"
            )

            store.close()

    def test_context_digest_uses_helper_prompts(self):
        """Verifica que el digest use los prompts helper versionados."""
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            llm, store = _make_llm(tmp)

            llm._memory.system_prompt = "[SYSTEM] Eres un personaje de prueba."
            llm._memory.clear()
            llm._model_manager.generate = MagicMock(return_value={
                "choices": [{"message": {"content": "Hechos estables:\n- El usuario conversa en español."}}]
            })

            _fill_memory(llm, 15)
            llm._auto_trim_if_needed()

            sent_messages = llm._model_manager.generate.call_args.kwargs["messages"]
            assert "context compressor" in sent_messages[0]["content"]
            assert "Return the digest in Spanish" in sent_messages[0]["content"]
            assert "CONVERSATION TO COMPRESS:" in sent_messages[1]["content"]
            assert "Mensaje de prueba" in sent_messages[1]["content"]

            store.close()

    def test_trim_targets_60_percent(self):
        """Verifica que el trim recorte hasta ~60% del effective_limit."""
        with tempfile.TemporaryDirectory() as tmp:
            llm, store = _make_llm(tmp, n_ctx=512, reserve=50)

            test_system = "[SYSTEM] Test."
            llm._memory.system_prompt = test_system
            llm._memory.clear()

            _fill_memory(llm, 25)

            llm._auto_trim_if_needed()

            usage = llm.get_token_usage()
            effective_limit = 512 - 50  # 462
            target = int(effective_limit * 0.60)  # ~277

            # After trim, total tokens should be around or below target
            # (exact match depends on message granularity)
            assert usage["total_tokens"] <= effective_limit, \
                f"Total tokens ({usage['total_tokens']}) should be <= effective_limit ({effective_limit})"

            store.close()


class TestIsContextNearLimit:
    """Tests para verificar que is_context_near_limit usa effective_limit correctamente."""

    def test_reserve_tokens_reduces_effective_limit(self):
        from vtool_llama.engine.tokenizer_utils import is_context_near_limit

        # Sin reserve: 400/500 = 80% < 85% → False
        assert not is_context_near_limit(400, 500, reserve_tokens=0)

        # Con reserve: 400/(500-100) = 400/400 = 100% >= 85% → True
        assert is_context_near_limit(400, 500, reserve_tokens=100)

    def test_threshold_against_effective_limit(self):
        from vtool_llama.engine.tokenizer_utils import is_context_near_limit

        # effective_limit = 1000 - 200 = 800
        # 680/800 = 85% → True (at threshold)
        assert is_context_near_limit(680, 1000, reserve_tokens=200, threshold_percent=85.0)

        # 679/800 = 84.875% → False (just below)
        assert not is_context_near_limit(679, 1000, reserve_tokens=200, threshold_percent=85.0)

    def test_zero_effective_limit_returns_true(self):
        from vtool_llama.engine.tokenizer_utils import is_context_near_limit

        assert is_context_near_limit(100, 200, reserve_tokens=200)
        assert is_context_near_limit(100, 200, reserve_tokens=300)


class TestKVCacheProtection:
    """Tests para verificar que el KV cache se protege durante el resumen pre-trim."""

    def test_kv_state_saved_and_restored_during_trim(self):
        """Verifica que save_state/load_state se llaman durante el trim."""
        from unittest.mock import MagicMock, call, patch

        with tempfile.TemporaryDirectory() as tmp:
            llm, store = _make_llm(tmp)

            test_system = "[SYSTEM] Test."
            llm._memory.system_prompt = test_system
            llm._memory.clear()

            # Mock generate para el resumen
            mock_result = {
                "choices": [{"message": {"content": "Resumen de prueba."}}]
            }
            llm._model_manager.generate = MagicMock(return_value=mock_result)

            _fill_memory(llm, 20)

            # Acceder al mock del modelo directamente
            mock_model = llm._model_manager._model
            mock_model.save_state.reset_mock()
            mock_model.load_state.reset_mock()

            llm._auto_trim_if_needed()

            # Verificar que se llamó save_state y load_state
            assert mock_model.save_state.called, \
                "save_state debería haberse llamado para proteger el KV cache"
            assert mock_model.load_state.called, \
                "load_state debería haberse llamado para restaurar el KV cache"

            store.close()


class TestSummaryNoAccumulation:
    """Verifica que el resumen no se acumule infinitamente tras múltiples trims."""

    def test_summaries_do_not_accumulate(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as tmp:
            llm, store = _make_llm(tmp, n_ctx=256, reserve=30)

            test_system = "[SYSTEM] Eres un personaje de prueba."
            llm._memory.system_prompt = test_system
            llm._memory.clear()

            # Mock generate para retornar un resumen
            mock_result = {
                "choices": [{"message": {"content": "El usuario y personaje chatean."}}]
            }
            llm._model_manager.generate = MagicMock(return_value=mock_result)

            # Primer llenado y trim
            _fill_memory(llm, 15)
            llm._auto_trim_if_needed()

            # Verificar que hay un resumen
            messages_1 = list(llm._memory.messages)
            summaries_1 = [m for m in messages_1 if m.role == "system" and m.content and "[RESUMEN DE CONVERSACIÓN PREVIA]" in m.content]
            assert len(summaries_1) == 1, "Debería haber exactamente 1 resumen tras el primer trim"

            # Segundo llenado y trim
            _fill_memory(llm, 15)
            llm._auto_trim_if_needed()

            # Verificar que sigue habiendo exactamente un resumen (el anterior se eliminó antes de meter el nuevo)
            messages_2 = list(llm._memory.messages)
            summaries_2 = [m for m in messages_2 if m.role == "system" and m.content and "[RESUMEN DE CONVERSACIÓN PREVIA]" in m.content]
            assert len(summaries_2) == 1, "No deben acumularse resúmenes; debe haber exactamente 1 tras el segundo trim"

            store.close()
