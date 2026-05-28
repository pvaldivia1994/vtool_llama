import uuid
from pathlib import Path
from typing import Callable, Optional, List, Dict

try:
    import chromadb
    from chromadb.utils import embedding_functions as chroma_ef
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False

def _resolve_default_embedding():
    """Intenta crear embedding function por defecto."""
    try:
        return chroma_ef.DefaultEmbeddingFunction()
    except Exception:
        return None

class ChromaStore:
    """Maneja el almacenamiento vectorial genérico."""

    def __init__(self, db_path: Path, collection_name: str, log_fn: Optional[Callable] = None):
        self._db_path = db_path
        self._collection_name = collection_name
        self._log = log_fn or (lambda msg: None)
        self._client = None
        self._collection = None
        self._embedding_fn = _resolve_default_embedding()

    @property
    def chroma_path(self) -> Path:
        return self._db_path

    @property
    def is_available(self) -> bool:
        return HAS_CHROMA and self._collection is not None

    def initialize(self) -> bool:
        """Inicializa o abre la base de datos ChromaDB."""
        if not HAS_CHROMA:
            self._log("WARN: chromadb no instalado. Usando fallback sin busqueda semantica.")
            return False

        try:
            self._db_path.mkdir(parents=True, exist_ok=True)

            self._client = chromadb.PersistentClient(path=str(self._db_path))
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                embedding_function=self._embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
            return True
        except Exception as e:
            self._log(f"WARN: Error iniciando ChromaDB ({self._collection_name}): {e}")
            return False

    def count(self) -> int:
        if not self.is_available:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    def add_document(self, doc_id: str, document: str, metadata: dict) -> None:
        """Guarda un documento como embedding semantico."""
        if not self.is_available:
            return
        try:
            self._collection.add(
                ids=[doc_id],
                documents=[document],
                metadatas=[metadata],
            )
        except Exception as e:
            self._log(f"WARN: Error guardando documento en ChromaDB ({self._collection_name}): {e}")

    def add_documents_batch(self, documents_data: List[Dict]) -> None:
        """Guarda multiples documentos en batch. Cada dict debe tener 'id', 'document', 'metadata'."""
        if not self.is_available or not documents_data:
            return
        ids = []
        documents = []
        metadatas = []
        for doc in documents_data:
            ids.append(doc.get("id", uuid.uuid4().hex[:12]))
            documents.append(doc.get("document", ""))
            metadatas.append(doc.get("metadata", {}))
        try:
            self._collection.add(ids=ids, documents=documents, metadatas=metadatas)
        except Exception as e:
            self._log(f"WARN: Error en batch insert ChromaDB ({self._collection_name}): {e}")

    def search(self, query: str, top_k: int = 5, where: Optional[dict] = None) -> List[Dict]:
        """Busqueda semantica de documentos."""
        if not self.is_available:
            return []
        try:
            kwargs = {
                "query_texts": [query],
                "n_results": min(top_k, 20),
            }
            if where:
                kwargs["where"] = where
            results = self._collection.query(**kwargs)

            docs_list = []
            ids = results.get("ids", [[]])[0]
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]

            for i in range(len(ids)):
                docs_list.append({
                    "id": ids[i],
                    "document": docs[i] if i < len(docs) else "",
                    "metadata": metas[i] if i < len(metas) else {},
                    "similarity": 1.0 - dists[i] if i < len(dists) else 0.0,
                })
            return docs_list
        except Exception as e:
            self._log(f"WARN: Error en busqueda ChromaDB ({self._collection_name}): {e}")
            return []

    def clear(self) -> None:
        """Limpia todos los documentos de la coleccion."""
        if not self.is_available:
            return
        try:
            existing = self._collection.get()
            if existing and existing.get("ids"):
                self._collection.delete(ids=existing["ids"])
        except Exception:
            pass

    def delete_by_metadata(self, where: dict) -> None:
        """Elimina documentos de la coleccion que coincidan con un filtro de metadatos."""
        if not self.is_available:
            return
        try:
            self._collection.delete(where=where)
            self._log(f"ChromaDB: Documentos eliminados con filtro where={where}")
        except Exception as e:
            self._log(f"WARN: Error eliminando documentos en ChromaDB por metadatos (intentando fallback): {e}")
            try:
                existing = self._collection.get()
                if existing and existing.get("ids"):
                    ids_to_delete = []
                    for i, meta in enumerate(existing.get("metadatas", [])):
                        if meta:
                            if "timestamp" in where and isinstance(where["timestamp"], dict) and "$gt" in where["timestamp"]:
                                target = where["timestamp"]["$gt"]
                                val = meta.get("timestamp")
                                if val and val > target:
                                    ids_to_delete.append(existing["ids"][i])
                            else:
                                match = True
                                for k, v in where.items():
                                    if meta.get(k) != v:
                                        match = False
                                        break
                                if match:
                                    ids_to_delete.append(existing["ids"][i])
                    if ids_to_delete:
                        self._collection.delete(ids=ids_to_delete)
                        self._log(f"ChromaDB Fallback: Eliminados {len(ids_to_delete)} documentos.")
            except Exception as ex:
                self._log(f"ERROR: Fallback de borrado ChromaDB falló: {ex}")


