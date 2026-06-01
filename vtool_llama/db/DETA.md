# db — Arquitectura Detallada

## Visión General

Capa de infraestructura para persistencia. Contiene tres componentes: `ChatStore` (SQLite event store), `ChromaStore` (wrapper vectorial para memorias semánticas) y utilidades de I/O para archivos JSON.

```
├── db/
│   ├── __init__.py       # Barrel: exporta ChatStore, ChromaStore, HAS_CHROMA, io
│   ├── chat_store.py     # SQLite event store (source of truth del historial)
│   ├── chroma_store.py   # Wrapper para ChromaDB (solo memorias semánticas)
│   └── io.py             # Utilidades compartidas de I/O
```

## Archivos del Subpackage

### `__init__.py`
Barrel. Exporta `ChatStore`, `ChromaStore`, `HAS_CHROMA` y el módulo `io`.

### `chat_store.py` — SQLite Event Store

Source of truth del historial conversacional. Reemplaza a ChromaDB para almacenar mensajes.

**Esquema SQLite (WAL mode):**

| Tabla | Propósito |
|-------|-----------|
| `conversations` | Sesiones por personaje con active_branch + active_leaf |
| `messages` | Eventos inmutables con branch_id, message_index, parent_id, speaker_tag (v13), thinking TEXT (v19) |
| `branches` | Ramas (br_001, br_002...) con label descriptivo |
| `summaries` | Episodios/resúmenes automáticos o manuales |
| `tool_calls` | Registro detallado de tool calls |
| `memories` | Hechos/preferencias importantes extraídos |
| `context_snapshots` | Debug: snapshot del prompt exacto enviado al LLM |
| `state` | KV store para metadata de la sesión |

```
ChatStore
├── __init__(db_path) → ensure_schema() con WAL
├── get_or_create_conversation(name) → Conversation
├── set_active_leaf(conv_id, branch_id, msg_id)
│
├── add_message(conv_id, branch, role, content, ..., speaker_tag="", thinking="") → int (v19)
├── get_message_path(leaf_id) → list[ChatMessage]
├── get_active_branch_messages(conv_id, branch, leaf, limit)
├── soft_delete_message(msg_id)
│
├── create_branch(conv_id, from_msg_id, label) → str
├── get_branches(conv_id) → list[Branch]
├── checkout(conv_id, branch_id, leaf_msg_id)
│
├── add_summary(conv_id, branch, start, end, summary, ...) → int
├── get_summaries(conv_id, branch, limit)
├── get_summary_by_id(id)
├── delete_summary(id) → bool
│
├── add_memory(conv_id, type, content, ...) → int
├── get_memories(conv_id, limit, min_importance)
├── bump_memory_access(memory_id)
│
├── add_tool_call(message_id, tool_name, ...) → int
├── get_tool_calls(message_id) → list[dict]
│
├── save_context_snapshot(conv_id, prompt, token_count)
│
├── close()
└── checkout(conv_id, branch_id, leaf_msg_id) → rollback NO destructivo
```

**Branching**: `message_index` auto-incremental por branch. `parent_id` permite reconstruir el path completo. `checkout()` cambia el puntero activo sin borrar nada.

**Concurrencia**: WAL mode + `PRAGMA synchronous=NORMAL` + RLock para escrituras seguras desde múltiples threads.

### `chroma_store.py` — Wrapper para ChromaDB (solo memorias)

Actúa como capa semántica opcional. Ya NO guarda turnos de chat (eso lo hace ChatStore).

| Método | Rol |
|--------|-----|
| `initialize()` | Crea/abre colección ChromaDB |
| `add_document(id, text, meta)` | Indexa un documento con embedding |
| `search(query, top_k, where)` | Búsqueda semántica |
| `get_all_documents()` | Exporta todos los documentos (para migración) |
| `clear()` | Elimina toda la colección |
| `close()` | Cierra conexión |

**Manejo de errores**: Si chromadb no está instalado, `HAS_CHROMA = False` y todos los métodos son no-op.

### `io.py` — Utilidades de I/O

| Función | Rol |
|---------|-----|
| `ensure_dir(path)` | Crea directorio recursivamente |
| `read_json_dict(path)` | Lee JSON como dict |
| `write_json(path, data, atomic=True)` | Escritura atómica (`.tmp` + `os.replace`), asegurando la creación del directorio padre si no existe |

## Dependencias

| Módulo | Lo usa |
|--------|--------|
| `db.chat_store` | `engine/character.py`, `engine/chat.py`, `engine/memory.py`, `engine/base.py` |
| `db.chroma_store` | `soul/accessor.py`, `soul/soul_generator.py` (solo memorias) |
| `db.io` | Cualquier módulo que necesite I/O de archivos |
