"""
Test v12: verificar que los mensajes se acumulan correctamente
despues de load_character() con el fix del deque maxlen.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vtool_llama import VToolLlama

def test_messages_accumulate_after_load():
    """Despues de load_character(), los mensajes deben acumularse."""
    llm = VToolLlama(auto_load=False)
    # Verificar que ANTES de load_character el maxlen sea correcto
    print(f"ANTES de load: maxlen={llm._memory._messages.maxlen} history_limit={llm._memory._history_limit}")
    print(f"config.history_limit={llm._config.history_limit}")
    llm.load_character("luna")
    # Verificar DESPUES de load_character
    print(f"DESPUES de load: maxlen={llm._memory._messages.maxlen} history_limit={llm._memory._history_limit}")
    assert llm._memory._messages.maxlen == 42, \
        f"maxlen debe ser 42, es {llm._memory._messages.maxlen}"

    # Contar mensajes user actuales (vienen de la conversacion anterior en SQLite)
    ctx_before = llm._memory.get_context_messages()
    existing_users = len([m for m in ctx_before if m["role"] == "user"])
    
    # Agregar 3 turnos nuevos
    for i, p in enumerate(["Tengo un perro llamado Pepe", "como me llamo", "cual es el nombre de mi perro"]):
        llm._memory.add_user_message(p)
        llm._memory.add_assistant_message(f"respuesta {i}")

    ctx = llm._memory.get_context_messages()
    user_msgs = [m for m in ctx if m["role"] == "user"]
    total_expected = existing_users + 3
    assert len(user_msgs) == total_expected, \
        f"Deben haber {total_expected} mensajes user, hay {len(user_msgs)}"
    assert any("Tengo un perro" in m["content"] for m in user_msgs), \
        "'Tengo un perro' debe estar en los mensajes"
    assert any("cual es el nombre" in m["content"] for m in user_msgs), \
        "'cual es el nombre' debe estar en los mensajes"
    print(f"OK: maxlen={llm._memory._messages.maxlen}, {len(ctx)} mensajes totales")
    llm._chat_store.close()
