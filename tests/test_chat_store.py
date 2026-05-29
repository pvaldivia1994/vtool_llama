"""
Tests del SQLite event store + ContextBuilder + TokenCounter.
Solo los 5 escenarios más críticos.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from vtool_llama.db import ChatStore
from vtool_llama.utils import TokenCounter
from vtool_llama.engine.context_builder import ContextBuilder
from vtool_llama.engine.retrieval import RecentMessagesStrategy


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "test_chat.db")


@pytest.fixture
def store(db_path):
    s = ChatStore(db_path)
    yield s
    s.close()


@pytest.fixture
def conv(store):
    return store.get_or_create_conversation("test_char")


@pytest.fixture
def counter():
    return TokenCounter()


@pytest.fixture
def builder(store, counter):
    return ContextBuilder(
        store=store,
        token_counter=counter,
        strategies=[
            RecentMessagesStrategy(),
        ],
    )


# ======================================================================
# Test 1: ChatStore — mensajes lineales y path reconstruction
# ======================================================================

class TestChatStoreMessages:
    def test_add_and_path(self, store, conv):
        m1 = store.add_message(conv.id, "main", "user", "hola")
        m2 = store.add_message(conv.id, "main", "assistant", "cómo estás", parent_id=m1)
        m3 = store.add_message(conv.id, "main", "user", "bien", parent_id=m2)

        path = store.get_message_path(m3)
        assert len(path) == 3
        assert [m.role for m in path] == ["user", "assistant", "user"]
        assert [m.content for m in path] == ["hola", "cómo estás", "bien"]

    def test_message_index_auto(self, store, conv):
        ids = []
        for i in range(5):
            ids.append(store.add_message(conv.id, "main", "user", f"msg {i}"))
        msgs = store.get_branch_messages(conv.id, "main")
        assert [m.message_index for m in msgs] == [1, 2, 3, 4, 5]


# ======================================================================
# Test 2: ChatStore — branching y checkout no destructivo
# ======================================================================

class TestChatStoreBranching:
    def test_create_branch_and_checkout(self, store, conv):
        m1 = store.add_message(conv.id, "main", "user", "pregunta")
        m2 = store.add_message(conv.id, "main", "assistant", "respuesta A", parent_id=m1)

        branch_id = store.create_branch(conv.id, m1, label="Regenerado")
        m3 = store.add_message(conv.id, branch_id, "assistant", "respuesta B", parent_id=m1)

        # main tiene: m1 → m2
        # branch tiene: m1 → m3
        path_main = store.get_message_path(m2)
        path_branch = store.get_message_path(m3)
        assert len(path_main) == 2
        assert len(path_branch) == 2
        assert path_main[-1].content == "respuesta A"
        assert path_branch[-1].content == "respuesta B"

    def test_checkout_no_destructive(self, store, conv):
        store.add_message(conv.id, "main", "user", "a")
        m2 = store.add_message(conv.id, "main", "assistant", "original")
        store.set_active_leaf(conv.id, "main", m2)
        assert store.get_conversation(conv.id).active_leaf_message_id == m2


# ======================================================================
# Test 3: TokenCounter — conteo y truncate
# ======================================================================

class TestTokenCounter:
    def test_count_text_fallback(self, counter):
        assert counter.count_text("") == 0
        assert counter.count_text("hola") >= 1
        # 4 chars/token → "hola" = 4 chars → ~1 token
        assert counter.count_text("hola mundo") >= 2

    def test_truncate_to_budget(self, counter):
        msgs = [{"role": "user", "content": f"mensaje {i}"} for i in range(10)]
        # budget muy chico
        result = counter.truncate_to_budget(msgs, budget=2, preserve_last=1)
        assert len(result) <= len(msgs)
        assert result[-1]["content"] == "mensaje 9"  # preserve_last


# ======================================================================
# Test 4: ContextBuilder — orquestación básica
# ======================================================================

class TestContextBuilder:
    def test_build_empty(self, builder, conv):
        sections = builder.build(conv.id, "main", 0, 1000, system_prompt="test sys")
        assert any(s.type == "system" for s in sections)
        assert sections[0].type == "system"
        assert sections[0].messages[0]["content"] == "test sys"

    def test_build_with_messages(self, builder, store, conv):
        m1 = store.add_message(conv.id, "main", "user", "qué hora es")
        m2 = store.add_message(conv.id, "main", "assistant", "las 3", parent_id=m1)
        store.set_active_leaf(conv.id, "main", m2)

        sections = builder.build(conv.id, "main", m2, 5000, system_prompt="sys")
        types = [s.type for s in sections]
        assert "system" in types
        assert "history" in types
        history = [s for s in sections if s.type == "history"]
        assert len(history) == 1
        assert len(history[0].messages) == 2


# ======================================================================
# Test 5: ChatStore — soft delete y summaries
# ======================================================================

class TestChatStoreDeleteAndSummaries:
    def test_soft_delete(self, store, conv):
        m1 = store.add_message(conv.id, "main", "user", "borrame")
        path = store.get_message_path(m1)
        assert len(path) == 1
        assert path[0].status == "active"

        store.soft_delete_message(m1)
        path = store.get_message_path(m1)
        assert path[0].status == "deleted"

    def test_summaries(self, store, conv):
        store.add_summary(conv.id, "main", 1, 5, "primer resumen", reason="interval")
        s2 = store.add_summary(conv.id, "main", 6, 10, "segundo resumen", topic="tests", reason="manual")

        summaries = store.get_summaries(conv.id, "main")
        assert len(summaries) == 2

        loaded = store.get_summary_by_id(s2)
        assert loaded is not None
        assert loaded.summary == "segundo resumen"
        assert loaded.reason == "manual"

        assert store.delete_summary(s2) is True
        assert store.get_summary_by_id(s2) is None
