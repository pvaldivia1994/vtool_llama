"""Tests del sistema de thinking v19: columna separada + optimización de contexto."""

from __future__ import annotations

import json
import os
import tempfile
import uuid


def _make_llm(tmp):
    """Crea un VToolLlama mockeado."""
    config_path = os.path.join(tmp, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({
            "debug": False, "n_ctx": 4096, "n_batch": 1,
            "gpu_layers": 0, "temperature": 0.7, "top_p": 0.9,
            "top_k": 40, "repeat_penalty": 1.1, "max_tokens": 100,
            "system_prompt": "test", "enable_logging": False,
            "history_limit": 50, "auto_trim_context": True,
            "context_reserve_tokens": 50,
            "models_directory": tmp, "default_model": "none.gguf",
            "expand_n_ctx_for_core": False,
            "disable_thinking": False,
            "show_thinking": True,
        }, f)

    from vtool_llama import VToolLlama
    from unittest.mock import MagicMock

    llm = VToolLlama(config_path=config_path, auto_load=False)

    mock_model = MagicMock()
    mock_model.tokenize.side_effect = lambda text, *a, **kw: [0] * max(1, len(text) // 4)
    mock_model.reset = MagicMock()
    llm._model_manager._model = mock_model
    llm._model_manager._tokenize_fn = mock_model.tokenize
    llm._model_manager.count_messages_tokens = MagicMock(
        side_effect=lambda messages: sum(len(m["content"]) for m in messages)
    )

    def mock_generate(messages, **kwargs):
        return {"choices": [{"message": {
            "content": "<think>\nRazonamiento interno\n</think>\nLuna: *Hola* ¿cómo estás?",
            "tool_calls": None,
        }}]}
    llm._model_manager.generate = MagicMock(side_effect=mock_generate)

    from vtool_llama.db import ChatStore
    store = ChatStore(os.path.join(tmp, "chat.db"))
    llm._chat_store = store
    llm._memory._conversation_id = uuid.uuid4().hex[:12]
    llm._memory._branch_id = "main"
    llm._memory._active_leaf_id = 0
    llm._memory._store = store
    llm._semantic_chroma = None
    llm._character_manager._character_name = "test"
    llm._character_manager._is_loaded = True

    return llm


def test_thinking_stored_separately_in_db():
    """chat_with_thinking guarda thinking en columna separada de SQLite."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = _make_llm(tmp)
        thinking, content = llm.chat_with_thinking("Hola")

        assert thinking == "Razonamiento interno"
        assert "Luna:" in content

        # Verificar que en SQLite el thinking está separado
        msgs = llm._chat_store.get_branch_messages(
            llm._memory._conversation_id, llm._memory._branch_id
        )
        assistant_msgs = [m for m in msgs if m.role == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].thinking == "Razonamiento interno"
        assert "Luna:" in assistant_msgs[0].content

        if llm._chat_store:
            llm._chat_store.close()


def test_thinking_does_not_show_when_show_thinking_false():
    """show_thinking=false guarda thinking en DB pero no lo retorna."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = _make_llm(tmp)
        llm._config.show_thinking = False

        thinking, content = llm.chat_with_thinking("Hola")

        assert thinking == ""  # No se muestra al usuario
        assert "Luna:" in content

        # Pero en DB el thinking SÍ está guardado
        msgs = llm._chat_store.get_branch_messages(
            llm._memory._conversation_id, llm._memory._branch_id
        )
        assistant_msgs = [m for m in msgs if m.role == "assistant"]
        assert assistant_msgs[0].thinking == "Razonamiento interno"

        if llm._chat_store:
            llm._chat_store.close()


def test_thinking_only_in_last_assistant_message():
    """get_context_messages solo incluye <think> en el último assistant."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = _make_llm(tmp)

        # Dos turnos con thinking
        llm.chat_with_thinking("Hola")
        llm.chat_with_thinking("¿Cómo estás?")

        ctx = llm._memory.get_context_messages()
        assistant_msgs = [m for m in ctx if m["role"] == "assistant"]

        # Debe haber 2 assistant messages
        assert len(assistant_msgs) == 2

        # El primero (histórico) NO debe tener <think>
        assert "<think>" not in assistant_msgs[0]["content"]

        # El segundo (último) DEBE tener <think>
        assert "<think>" in assistant_msgs[1]["content"]
        assert "Razonamiento interno" in assistant_msgs[1]["content"]

        if llm._chat_store:
            llm._chat_store.close()


def test_thinking_attached_to_last_assistant_not_last_message():
    """El <think> se adjunta al último assistant, no al último mensaje (que puede ser user)."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = _make_llm(tmp)
        llm._user_tag = "PLAYER"

        # Un turno con thinking
        llm.chat_with_thinking("Hola")

        # Agregar un mensaje user nuevo (simula el siguiente turno antes de generar)
        llm._memory.add_user_message("¿Cómo estás?")

        ctx = llm._memory.get_context_messages()
        assistant_msgs = [m for m in ctx if m["role"] == "assistant"]
        user_msgs = [m for m in ctx if m["role"] == "user"]

        # El último mensaje de la lista es user, NO assistant
        assert ctx[-1]["role"] == "user"

        # Pero el assistant message DEBE tener <think> (es el último assistant)
        assert len(assistant_msgs) >= 1
        assert "<think>" in assistant_msgs[-1]["content"]

        if llm._chat_store:
            llm._chat_store.close()


def test_thinking_column_in_chatmessage():
    """ChatMessage.thinking debe persistir al leer desde SQLite."""
    with tempfile.TemporaryDirectory() as tmp:
        store_path = os.path.join(tmp, "test.db")
        from vtool_llama.db import ChatStore
        store = ChatStore(store_path)

        conv = store.get_or_create_conversation("test")
        msg_id = store.add_message(
            conversation_id=conv.id,
            branch_id="main",
            role="assistant",
            content="Luna: *asiente*",
            thinking="Pensamiento interno",
        )
        path = store.get_message_path(msg_id)
        assert len(path) == 1
        assert path[0].thinking == "Pensamiento interno"
        assert path[0].content == "Luna: *asiente*"
        store.close()


def test_thinking_db_persistence_and_context_injection_end_to_end():
    """Valida end-to-end: thinking en DB + inyectado en contexto del último assistant.

    Escenario real: 2 turnos con thinking. Verifica que:
    1. El thinking se guarda en la columna messages.thinking de SQLite
    2. get_context_messages() inyecta <think> solo en el último assistant
    3. El content en DB NO tiene <think> (está separado)
    """
    with tempfile.TemporaryDirectory() as tmp:
        llm = _make_llm(tmp)

        # Turno 1: chat_with_thinking
        thinking1, content1 = llm.chat_with_thinking("Hola")
        assert thinking1 == "Razonamiento interno"
        assert content1 == "Luna: *Hola* ¿cómo estás?"

        # Turno 2: chat_with_thinking
        thinking2, content2 = llm.chat_with_thinking("¿Cómo estás?")
        assert thinking2 == "Razonamiento interno"
        assert content2 == "Luna: *Hola* ¿cómo estás?"

        # ── Validación 1: DB tiene thinking separado ──
        msgs = llm._chat_store.get_branch_messages(
            llm._memory._conversation_id, llm._memory._branch_id
        )
        assistant_msgs = [m for m in msgs if m.role == "assistant"]
        assert len(assistant_msgs) == 2

        # Ambos assistant messages tienen thinking en DB
        assert assistant_msgs[0].thinking == "Razonamiento interno"
        assert assistant_msgs[1].thinking == "Razonamiento interno"

        # El content en DB NO tiene <think> (está separado)
        assert "<think>" not in assistant_msgs[0].content
        assert "<think>" not in assistant_msgs[1].content

        # ── Validación 2: contexto inyecta <think> solo en el último ──
        ctx = llm._memory.get_context_messages()
        ctx_assistant = [m for m in ctx if m["role"] == "assistant"]
        assert len(ctx_assistant) == 2

        # Primer assistant (histórico) → sin <think>
        assert "<think>" not in ctx_assistant[0]["content"]
        # Segundo assistant (último) → con <think>
        assert "<think>" in ctx_assistant[1]["content"]
        assert "Razonamiento interno" in ctx_assistant[1]["content"]

        # ── Validación 3: raw SQLite tiene la columna thinking ──
        import sqlite3
        conn = sqlite3.connect(llm._chat_store._path)
        row = conn.execute(
            "SELECT thinking, content FROM messages WHERE role='assistant' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "Razonamiento interno"  # thinking column
        assert "<think>" not in row[1]  # content column, raw

        if llm._chat_store:
            llm._chat_store.close()
