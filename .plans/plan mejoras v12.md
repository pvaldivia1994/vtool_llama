# Plan mejoras v12

## Objetivo

Diagnosticar por qué el log no captura todos los mensajes, por qué ChromaDB no se ejecuta, y crear un test que verifique el flujo completo de mensajes.

## Problemas detectados

### 1. El log no muestra el mensaje actual en "Mensajes enviados al modelo"

En el `character_log.md`, el Turno 4 muestra:

```
**Usuario**: Tengo un perro llamado Pepe
```

Pero el JSON de "Mensajes enviados al modelo" **no incluye** ese mensaje. Solo muestra los mensajes anteriores:

```json
[
  {"role": "user", "content": "[USER] Hola"},
  {"role": "assistant", ...},
  {"role": "user", "content": "[USER] Mi nombre es LiuniK"},
  {"role": "assistant", ...},
  {"role": "user", "content": "[USER] Como te llamas"},
  {"role": "assistant", ...}
]
```

La SQLite SÍ registró el mensaje (línea 177 del log), y el modelo SÍ respondió (línea 221), pero el JSON del log no lo contiene. Esto puede ser porque:
- `_log_debug_turn()` se llama con `messages` que no incluye el mensaje actual
- El mensaje fue agregado después del logging
- Timing issue en stream_chat vs chat

### 2. No hay logs `[CHROMA]` — ChromaDB no se está ejecutando

En todo el log no hay una sola línea `[CHROMA]`. Las estrategias de retrieval (`SemanticRetrievalStrategy`, `ArchivedMemoryStrategy`) no se están ejecutando o no encuentran ChromaDB disponible.

Causas posibles:
- `_semantic_chroma` nunca se inicializó (porque `semantic_memory_enabled: false`)
- `_archived_chroma` nunca se inicializó (porque `semantic_memory_enabled: false`)
- Las estrategias se registran pero ChromaDB no está disponible
- `index_conversation()` no se llamó porque no hay ChromaDB

### 3. No hay test de flujo completo de mensajes

No hay un test que verifique:
- Que los mensajes se agregan correctamente al ChatMemory
- Que `_get_inference_messages()` devuelve todos los mensajes
- Que el log captura todo el flujo
- Que SQLite tiene los mismos mensajes que ChatMemory

## Cambios propuestos

### 1. Arreglar `_log_debug_turn()` para que capture el mensaje actual

El problema: `_log_debug_turn()` se llama con `messages` que son los mensajes ANTES de agregar el mensaje actual en ciertos flujos.

**Solución**: Loggear los `messages` DESPUÉS de que `generate()` devuelva, en vez de antes. O loggear `messages` + el prompt del usuario como un mensaje adicional.

En `chat.py`, mover el logging del inicio a después de generate:

```python
# En vez de:
self._log_debug_turn(prompt, messages)
result = self._model_manager.generate(messages=messages, ...)

# Hacer:
result = self._model_manager.generate(messages=messages, ...)
self._log_debug_turn(prompt, messages)  # messages now includes the response
```

**[Pendiente]**

### 2. Forzar inicialización de ChromaDB en load_character

Actualmente, ChromaDB solo se inicializa si `semantic_memory: True` se pasa a `load_character()` o si `semantic_memory_enabled: True` en config. 

**Solución**: Inicializar ChromaDB siempre que haya personaje cargado, no solo cuando `semantic_memory` está activo. La colección `archived_memory` se necesita para el `_index_character_core()` y la `ArchivedMemoryStrategy`.

```python
# En load_character(), init ChromaDB siempre:
self._semantic_chroma = ChromaStore(...)
self._semantic_chroma.initialize()
self._archived_chroma = ChromaStore(..., "archived_memory")
self._archived_chroma.initialize()
```

Sin depender de `semantic_memory` flag.

**[Pendiente]**

### 3. Test: verificar flujo completo de mensajes

Crear un test en `tests/test_chat_memory.py` que:

```python
def test_full_message_flow():
    """Verifica que todos los mensajes se preserven en el flujo completo."""
    mem = _make_memory()
    
    messages = [
        "Hola",
        "Mi nombre es LiuniK",
        "Como te llamas",
        "Tengo un perro llamado Pepe",
        "como me llamo",
        "cual es el nombre de mi perro",
    ]
    
    # Agregar todos los mensajes
    for msg in messages:
        mem.add_user_message(msg)
        mem.add_assistant_message(f"respuesta a: {msg}")
    
    # Verificar que todos están presentes
    ctx = mem.get_context_messages()
    user_msgs = [m for m in ctx if m["role"] == "user"]
    assert len(user_msgs) == len(messages)
    assert user_msgs[3]["content"] == "Tengo un perro llamado Pepe"
    
    # Verificar SQLite si está vinculado
    ...
```

**[Pendiente]**

### 4. Verificar ChromaDB en runtime

Agregar un log de diagnóstico en `_warmup_character_cache()` que muestre si ChromaDB está disponible y qué colecciones se inicializaron:

```python
self._log_debug("CHROMA", f"semantic={self._semantic_chroma is not None and self._semantic_chroma.is_available}, "
                f"archived={self._archived_chroma is not None and self._archived_chroma.is_available}")
```

**[Pendiente]**

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `engine/chat.py` | Mover `_log_debug_turn()` después de `generate()` |
| `engine/character.py` | Inicializar ChromaDB siempre + log diagnóstico |
| `tests/test_chat_memory.py` | Test de flujo completo de mensajes |

## Orden de implementación

1. Inicializar ChromaDB siempre en `load_character()`
2. Log diagnóstico de ChromaDB
3. Mover `_log_debug_turn()` después de `generate()`
4. Test de flujo completo de mensajes
