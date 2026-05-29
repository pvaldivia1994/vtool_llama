"""
Tests de integración: carga de personajes, chat, historial.
Requiere un modelo GGUF (skip si no hay modelo configurado).
Ejecuta solo los paths básicos sin modelo real.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from vtool_llama import VToolLlama


# ======================================================================
# Test 1: load_character falla con personaje inexistente
# ======================================================================

class TestCharacterLoading:
    def test_load_nonexistent_character(self):
        llm = VToolLlama(auto_load=False)
        with pytest.raises(ValueError, match="no encontrado"):
            llm.load_character("personaje_que_no_existe_xyz")
        assert llm.state_manager.loading is False

    def test_list_characters_empty(self):
        llm = VToolLlama(auto_load=False)
        chars = llm.list_characters()
        assert isinstance(chars, list)


# ======================================================================
# Test 2: Chat sin modelo cargado
# ======================================================================

class TestChatNoModel:
    def test_chat_raises_without_model(self):
        llm = VToolLlama(auto_load=False)
        with pytest.raises(Exception):
            llm.chat("hola")

    def test_memory_methods_without_model(self):
        llm = VToolLlama(auto_load=False)
        llm.clear_memory()
        mem = llm.get_memory()
        # Siempre queda el system prompt después de clear
        assert len(mem) == 1
        assert mem[0]["role"] == "system"


# ======================================================================
# Test 3: ChatStore se crea al cargar personaje (sin modelo)
# ======================================================================

class TestChatStoreOnLoad:
    def test_chat_store_created_on_load(self):
        llm = VToolLlama(auto_load=False)

        # Buscar default character
        chars = llm.list_characters()
        if not chars:
            pytest.skip("No hay personajes disponibles")

        name = chars[0]["name"] if isinstance(chars[0], dict) else chars[0]
        result = llm.load_character(name)
        assert result.success is True
        assert llm.chat_store is not None
        assert result.character_name == name

    def test_get_chat_history_empty(self):
        llm = VToolLlama(auto_load=False)
        chars = llm.list_characters()
        if not chars:
            pytest.skip("No hay personajes")

        name = chars[0]["name"] if isinstance(chars[0], dict) else chars[0]
        llm.load_character(name)
        history = llm.get_chat_history()
        assert isinstance(history, list)


# ======================================================================
# Test 4: Conversación persistence via ChatMemory + SQLite
# ======================================================================

class TestChatMemoryPersistence:
    def test_messages_persisted_to_sqlite(self):
        llm = VToolLlama(auto_load=False)
        chars = llm.list_characters()
        if not chars:
            pytest.skip("No hay personajes")

        name = chars[0]["name"] if isinstance(chars[0], dict) else chars[0]
        llm.load_character(name)

        # Simular conversación manualmente via ChatMemory
        uid = llm._memory.add_user_message("test message")
        assert uid is not None, "add_user_message debería retornar message_id"

        aid = llm._memory.add_assistant_message("test response")
        assert aid is not None, "add_assistant_message debería retornar message_id"

        # Verificar que persiste en SQLite
        path = llm.chat_store.get_message_path(aid)
        assert len(path) >= 2
        assert path[-2].content == "test message"
        assert path[-1].content == "test response"


    def test_messages_survive_reload(self):
        llm = VToolLlama(auto_load=False)
        chars = llm.list_characters()
        if not chars:
            pytest.skip("No hay personajes")

        name = chars[0]["name"] if isinstance(chars[0], dict) else chars[0]
        llm.load_character(name)

        llm._memory.add_user_message("mensaje antes de recargar")
        llm._memory.add_assistant_message("respuesta antes de recargar")

        # Recargar personaje
        llm.load_character(name)

        # El historial debería estar en SQLite (aunque el buffer RAM se limpia)
        store = llm.chat_store
        conv = store.get_conversation(llm._memory._conversation_id)
        msgs = store.get_branch_messages(conv.id, conv.active_branch_id, limit=100)
        contents = [(m.role, m.content) for m in msgs]
        assert ("user", "mensaje antes de recargar") in contents
        assert ("assistant", "respuesta antes de recargar") in contents


# ======================================================================
# Test 5: get_chat_history después de agregar mensajes
# ======================================================================

class TestGetChatHistory:
    def test_get_chat_history_returns_dicts(self):
        llm = VToolLlama(auto_load=False)
        chars = llm.list_characters()
        if not chars:
            pytest.skip("No hay personajes")

        name = chars[0]["name"] if isinstance(chars[0], dict) else chars[0]
        llm.load_character(name)

        llm._memory.add_user_message("user msg")
        llm._memory.add_assistant_message("assistant msg")

        history = llm.get_chat_history()
        assert len(history) >= 2
        for entry in history:
            assert "id" in entry
            assert "role" in entry
            assert "content" in entry
            assert "status" in entry
            assert "created_at" in entry

        roles = [e["role"] for e in history]
        assert "user" in roles
        assert "assistant" in roles
