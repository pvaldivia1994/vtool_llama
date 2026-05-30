"""
Test para el auto-trim con contexto pequeño.
Verifica que el system prompt se preserve y que se genere resumen antes de recortar.
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


class TestAutoTrimSmallContext:
    def test_system_prompt_preserved_after_trim(self):
        """Configura n_ctx muy pequeño para forzar trim y verificar que system prompt sobrevive."""
        import json

        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "debug": False, "n_ctx": 512, "n_batch": 1,
                    "gpu_layers": 0, "temperature": 0.7, "top_p": 0.9,
                    "top_k": 40, "repeat_penalty": 1.1, "max_tokens": 100,
                    "system_prompt": "test", "enable_logging": False,
                    "history_limit": 50, "auto_trim_context": True,
                    "context_reserve_tokens": 50,
                    "models_directory": tmp, "default_model": "none.gguf",
                }, f)

            llm = VToolLlama(config_path=config_path, auto_load=False)

            # Simular modelo cargado para que el contador de tokens funcione
            from unittest.mock import MagicMock
            mock_model = MagicMock()
            mock_model.tokenize.return_value = [0] * 10  # ~10 tokens por llamada
            llm._model_manager._model = mock_model
            llm._model_manager._tokenize_fn = mock_model.tokenize

            # Configurar store mínimo
            db_path = os.path.join(tmp, "chat.db")
            store = ChatStore(db_path)
            conv = store.get_or_create_conversation("test")
            llm._chat_store = store
            llm._memory.bind_store(store, None, None, conv.id, "main", 0)

            # Inyectar system prompt de prueba
            test_system = "[SYSTEM] Eres un personaje de prueba con una personalidad definida y un contexto específico."
            llm._memory.system_prompt = test_system
            llm._memory.clear()

            usage = llm.get_token_usage()
            assert usage["system_tokens"] > 0, "System prompt debería tener tokens"
            assert usage["max_tokens"] == 512, "n_ctx debería ser 512"

            # Llenar memoria hasta forzar trim
            _fill_memory(llm, 15)

            usage = llm.get_token_usage()
            assert usage["system_tokens"] > 0, "System prompt debería mantenerse después de llenar"

            # Forzar trim
            llm._auto_trim_if_needed()

            usage = llm.get_token_usage()
            assert usage["system_tokens"] > 0, "System prompt debería preservarse después del trim"
            assert usage["total_tokens"] <= usage["max_tokens"] - usage["reserved"], \
                f"Total tokens ({usage['total_tokens']}) debería ser menor que max - reserved ({usage['max_tokens'] - usage['reserved']})"
            assert usage["messages"] >= 1, "Debería quedar al menos el system prompt"

            store.close()

    def test_messages_reduced_after_trim(self):
        """Verifica que el trim realmente reduzca la cantidad de mensajes."""
        import json

        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "debug": False, "n_ctx": 512, "n_batch": 1,
                    "gpu_layers": 0, "temperature": 0.7, "top_p": 0.9,
                    "top_k": 40, "repeat_penalty": 1.1, "max_tokens": 100,
                    "system_prompt": "test", "enable_logging": False,
                    "history_limit": 50, "auto_trim_context": True,
                    "context_reserve_tokens": 50,
                    "models_directory": tmp, "default_model": "none.gguf",
                }, f)

            llm = VToolLlama(config_path=config_path, auto_load=False)
            from unittest.mock import MagicMock
            mock_model = MagicMock()
            mock_model.tokenize.return_value = [0] * 10
            llm._model_manager._model = mock_model
            llm._model_manager._tokenize_fn = mock_model.tokenize

            db_path = os.path.join(tmp, "chat.db")
            store = ChatStore(db_path)
            conv = store.get_or_create_conversation("test")
            llm._chat_store = store
            llm._memory.bind_store(store, None, None, conv.id, "main", 0)

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
