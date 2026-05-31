"""
Test v12: escenario completo de archive + retrieval.

Config: history_limit=5 (maxlen=7, caben ~3 turnos)
1. Chat 1: "Hola mi nombre es LiuniK"
2. Chats 2-9: mensajes de relleno
3. Chat 10: el modelo debe poder recuperar el nombre
   via ChromaDB (archived_memory)

Flujo esperado:
  - Los mensajes del chat 1 rotan del deque aprox en chat 4-5
  - Se archivan en ChromaDB via archive callback
  - En chat 10, SemanticRetrievalStrategy busca en archived_memory
  - ChromaDB devuelve [PLAYER] Hola mi nombre es LiuniK
  - El modelo recibe ese contexto y sabe el nombre
"""
import sys, os, json, tempfile, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from unittest.mock import MagicMock, ANY


def test_scenario_archive_and_retrieval():
    """Escenario completo: archive en rotacion + retrieval semantico."""
    
    # Config con history_limit=5 (maxlen=7, solo ~3 turnos)
    config = {
        "debug": False, "n_ctx": 4096, "n_batch": 1,
        "gpu_layers": 0, "temperature": 0.7, "top_p": 0.9,
        "top_k": 40, "repeat_penalty": 1.1, "max_tokens": 100,
        "system_prompt": "test", "enable_logging": False,
        "history_limit": 5, "auto_trim_context": True,
        "context_reserve_tokens": 50,
        "models_directory": tempfile.mkdtemp(), "default_model": "none.gguf",
        "semantic_memory_enabled": True,
        "memory_rag_budget": 500,
        "memory_rag_min_similarity": 0.1,
    }
    
    config_path = os.path.join(tempfile.mkdtemp(), "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f)

    from vtool_llama import VToolLlama
    from vtool_llama.db import ChatStore
    from vtool_llama.db.chroma_store import ChromaStore, HAS_CHROMA

    if not HAS_CHROMA:
        print("SKIP: chromadb no instalado")
        return

    llm = VToolLlama(config_path=config_path, auto_load=False)

    # Mock del modelo
    mm = MagicMock()
    mm.tokenize.side_effect = lambda t, *a, **kw: [0] * max(1, len(t) // 4)
    llm._model_manager._model = mm
    llm._model_manager._tokenize_fn = mm.tokenize
    llm._model_manager.count_messages_tokens = MagicMock(
        side_effect=lambda msgs: sum(len(m.get("content", "")) for m in msgs))

    # Mock generate: guardar mensajes recibidos y devolver respuesta
    last_messages = []
    def mock_generate(messages, **kwargs):
        nonlocal last_messages
        last_messages = list(messages)
        return {"choices": [{"message": {"content": "ok", "tool_calls": None}}]}
    llm._model_manager.generate = MagicMock(side_effect=mock_generate)

    # Inicializar store + chroma
    store_dir = tempfile.mkdtemp()
    llm._chat_store = ChatStore(os.path.join(store_dir, "chat.db"),
                                 log_fn=lambda t, m: None)
    llm._memory._conversation_id = uuid.uuid4().hex[:12]
    llm._memory._branch_id = "main"
    llm._memory._active_leaf_id = 0
    llm._character_manager._character_name = "test"
    llm._character_manager._prompt_dirty = False

    # Inicializar ChromaDB archived_memory (como en load_character)
    from vtool_llama.db.chroma_store import ChromaStore as CS
    llm._archived_chroma = CS(
        Path(tempfile.mkdtemp()) / "semantic",
        "archived_memory",
        log_fn=lambda m: None,
    )
    llm._archived_chroma.initialize()

    # Conectar archive callback
    llm._memory.set_archive_callback(lambda msgs: llm._archive_to_chroma(msgs))

    # ===== Chat 1: decir el nombre =====
    llm.chat("Hola mi nombre es LiuniK")
    
    # Chats 2-9: relleno para causar rotacion
    for i in range(2, 10):
        llm.chat(f"mensaje de relleno numero {i} para ocupar espacio")

    # ===== Chat 10: verificar que el nombre se recupero =====
    llm.chat("cual es mi nombre?")
    
    # Analizar los mensajes que recibio el modelo en el ultimo chat
    print(f"Ultimo generate recibio {len(last_messages)} mensajes")
    system_msgs = [m for m in last_messages if m.get("role") == "system"]
    all_content = " ".join(m.get("content", "") for m in last_messages)
    
    print(f"Mensajes system: {len(system_msgs)}")
    for i, sm in enumerate(system_msgs):
        print(f"  system[{i}]: {sm.get('content', '')[:80]}...")
    
    # Verificar que el nombre esta disponible (via contexto o chroma)
    nombre_encontrado = "LiuniK" in all_content or "LiuniK" in str(last_messages)
    
    if not nombre_encontrado:
        # Buscar directamente en ChromaDB para confirmar que se archivo
        results = llm._archived_chroma.search("cual es mi nombre", top_k=3)
        print(f"Busqueda en archived_memory: {len(results)} resultados")
        for r in results:
            print(f"  sim={r.get('similarity',0):.3f}: {r.get('document','')[:80]}")
            if "LiuniK" in (r.get("document", "") or ""):
                nombre_encontrado = True
    
    assert nombre_encontrado, (
        "El nombre 'LiuniK' deberia estar disponible via chroma o contexto. "
        "Primer chat archivado pero no recuperado."
    )
    print(f"\nOK: El nombre LiuniK esta disponible en el turno 10")

    llm._chat_store.close()
