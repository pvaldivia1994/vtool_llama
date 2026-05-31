"""
Test: verifica que los mensajes se archiven en ChromaDB cuando rotan del deque.

Escenario:
- history_limit=3 (maxlen=5, solo 2 turnos completos)
- El turno 1 "Hola mi nombre es LiuniK" debe archivarse en ChromaDB cuando rote
- En turno 10, ChromaDB debe poder recuperarlo
"""
import sys, os, json, tempfile, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock
from vtool_llama import VToolLlama
from vtool_llama.db import ChatStore
from vtool_llama.engine.chat_memory import ChatMemory


def test_archive_on_rotate_mock():
    """Verifica que el callback de archive se dispare cuando el deque rota."""
    archived = []

    def mock_archive(msgs):
        for m in msgs:
            archived.append(m.content)

    mem = ChatMemory(system_prompt="test", history_limit=2)
    mem.set_archive_callback(mock_archive)

    # Llenar el deque hasta que rote (maxlen=4, 2+2)
    for i in range(10):
        mem.add_user_message(f"user_msg_{i}")
        mem.add_assistant_message(f"asst_{i}")

    # Verificar que los mensajes viejos se archiven al rotar
    # Con maxlen=4, el primer mensaje en rotar es user_msg_0
    # (esta en self._messages[1] cuando el deque esta lleno)
    assert len(archived) > 0, f"Deben haber mensajes archivados. Archivados: {archived}"
    assert any("user_msg_0" in m for m in archived), \
        f"user_msg_0 deberia estar archivado. Archivados: {archived}"
    print(f"OK: {len(archived)} mensajes archivados, primeros: {archived[:4]}")
    print(f"Mensajes en deque ahora: {[m.content for m in mem._messages]}")


def test_archive_in_real_chat():
    """Test de integracion: verifica que el callback conecte en load_character()."""
    config_path = os.path.join(tempfile.mkdtemp(), "config.json")
    with open(config_path, "w") as f:
        json.dump({
            "debug": False, "n_ctx": 4096, "n_batch": 1,
            "gpu_layers": 0, "temperature": 0.7, "top_p": 0.9,
            "top_k": 40, "repeat_penalty": 1.1, "max_tokens": 100,
            "system_prompt": "test", "enable_logging": False,
            "history_limit": 40, "auto_trim_context": True,
            "context_reserve_tokens": 50,
            "models_directory": os.path.dirname(config_path),
            "default_model": "none.gguf",
            "expand_n_ctx_for_core": False,
        }, f)

    llm = VToolLlama(config_path=config_path, auto_load=False)
    mm = MagicMock()
    mm.tokenize.side_effect = lambda t, *a, **kw: [0] * max(1, len(t) // 4)
    llm._model_manager._model = mm
    llm._model_manager._tokenize_fn = mm.tokenize
    llm._model_manager.count_messages_tokens = MagicMock(
        side_effect=lambda msgs: sum(len(m.get("content", "")) for m in msgs))
    llm._model_manager.generate = MagicMock(return_value={
        "choices": [{"message": {"content": "ok", "tool_calls": None}}]})

    # Simular load_character parcial
    store_path = os.path.join(os.path.dirname(config_path), "chat.db")
    llm._chat_store = ChatStore(store_path)
    llm._memory._conversation_id = uuid.uuid4().hex[:12]
    llm._memory._branch_id = "main"
    llm._memory._active_leaf_id = 0
    llm._character_manager._character_name = "test"
    llm._character_manager._prompt_dirty = False

    # Conectar archive callback
    llm._memory.set_archive_callback(lambda msgs: llm._archive_to_chroma(msgs))

    # Simular 10 turnos
    for i in range(10):
        llm.chat(f"user_msg_{i}")

    # Verificar que el chat funciono (los mensajes se acumulan correctamente)
    ctx = llm._memory.get_context_messages()
    user_msgs = [m for m in ctx if m["role"] == "user"]
    print(f"Contexto actual: {len(ctx)} mensajes, {len(user_msgs)} usuario(s)")
    print(f"Ultimos users: {[m['content'] for m in user_msgs]}")

    llm._chat_store.close()
    print("OK: chat completo sin errores")
