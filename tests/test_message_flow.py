"""
Test de flujo completo de mensajes en el pipeline real.

Reproduce el escenario del chat con Luna para verificar que todos
los mensajes se envíen al modelo en cada turno.
"""

from __future__ import annotations

import json
import os
import tempfile


def _make_llm(tmp, n_ctx=4096):
    """Crea un VToolLlama mockeado para pruebas de mensajes."""
    import json as j
    config_path = os.path.join(tmp, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        j.dump({
            "debug": False, "n_ctx": n_ctx, "n_batch": 1,
            "gpu_layers": 0, "temperature": 0.7, "top_p": 0.9,
            "top_k": 40, "repeat_penalty": 1.1, "max_tokens": 100,
            "system_prompt": "test", "enable_logging": False,
            "history_limit": 50, "auto_trim_context": True,
            "context_reserve_tokens": 50,
            "models_directory": tmp, "default_model": "none.gguf",
            "expand_n_ctx_for_core": False,
        }, f)

    from vtool_llama import VToolLlama
    from unittest.mock import MagicMock

    llm = VToolLlama(config_path=config_path, auto_load=False)

    # Mock del modelo
    mock_model = MagicMock()
    mock_model.tokenize.side_effect = lambda text, *a, **kw: [0] * max(1, len(text) // 4)
    mock_model.reset = MagicMock()
    llm._model_manager._model = mock_model
    llm._model_manager._tokenize_fn = mock_model.tokenize
    llm._model_manager.count_messages_tokens = MagicMock(
        side_effect=lambda messages: sum(len(m["content"]) for m in messages)
    )

    # Mock generate para que devuelva una respuesta
    def mock_generate(messages, **kwargs):
        return {
            "choices": [{"message": {"content": "respuesta mock", "tool_calls": None}}]
        }
    llm._model_manager.generate = MagicMock(side_effect=mock_generate)
    # Simular personaje cargado con store
    import uuid
    from vtool_llama.db import ChatStore
    llm._chat_store = ChatStore(os.path.join(tmp, "chat.db"))
    llm._memory._conversation_id = uuid.uuid4().hex[:12]
    llm._memory._branch_id = "main"
    llm._memory._active_leaf_id = 0
    llm._semantic_chroma = None
    llm._character_manager._character_name = "test"
    llm._character_manager._prompt_dirty = False

    return llm


def test_messages_acumulate_in_chat():
    """Verifica que chat() acumule mensajes correctamente turno a turno."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = _make_llm(tmp)

        # Secuencia exacta del chat con Luna
        prompts = [
            "Hola",
            "Mi nombre es LiuniK",
            "Como te llamas",
            "Tengo un perro llamado Pepe",
            "como me llamo",
            "cual es el nombre de mi perro",
        ]

        for i, prompt in enumerate(prompts):
            llm.chat(prompt)
            usage = llm.get_token_usage()
            # system(1) + (i+1) user + (i+1) assistant = 3 + i*2
            expected_msgs = 3 + i * 2
            assert usage["messages"] == expected_msgs, (
                f"Turno {i+1}: esperaba {expected_msgs} mensajes, "
                f"tengo {usage['messages']}. Historial: "
                f"{[m['content'][:30] for m in llm._memory.get_context_messages()]}"
            )

        # Verificación final: todos los mensajes están presentes
        ctx = llm._memory.get_context_messages()
        assert len(ctx) == 13, f"Esperaba 13 mensajes (system + 6 user + 6 assistant), tengo {len(ctx)}"

        if llm._chat_store:
            llm._chat_store.close()


def test_messages_acumulate_in_stream_chat():
    """Verifica que stream_chat() acumule mensajes correctamente."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = _make_llm(tmp)

        # Mock generate para streaming
        from unittest.mock import MagicMock

        def mock_stream(messages, **kwargs):
            class MockStream:
                def __init__(self):
                    self._done = False
                def __iter__(self):
                    return self
                def __next__(self):
                    if self._done:
                        raise StopIteration
                    self._done = True
                    return {"choices": [{"delta": {"content": "respuesta mock"}}]}
            return MockStream()

        llm._model_manager.generate = MagicMock(side_effect=mock_stream)

        prompts = [
            "Hola",
            "Mi nombre es LiuniK",
            "Como te llamas",
            "Tengo un perro llamado Pepe",
        ]

        for i, prompt in enumerate(prompts):
            # Consumir el stream
            for token in llm.stream_chat(prompt):
                pass
            usage = llm.get_token_usage()
            expected_msgs = 3 + i * 2
            assert usage["messages"] == expected_msgs, (
                f"Turno {i+1}: esperaba {expected_msgs} mensajes, "
                f"tengo {usage['messages']}"
            )

        # ctx mensajes tienen prefijo PLAYER: gracias a _get_inference_messages
        inf_msgs = llm._get_inference_messages()
        assert inf_msgs[1]["content"] == "PLAYER: Hola"
        assert inf_msgs[3]["content"] == "PLAYER: Mi nombre es LiuniK"
        assert "PLAYER: Tengo un perro llamado Pepe" in [m["content"] for m in inf_msgs], (
            "El mensaje 'Tengo un perro llamado Pepe' debe estar en el contexto"
        )

        llm._chat_store.close()


def test_get_inference_messages_includes_all():
    """Verifica que _get_inference_messages() devuelva todos los mensajes."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = _make_llm(tmp)

        llm._memory.add_user_message("Hola")
        llm._memory.add_assistant_message("respuesta 1")

        msgs = llm._get_inference_messages()
        assert len(msgs) == 3, f"Esperaba 3 mensajes, tengo {len(msgs)}"
        assert msgs[1]["content"] == "PLAYER: Hola"

        llm._memory.add_user_message("Mi nombre es LiuniK")
        llm._memory.add_assistant_message("respuesta 2")

        msgs = llm._get_inference_messages()
        assert len(msgs) == 5, f"Esperaba 5 mensajes, tengo {len(msgs)}"
        assert msgs[3]["content"] == "PLAYER: Mi nombre es LiuniK"

        if llm._chat_store:
            llm._chat_store.close()
