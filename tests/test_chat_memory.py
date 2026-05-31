"""
Tests de ChatMemory: retención de contexto conversacional.

Verifica que los mensajes se preserven entre turnos,
que el system prompt nunca se pierda, y que get_context_messages()
devuelva el historial completo.
"""

from __future__ import annotations

from vtool_llama.engine.chat_memory import ChatMemory


def _make_memory(history_limit: int = 50) -> ChatMemory:
    return ChatMemory(system_prompt="[SYSTEM] Eres un personaje de prueba.", history_limit=history_limit)


# ======================================================================
# Retención básica
# ======================================================================


def test_messages_retained_after_multiple_turns():
    """Verifica que los mensajes se acumulen correctamente turno a turno."""
    mem = _make_memory()

    mem.add_user_message("hola")
    mem.add_assistant_message("¿Qué quieres?")

    assert len(mem.messages) == 3  # system + user + assistant
    assert mem.messages[0].role == "system"
    assert mem.messages[1].role == "user"
    assert mem.messages[1].content == "hola"
    assert mem.messages[2].role == "assistant"


def test_conversation_flow_preserved():
    """Simula una conversación de 4 turnos y verifica que todo el historial esté presente."""
    mem = _make_memory()

    # Turno 1
    mem.add_user_message("hola")
    mem.add_assistant_message("¿Q-qué quieres, Capataz?")

    # Turno 2
    mem.add_user_message("mi nombre es LiuniK")
    mem.add_assistant_message("¿Q-qué quieres, LiuniK? Mi nombre es Luna.")

    # Turno 3
    mem.add_user_message("un placer conocerte Luna")
    mem.add_assistant_message("Un placer... Mi nombre es Luna.")

    # Turno 4 — preguntar el nombre que ya se dijo en turno 2
    mem.add_user_message("y yo como me llamo?")
    mem.add_assistant_message("¿Y cómo te llamas?")

    # Verificar que los 4 turnos están completos (9 mensajes: system + 4 user + 4 assistant)
    ctx = mem.get_context_messages()
    assert len(ctx) == 9, f"Esperaba 9 mensajes, tengo {len(ctx)}"

    # Verificar que el primer mensaje user "hola" sigue presente
    assert ctx[1]["content"] == "hola"
    assert ctx[1]["role"] == "user"

    # Verificar que el nombre "LiuniK" dicho en turno 2 sigue en el contexto
    user_messages = [m for m in ctx if m["role"] == "user"]
    names = [m["content"] for m in user_messages]
    assert any("LiuniK" in c for c in names), "LiuniK debería estar en algún mensaje user"
    assert any("Luna" in c for c in [m["content"] for m in ctx if m["role"] == "assistant"])

    # Verificar que el system prompt está intacto
    assert ctx[0]["role"] == "system"
    assert "personaje de prueba" in ctx[0]["content"]


# ======================================================================
# System prompt preservation
# ======================================================================


def test_system_prompt_never_lost():
    """Verifica que el system prompt nunca se pierda aunque el deque rote."""
    mem = _make_memory(history_limit=5)  # deque pequeño para forzar rotación

    # Llenar hasta rotar
    for i in range(20):
        mem.add_user_message(f"mensaje {i}")
        mem.add_assistant_message(f"respuesta {i}")

    ctx = mem.get_context_messages()
    # El system prompt siempre debe estar primero
    assert ctx[0]["role"] == "system"
    assert "personaje de prueba" in ctx[0]["content"]


def test_context_messages_excludes_empty():
    """Verifica que get_context_messages no incluya mensajes vacíos."""
    mem = _make_memory()
    mem.add_user_message("   ")
    mem.add_user_message("válido")

    ctx = mem.get_context_messages()
    contents = [m["content"] for m in ctx if m["role"] == "user"]
    assert "   " not in contents
    assert "válido" in contents


# ======================================================================
# Clear preserva system prompt
# ======================================================================


def test_clear_preserves_system_prompt():
    """Verifica que clear() elimine el historial pero mantenga el system prompt."""
    mem = _make_memory()
    mem.add_user_message("hola")
    mem.add_assistant_message("chao")

    mem.clear()

    ctx = mem.get_context_messages()
    assert len(ctx) == 1, "Solo debería quedar el system prompt"
    assert ctx[0]["role"] == "system"
    assert "personaje de prueba" in ctx[0]["content"]


# ======================================================================
# v12: flujo completo de mensajes (escenario real de Luna)
# ======================================================================


def test_full_message_flow_preserved():
    """Verifica que 6 turnos consecutivos se preserven completos.
    Escenario real extraído del chat con Luna."""
    mem = _make_memory(history_limit=50)

    messages = [
        "Hola",
        "Mi nombre es LiuniK",
        "Como te llamas",
        "Tengo un perro llamado Pepe",
        "como me llamo",
        "cual es el nombre de mi perro",
    ]

    # Agregar todos los mensajes simulando una conversación
    for msg in messages:
        mem.add_user_message(msg)
        mem.add_assistant_message(f"respuesta a: {msg}")

    # Verificar que todos los mensajes están presentes
    ctx = mem.get_context_messages()
    user_msgs = [m for m in ctx if m["role"] == "user"]
    assistant_msgs = [m for m in ctx if m["role"] == "assistant"]

    assert len(user_msgs) == len(messages), \
        f"Todos los mensajes user deben estar presentes: {len(user_msgs)}/{len(messages)}"
    assert len(assistant_msgs) == len(messages), \
        f"Todas las respuestas deben estar presentes: {len(assistant_msgs)}/{len(messages)}"

    # Verificar mensajes específicos
    assert user_msgs[0]["content"] == "Hola"
    assert user_msgs[1]["content"] == "Mi nombre es LiuniK"
    assert user_msgs[2]["content"] == "Como te llamas"
    assert user_msgs[3]["content"] == "Tengo un perro llamado Pepe"
    assert user_msgs[4]["content"] == "como me llamo"
    assert user_msgs[5]["content"] == "cual es el nombre de mi perro"

    # Verificar orden: system, user1, asst1, user2, asst2, ...
    assert ctx[0]["role"] == "system"
    assert ctx[1]["role"] == "user"
    assert ctx[2]["role"] == "assistant"
    assert ctx[3]["role"] == "user"
    assert ctx[11]["role"] == "user"  # último user
    assert ctx[12]["role"] == "assistant"  # última respuesta

    # Verificar que el system prompt no se perdió
    assert "personaje de prueba" in ctx[0]["content"]
