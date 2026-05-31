"""Tests del sistema inline v15: #, [], :, * en mensajes del usuario."""

from __future__ import annotations

import json
import os
import uuid

from unittest.mock import MagicMock
from types import SimpleNamespace


# ──────────────────────────────────────────────────────────────
# Helper: crear VToolLlama mockeado
# ──────────────────────────────────────────────────────────────

def _make_llm(tmp_path):
    """Crea un VToolLlama con mocks para pruebas de pipeline inline."""
    config_path = os.path.join(tmp_path, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({
            "debug": False, "n_ctx": 4096, "n_batch": 1,
            "gpu_layers": 0, "temperature": 0.7, "top_p": 0.9,
            "top_k": 40, "repeat_penalty": 1.1, "max_tokens": 100,
            "system_prompt": "test", "enable_logging": False,
            "history_limit": 50, "auto_trim_context": True,
            "context_reserve_tokens": 50,
            "models_directory": str(tmp_path), "default_model": "none.gguf",
            "expand_n_ctx_for_core": False,
        }, f)

    from vtool_llama import VToolLlama

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
        return {"choices": [{"message": {"content": "respuesta mock", "tool_calls": None}}]}
    llm._model_manager.generate = MagicMock(side_effect=mock_generate)

    from vtool_llama.db import ChatStore
    store = ChatStore(os.path.join(tmp_path, "chat.db"))
    llm._chat_store = store
    llm._memory._conversation_id = uuid.uuid4().hex[:12]
    llm._memory._branch_id = "main"
    llm._memory._active_leaf_id = 0
    # Vincular store a ChatMemory para que add_user_message persista en SQLite
    llm._memory._store = store
    llm._semantic_chroma = None
    llm._character_manager._character_name = "test"
    llm._character_manager._is_loaded = True

    import tempfile
    char_dir = tempfile.mkdtemp()
    llm._character_manager._char_dir = char_dir

    return llm


# ──────────────────────────────────────────────────────────────
# Tests de patrones regex
# ──────────────────────────────────────────────────────────────

def test_hash_pattern():
    from vtool_llama.engine.inline import HASH_PATTERN

    m = HASH_PATTERN.search("#time noche#")
    assert m and m.group(1) == "time" and m.group(2) == "noche"

    m = HASH_PATTERN.search("#mem#")
    assert m and m.group(1) == "mem" and m.group(2) is None

    m = HASH_PATTERN.search("#char estoy muy triste#")
    assert m and m.group(1) == "char" and m.group(2) == "estoy muy triste"

    m = HASH_PATTERN.search("#world hay estalactitas#")
    assert m and m.group(1) == "world" and m.group(2) == "hay estalactitas"

    # Sin cierre → no match
    assert HASH_PATTERN.search("#time") is None

    # Solo # sin comando
    assert HASH_PATTERN.search("solo # no cierra") is None


def test_scene_pattern():
    from vtool_llama.engine.inline import SCENE_PATTERN

    # Multi-word → match scene
    assert SCENE_PATTERN.search("[CUECA OSCURA]")
    assert SCENE_PATTERN.search("[HAY UNA TRAMPA EN EL PISO]")
    assert SCENE_PATTERN.search("[esto es un texto largo]")

    # Single-word → NO match (es personaje)
    assert not SCENE_PATTERN.search("[LUNA]")
    assert not SCENE_PATTERN.search("[ROBERTO]")
    assert not SCENE_PATTERN.search("[USER]")


def test_thought_pattern():
    from vtool_llama.engine.inline import THOUGHT_PATTERN

    m = THOUGHT_PATTERN.search(":esto es peligroso:")
    assert m and m.group(1) == "esto es peligroso"

    # Un sólo : no match
    assert THOUGHT_PATTERN.search("esto: no") is None


def test_action_pattern():
    from vtool_llama.engine.inline import ACTION_PATTERN

    m = ACTION_PATTERN.search("*abre la puerta*")
    assert m and m.group(1) == "abre la puerta"

    # Sin cierre
    assert ACTION_PATTERN.search("*abre") is None


# ──────────────────────────────────────────────────────────────
# Tests de InlineProcessor
# ──────────────────────────────────────────────────────────────

def _make_mock_llm():
    """Mock liviano para InlineProcessor (sin base de datos)."""
    from types import SimpleNamespace
    llm = SimpleNamespace()
    llm._chat_store = None
    llm._memory = SimpleNamespace()
    llm._memory._conversation_id = None
    llm._log_debug = lambda *a: None
    llm._log_warning = lambda *a: None
    llm._log_info = lambda *a: None
    llm._char_thought_buffer = []
    return llm


def test_extract_hash_registered():
    from vtool_llama.engine.inline import InlineProcessor
    p = InlineProcessor()
    calls = []

    p.register("test", lambda args, llm: calls.append(args), "")

    llm = _make_mock_llm()
    result = p._extract_hash("Hola #test mundo# como estas", llm)
    assert calls == ["mundo"]
    assert "Hola" in result
    assert "como estas" in result[-1]


def test_extract_hash_unregistered_preserved():
    from vtool_llama.engine.inline import InlineProcessor
    p = InlineProcessor()
    llm = _make_mock_llm()

    result = p._extract_hash("texto #unknown arg# mas", llm)
    # El texto con #unknown# debe preservarse literal
    combined = " ".join(result)
    assert "#unknown" in combined


def test_extract_hash_multiple_commands():
    from vtool_llama.engine.inline import InlineProcessor
    p = InlineProcessor()
    calls = []
    p.register("a", lambda a, l: calls.append(("a", a)), "")
    p.register("b", lambda a, l: calls.append(("b", a)), "")

    llm = _make_mock_llm()
    result = p._extract_hash("#a uno# medio #b dos# fin", llm)
    assert calls == [("a", "uno"), ("b", "dos")]
    assert len(result) == 2
    assert "medio" in result[0]
    assert "fin" in result[-1]


def test_extract_scene():
    from vtool_llama.engine.inline import InlineProcessor
    from vtool_llama.db import ChatStore
    import tempfile, uuid

    p = InlineProcessor()

    # Mock con store
    store_path = os.path.join(tempfile.mkdtemp(), "test.db")
    store = ChatStore(store_path)
    conv_id = uuid.uuid4().hex[:12]

    llm = _make_mock_llm()
    llm._chat_store = store
    llm._memory._conversation_id = conv_id
    llm._memory._branch_id = "main"

    result = p._extract_scene(["algo [UNA CUEVA OSCURA] texto"], llm)
    assert "algo" in result[0]
    assert "texto" in result[0]
    assert "[UNA CUEVA OSCURA]" not in result[0]

    # Verificar que se guardó en ContextInjector
    from vtool_llama.orquestador import ContextInjector
    inj = ContextInjector(store, conv_id, "main")
    active = inj.get_active_contexts()
    assert any("UNA CUEVA OSCURA" in ctx for ctx in active)


def test_tag_segment():
    from vtool_llama.engine.inline import InlineProcessor
    p = InlineProcessor()

    # Acción
    tag, content = p._tag_segment("*abre la puerta*")
    assert tag == "DOES"
    assert "*abre la puerta*" in content

    # Pensamiento (limpia :)
    tag, content = p._tag_segment(":esto es peligroso:")
    assert tag == "THINKS"
    assert content == "esto es peligroso"

    # Texto normal
    tag, content = p._tag_segment("Hola como estas")
    assert tag == "SAYS"
    assert content == "Hola como estas"

    # Mixto: acción + texto → DOES
    tag, content = p._tag_segment("*mira* y dice hola")
    assert tag == "DOES"


def test_build_messages():
    from vtool_llama.engine.inline import InlineProcessor
    p = InlineProcessor()

    msgs = p._build_messages([
        "*Entro sigilosamente*",
        "hay alguien ahi",
        ":esto es peligroso:",
    ])

    assert len(msgs) == 3
    assert msgs[0]["tag"] == "DOES"
    assert msgs[1]["tag"] == "SAYS"
    assert msgs[2]["tag"] == "THINKS"
    assert msgs[2]["content"] == "esto es peligroso"


# ──────────────────────────────────────────────────────────────
# Tests de pipeline integrado
# ──────────────────────────────────────────────────────────────

def _check_context_summary(llm, expected: str) -> bool:
    """Busca 'expected' en summaries SQLite de contexto."""
    summaries = llm._chat_store.get_summaries(
        llm._memory._conversation_id, llm._memory._branch_id, limit=100
    )
    return any(expected in s.summary for s in summaries if s.reason.startswith("ctx_"))


def test_chat_with_time_command(tmp_path):
    """#time desc → debe inyectar [CONTEXT][TIME] via ContextInjector."""
    llm = _make_llm(tmp_path)
    llm.chat("Te espero #time pasan 2 horas# estoy cansado")
    assert _check_context_summary(llm, "pasan 2 horas")


def test_chat_with_scene_command(tmp_path):
    """#scene desc → debe reemplazar la escena via save_scene."""
    llm = _make_llm(tmp_path)
    llm.chat("#scene estamos en un cafe#")
    assert _check_context_summary(llm, "estamos en un cafe")


def test_chat_with_world_command(tmp_path):
    """#world desc → debe inyectar [CONTEXT][WORLD]."""
    llm = _make_llm(tmp_path)
    llm.chat("mira #world hay estalactitas# cuidado")
    assert _check_context_summary(llm, "hay estalactitas")


def test_chat_with_char_thought(tmp_path):
    """#char pensamiento → buffer se inyecta como [ASSISTANT=X][THINKS] system msg."""
    llm = _make_llm(tmp_path)
    # Track buffer antes de que chat() lo inyecte y limpie
    original_inject = llm._inject_char_thoughts
    injected_thoughts = []

    def tracking_inject(messages):
        for name, thought in llm._char_thought_buffer:
            injected_thoughts.append((name, thought))
        original_inject(messages)

    llm._inject_char_thoughts = tracking_inject
    llm.chat("Hola #char estoy muy triste# que hago?")

    assert len(injected_thoughts) == 1
    assert injected_thoughts[0] == ("Test", "estoy muy triste")
    assert llm._char_thought_buffer is not None


def test_chat_with_action_thought_speak(tmp_path):
    """*acción*, :pensamiento:, y texto normal en un mensaje."""
    llm = _make_llm(tmp_path)

    # Verificar mensajes guardados en SQLite
    llm.chat("*Entro sigilosamente* :esto es malo: hay alguien ahi")

    msgs = llm._chat_store.get_branch_messages(
        llm._memory._conversation_id, llm._memory._branch_id
    )
    contents = [m.content for m in msgs if m.role == "user"]

    assert any("[DOES]" in c and "Entro sigilosamente" in c for c in contents)
    assert any("[THINKS]" in c and "esto es malo" in c for c in contents)
    assert any("[SAYS]" in c and "hay alguien ahi" in c for c in contents)


def test_chat_with_bare_scene_context(tmp_path):
    """[TEXTO LARGO] → scene context via _extract_inline_context."""
    llm = _make_llm(tmp_path)
    llm.chat("cuidado [HAY UNA TRAMPA EN EL PISO] no te muevas")
    assert _check_context_summary(llm, "HAY UNA TRAMPA EN EL PISO")


def test_chat_multi_character(tmp_path):
    """[ROBERTO] single-word → multi-personaje, no scene."""
    llm = _make_llm(tmp_path)
    llm._user_tag = "PLAYER"
    llm.chat("[ROBERTO] Hola que tal")

    from vtool_llama.orquestador import ContextInjector
    inj = ContextInjector(llm._chat_store, llm._memory._conversation_id, llm._memory._branch_id)

    # No debe guardarse como scene (single-word)
    active = inj.get_active_contexts()
    assert not any("ROBERTO" in ctx for ctx in active)

    # Debe guardarse como mensaje user con tag [ROBERTO]
    msgs = llm._chat_store.get_branch_messages(
        llm._memory._conversation_id, llm._memory._branch_id
    )
    contents = [m.content for m in msgs if m.role == "user"]
    # El tag se aplica en _get_inference_messages, no en add_user_message
    # Pero el mensaje debe existir
    assert any("Hola que tal" in c for c in contents)


def test_user_tag_respected(tmp_path):
    """_user_tag debe usarse en vez de [USER] hardcodeado, formato [USER=LIU]."""
    llm = _make_llm(tmp_path)
    llm._user_tag = "LIU"
    llm.chat("Hola")

    # Verificar en _get_inference_messages
    messages = llm._get_inference_messages()
    user_msgs = [m for m in messages if m.get("role") == "user"]
    assert any("[USER=LIU]" in m["content"] for m in user_msgs)


def test_hash_mem_command(tmp_path):
    """#mem texto → debe guardar memoria persistente."""
    llm = _make_llm(tmp_path)
    llm.chat("recuerda #mem nombre: Juan# ok?")

    memories = llm._character_manager.memories
    assert any("nombre: Juan" in m.content for m in memories)


def test_mixed_all_commands(tmp_path):
    """Todos los comandos inline en un solo mensaje."""
    llm = _make_llm(tmp_path)
    llm._character_manager._character_name = "Luna"

    prompt = (
        "*Entro sigilosamente* [CUECA OSCURA] hay alguien #world hay estalactitas# "
        ":esto es peligroso: #char esta nerviosa# *Miro alrededor*"
    )

    llm.chat(prompt)

    # Scene inyectado
    assert _check_context_summary(llm, "CUECA OSCURA")
    # World inyectado
    assert _check_context_summary(llm, "hay estalactitas")

    # Mensajes en SQLite deben tener los tags correctos
    msgs = llm._chat_store.get_branch_messages(
        llm._memory._conversation_id, llm._memory._branch_id
    )
    contents = [m.content for m in msgs if m.role == "user"]
    assert any("[DOES]" in c and "Entro sigilosamente" in c for c in contents)
    assert any("[SAYS]" in c and "hay alguien" in c for c in contents)
    assert any("[THINKS]" in c and "esto es peligroso" in c for c in contents)
    assert any("[DOES]" in c and "Miro alrededor" in c for c in contents)


def test_time_parentheses(tmp_path):
    """(texto multi-palabra) → debe inyectar [CONTEXT][TIME]."""
    llm = _make_llm(tmp_path)
    llm.chat("Hola (pasan dos horas) que tal")
    assert _check_context_summary(llm, "pasan dos horas")


def test_time_parentheses_single_word_not_consumed(tmp_path):
    """(palabra) single-word NO debe consumirse (solo multi-word)."""
    llm = _make_llm(tmp_path)
    llm.chat("Hola (hola) que tal")
    assert not _check_context_summary(llm, "hola")


def test_empty_scene_only(tmp_path):
    """Solo [SCENE] sin texto adicional → contexto inyectado, sin user msg vacío."""
    llm = _make_llm(tmp_path)
    llm.chat("[SOLO ESCENA]")
    assert _check_context_summary(llm, "SOLO ESCENA")


def test_hash_unregistered_preserved_in_chat(tmp_path):
    """#unknown debe preservarse como texto literal en la respuesta."""
    llm = _make_llm(tmp_path)
    result = llm.chat("esto es #foo desconocido# texto")

    # El mensaje debe contener #foo desconocido# literal
    msgs = llm._chat_store.get_branch_messages(
        llm._memory._conversation_id, llm._memory._branch_id
    )
    # Buscar en todos los mensajes
    all_content = " ".join(m.content for m in msgs)
    assert "#foo desconocido#" in all_content or "#foo" in all_content


# ──────────────────────────────────────────────────────────────
# Tests de _get_inference_messages
# ──────────────────────────────────────────────────────────────

def test_get_inference_messages_uses_user_tag(tmp_path):
    """_get_inference_messages debe usar _user_tag, no [USER] hardcodeado."""
    llm = _make_llm(tmp_path)
    llm._user_tag = "LIU"
    llm._memory.add_user_message("Hola mundo")

    messages = llm._get_inference_messages()
    user_msgs = [m for m in messages if m.get("role") == "user"]
    assert any("[USER=LIU]" in m["content"] for m in user_msgs)


def test_get_inference_messages_multichar(tmp_path):
    """[ROBERTO] en contenido → debe etiquetar como [USER=Roberto][SAYS]."""
    llm = _make_llm(tmp_path)
    llm._user_tag = "PLAYER"
    llm._memory.add_user_message("[ROBERTO] Hola que tal")

    messages = llm._get_inference_messages()
    user_msgs = [m for m in messages if m.get("role") == "user"]
    assert any("[USER=Roberto][SAYS]" in m["content"] for m in user_msgs)


def test_get_inference_messages_pretagged_skipped(tmp_path):
    """Mensajes ya pre-tagueados por InlineProcessor no se duplican."""
    llm = _make_llm(tmp_path)
    llm._user_tag = "LIU"
    llm._memory.add_user_message("[USER=LIU][DOES] *accion*")

    messages = llm._get_inference_messages()
    user_msgs = [m for m in messages if m.get("role") == "user"]
    # No debe tener DOBLE tag
    for m in user_msgs:
        assert m["content"].count("[USER=LIU]") <= 1
