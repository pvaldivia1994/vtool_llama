# db — Arquitectura Detallada

## Visión General

Capa de infraestructura para persistencia. Contiene dos componentes: un wrapper para ChromaDB (base de datos vectorial) y utilidades compartidas de I/O para archivos JSON con escritura atómica.

```
├── db/
│   ├── __init__.py       # Barrel: exporta ChromaStore, HAS_CHROMA, io
│   ├── chroma_store.py   # Wrapper para ChromaDB
│   └── io.py             # Utilidades compartidas de I/O
```

## Archivos del Subpackage

### `__init__.py`
Barrel. Exporta `ChromaStore`, `HAS_CHROMA` y el módulo `io`.

### `chroma_store.py` — Wrapper para ChromaDB

Clase `ChromaStore` que abstrae la base de datos vectorial ChromaDB para búsqueda semántica.

```
ChromaStore
├── __init__(db_path, collection_name, log_fn)
├── initialize() -> bool
├── add_event(event_id, description, metadata)
├── add_document(doc_id, text, metadata)
├── search(query, top_k, where) -> list[dict]
├── delete_by_metadata(where)
├── clear()
├── chroma_path (property)
└── is_available (property)
```

**Detalle de métodos:**

| Método | Rol |
|--------|-----|
| `initialize()` | Crea/abre colección ChromaDB en `db_path`. Retorna `False` si chromadb no está instalado |
| `add_event(id, desc, meta)` | Agrega un evento con embedding automático |
| `add_document(id, text, meta)` | Agrega un documento genérico |
| `search(query, top_k, where)` | Búsqueda semántica con filtro opcional `where`. Retorna docs con `similarity` score |
| `delete_by_metadata(where)` | Elimina documentos que matchean el filtro `where` (ej: `{"timestamp": {"$gt": "..."}}`) |
| `clear()` | Elimina toda la colección |

**Manejo de errores**: Si chromadb no está instalado, `HAS_CHROMA = False` y `initialize()` retorna `False`. Todos los métodos chequean `is_available` antes de operar.

**Embeddings**: Usa `chromadb.utils.embedding_functions.DefaultEmbeddingFunction()` (sentence-transformers all-MiniLM-L6-v2 si está disponible).

### `io.py` — Utilidades de I/O

Funciones compartidas para lectura/escritura de archivos JSON, usadas por `character/`, `soul/`, etc.

| Función | Rol |
|---------|-----|
| `ensure_dir(path)` | Crea directorio recursivamente si no existe |
| `read_json_dict(path)` | Lee JSON como dict. Retorna `{}` si no existe o hay error |
| `read_json(path, dataclass_type)` | Lee JSON filtrando solo campos válidos del dataclass |
| `write_json(path, data, atomic=True)` | Escribe JSON. Por defecto usa escritura **atómica** (`.tmp` + `os.replace`) |

**Escritura atómica** (`atomic=True`): Escribe a un archivo temporal (`.tmp`) y luego renombra. Si el proceso falla a mitad de escritura, el archivo original queda intacto. Si ocurre un error, limpia el `.tmp`.

## Dependencias

| Módulo | Lo usa |
|--------|--------|
| `db.chroma_store` | `character/chat_history.py`, `soul/accessor.py`, `soul/soul_generator.py` |
| `db.io` | Diseñado para ser usado por cualquier módulo que necesite I/O de archivos |

## Sistema de Detección de Disponibilidad

`chroma_store` tiene un mecanismo de importación condicional:

```python
try:
    import chromadb
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False
```

Todos los consumidores chequean `HAS_CHROMA` y `chroma.is_available` antes de operar, permitiendo que la librería funcione sin chromadb instalado.
