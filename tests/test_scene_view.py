"""
Tests para el comando /scene_view.
Verifica que construya correctamente el contexto desde SQLite.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from vtool_llama import VToolLlama
from vtool_llama.db import ChatStore


def _setup_chat_history(store: ChatStore, conv_id: str) -> int:
    m1 = store.add_message(conv_id, "main", "user", "Hay un perro grande en la entrada")
    m2 = store.add_message(conv_id, "main", "assistant", "El perro mueve la cola", parent_id=m1)
    m3 = store.add_message(conv_id, "main", "user", "El perro se fue", parent_id=m2)
    m4 = store.add_message(conv_id, "main", "assistant", "Se escuchan pasos", parent_id=m3)
    m5 = store.add_message(conv_id, "main", "user", "Ahora hay un gato negro en el tejado", parent_id=m4)
    m6 = store.add_message(conv_id, "main", "assistant", "El gato nos mira", parent_id=m5)
    store.set_active_leaf(conv_id, "main", m6)
    return m6


@pytest.fixture
def llm():
    return VToolLlama(auto_load=False)


class TestSceneViewNoModel:
    def test_scene_view_without_model(self, llm):
        result = llm._cmd_scene_view("")
        assert "No hay modelo" in result


class TestSceneViewNoHistory:
    def test_scene_view_without_history(self, llm):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "chat.db")
            store = ChatStore(db_path)
            conv = store.get_or_create_conversation("test")

            llm._model_manager._model = object()
            llm._chat_store = store
            llm._memory._conversation_id = conv.id
            llm._memory._branch_id = "main"
            llm._memory._active_leaf_id = 0

            result = llm._cmd_scene_view("")
            assert "No hay historial" in result

            store.close()


class TestSceneViewContextBuilder:
    def test_get_chat_history_returns_all_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "chat.db")
            store = ChatStore(db_path)
            conv = store.get_or_create_conversation("test")

            leaf = _setup_chat_history(store, conv.id)

            # Simular VToolLlama con store
            llm = VToolLlama(auto_load=False)
            llm._chat_store = store
            llm._memory._conversation_id = conv.id
            llm._memory._branch_id = "main"
            llm._memory._active_leaf_id = leaf

            history = llm.get_chat_history(limit=10)
            assert len(history) == 6
            assert history[0]["role"] == "user"
            assert "perro" in history[0]["content"]
            assert history[-1]["role"] == "assistant"
            assert "gato" in history[-1]["content"]

            store.close()

    def test_messages_are_in_cronological_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "chat.db")
            store = ChatStore(db_path)
            conv = store.get_or_create_conversation("test")
            _setup_chat_history(store, conv.id)

            msgs = store.get_branch_messages(conv.id, "main", limit=10)
            assert len(msgs) == 6
            contents = [m.content for m in msgs]
            idx_perro = next(i for i, c in enumerate(contents) if "perro grande" in c)
            idx_gato = next(i for i, c in enumerate(contents) if "gato negro" in c)
            assert idx_gato > idx_perro

            store.close()
