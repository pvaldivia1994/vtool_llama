# Plan mejoras v9

## Objetivo

Reemplazar el digest del trim (caro, con LLM) por guardado directo de mensajes crudos en ChromaDB. El retrieval semántico reemplaza al resumen como fuente de contexto histórico, con presupuesto fijo, threshold de similitud y orden síncrono para no perder datos.

## Diagnóstico

### Arquitectura actual

```
chat("msg largo...")
  └─ _auto_trim_if_needed()
       ├─ is_context_near_limit() → TRUE
       ├─ generate(digest)  ← LLAMADA CARA AL LLM
       ├── descarta mensajes viejos  ← SE PIERDEN
       │    └─ loop de eliminación:
       │         for i, msg in enumerate(messages):
       │             if msg.role != "system" ...:
       │                 removed = messages[i]
       │                 del messages[i]       ← desaparece, no va a ningún lado
       ├─ inserta digest en ChatMemory
       └─ guarda digest en SQLite

index_conversation()  ← cada N mensajes
  └─ agrupa en chunks de 10 → ChromaDB (conversation_chunks)
```

**Problemas:**

1. **El trim tira mensajes**: los mensajes viejos se descartan sin guardarlos en ChromaDB. Solo queda un resumen generado por LLM que cuesta ~0.5s por trim y puede alucinar.

2. **Bug en el loop de eliminación**: el loop final de `_auto_trim_if_needed()` elimina mensajes **que no estaban en `digest_candidates`**. Esos mensajes no fueron pasados al digest ni archivados — se pierden.

3. **El digest con LLM es innecesario**: con retrieval semántico sobre mensajes crudos, el resumen generado no aporta valor. Debería simplificarse a un fallback extractivo (sin LLM).

4. **Misma colección para todo**: `conversation_chunks` mezcla chunks activos con memoria histórica. No se puede limpiar uno sin afectar al otro.

5. **Query subóptima**: `SemanticRetrievalStrategy` usa los últimos 3 mensajes como query. El mensaje actual del usuario es una señal mucho más limpia.

## Cambios propuestos

### 1. `_archive_to_chroma()` — nuevo método

```python
def _archive_to_chroma(self, messages: list[Message]) -> bool:
    """Guarda mensajes crudos en archived_memory.
    Retorna True si TODOS se guardaron correctamente.
    Síncrono — si falla, el trim no continúa."""
    if not self._archived_chroma or not self._archived_chroma.is_available:
        return False
    try:
        for msg in messages:
            if not msg.content or not msg.content.strip():
                continue
            doc_id = f"archived_{msg.id}"
            self._archived_chroma.add_document(
                doc_id=doc_id,
                document=f"[{msg.role}]: {msg.content}",
                metadata={
                    "type": "archived",
                    "role": msg.role,
                    "conversation_id": self._memory._conversation_id,
                    "message_id": msg.id,
                }
            )
        return True
    except Exception as e:
        self._log_debug("MEMORY", f"Error archivando en ChromaDB: {e}")
        return False
```

**[Pendiente]**

### 2. Modificar `_auto_trim_if_needed()` — archivar antes de eliminar

El cambio sobre el código actual:

```python
# ANTES (generaba digest con LLM):
digest = ""
if len(digest_candidates) > 2:
    digest = _digest_with_llm(digest_candidates)

# DESPUÉS:
# 1. Archivar mensajes candidatos en ChromaDB (SÍNCRONO)
archived_ok = False
if len(digest_candidates) > 2:
    archived_ok = self._archive_to_chroma(digest_candidates)
    if not archived_ok:
        self._log_debug("MEMORY", "ChromaDB no disponible, usando fallback extractivo")

# 2. Digest extractivo SOLO (sin LLM, usa el _fallback_digest ya existente)
digest = _fallback_digest(digest_candidates) if digest_candidates else ""

# 3. Watermark si se archivó correctamente (pasar lista, no max — ver cambio 7)
if archived_ok and self._chat_store and self._memory._conversation_id:
    archived_ids = [msg.id for msg in digest_candidates if hasattr(msg, 'id') and msg.id]
    if archived_ids:
        self._chat_store.update_archived_watermark(
            self._memory._conversation_id,
            archived_ids       # ← lista completa, no max()
        )
```

**En el loop de eliminación**, agregar guardado de mensajes no capturados:

```python
# El loop actual:
for i, msg in enumerate(self._memory._messages):
    if msg.role != "system" and i != last_user_index:
        removed = self._memory._messages[i]
        # ← NUEVO: archivar si no estaba en digest_candidates
        if not any(m.id == removed.id for m in digest_candidates):
            self._archive_to_chroma([removed])
        del self._memory._messages[i]
        break
```

**[Pendiente]**

### 3. `SemanticRetrievalStrategy` — aceptar `user_prompt`

El cambio es quirúrgico sobre el código actual:

```python
def retrieve(
    self,
    store: ChatStore,
    token_counter: TokenCounter,
    conversation_id: str,
    branch_id: str,
    leaf_message_id: int,
    budget: int,
    user_prompt: str = "",           # ← parámetro nuevo
) -> PromptSection:
    if not self._chroma_store or not self._chroma_store.is_available:
        return PromptSection(type="semantic", priority=self.priority, tokens=0, messages=[])

    # Usar user_prompt como query primaria
    if user_prompt:
        query = user_prompt[:500]    # limitar largo
    else:
        # Fallback: últimos 3 mensajes
        path = store.get_active_branch_messages(...)
        query = " ".join(m.content for m in path if m.content)

    if not query:
        return PromptSection(...)

    # ...resto igual, incluyendo el filtro por _min_similarity...
```

Requiere cambiar la firma de `RetrievalStrategy.retrieve()` y pasar `user_prompt` desde `ContextBuilder`.

**[Pendiente]**

### 4. `ArchivedMemoryStrategy` = misma clase, parametrizada

No es una clase nueva. Es `SemanticRetrievalStrategy` pero apuntando a la colección `archived_memory`:

```python
self._archived_strategy = SemanticRetrievalStrategy(
    chroma_store=self._archived_chroma,   # ← segunda colección
    min_similarity=self._config.memory_rag_min_similarity,
    priority=25,  # después de SemanticRetrievalStrategy (20), antes de RecentMessages (50)
)
```

En `ContextBuilder`, se registran ambas estrategias con el mismo `user_prompt`.

**Inicialización de `_archived_chroma` en `load_character()`:**

```python
# Junto a la inicialización de _semantic_chroma actual:
self._archived_chroma = ChromaStore(
    char_dir / "_memory" / "semantic",
    "archived_memory",
    log_fn=lambda m: self._log_debug("ARCHIVE", m),
)
self._archived_chroma.initialize()
```

**[Pendiente]**

### 5. Presupuesto fijo de tokens para RAG

```python
MEMORY_BUDGET_TOKENS = 300  # configurable via memory_rag_budget

# En retrieve(), limitar por este presupuesto, no por el budget general
rag_budget = self._rag_budget if hasattr(self, '_rag_budget') else 300
running = 0
for r in results:
    tokens = token_counter.count_text(r.get("document", ""))
    if running + tokens > rag_budget and running > 0:
        break
    ...
```

**[Pendiente]**

### 6. Threshold de similitud — default a 0.5

El default actual es 0.3. Para roleplay, donde el vocabulario es consistente, 0.3 recupera demasiado ruido. Se cambia a **0.5**:

```python
# En types/core.py (nueva config)
memory_rag_min_similarity: float = 0.5
```

Esto aplica tanto a `SemanticRetrievalStrategy` como a `ArchivedMemoryStrategy`.

**[Pendiente]**

### 7. Watermark en SQLite — con rango, no solo `max`

El watermark simple con `max(archived_ids)` asume IDs monotónicos. Más robusto: trackear un **rango** `[start_id, end_id]` o garantizar contigüidad:

```python
# En chat_store.py:
def update_archived_watermark(
    self, conversation_id: str, message_ids: list[int]
) -> None:
    """Actualiza el watermark archivado. message_ids deben ser contiguos."""
    if not message_ids:
        return
    # Guardar el rango [min, max] para tracking
    meta = self._get_archived_meta(conversation_id)
    existing = set(meta.get("archived_ids", []))
    existing.update(message_ids)
    self._set_archived_meta(conversation_id, {
        "archived_ids": sorted(existing),
        "archived_max": max(existing),
    })
```

`index_conversation()` usa `archived_max` para saltear mensajes ya archivados.

**[Pendiente]**

### 8. Retry policy para ChromaDB fallido

Si ChromaDB falla persistentemente:

```python
# Config:
memory_archive_max_retries: int = 3
memory_archive_force_trim: bool = True  # último recurso

# Inicializar contador en load_character() o VToolLlama.__init__():
self._archive_retries = 0

# En _auto_trim_if_needed():
if not archived_ok:
    self._archive_retries += 1
    if self._archive_retries >= self._config.memory_archive_max_retries:
        self._log_warning("ChromaDB no responde. Forzando trim sin archivar.")
        # continuar con digest extractivo y trim
else:
    self._archive_retries = 0  # ChromaDB respondió → resetear contador
```

El contador se resetea cuando `_archive_to_chroma()` vuelve a funcionar (else), o al cargar un nuevo personaje.

**[Pendiente]**

### 9. Deduplicación entre colecciones

Cuando `SemanticRetrievalStrategy` y `ArchivedMemoryStrategy` devuelven fragmentos en el mismo turno, puede haber duplicados por contenido o por `doc_id`:

```python
# En ContextBuilder, después de recolectar todas las estrategias:
seen_ids = set()
seen_texts = set()
deduped = []
for section in all_sections:
    for msg in section.messages:
        content = msg.get("content", "")
        # Dedup por doc_id (si está en metadata) o por contenido exacto
        doc_id = msg.get("metadata", {}).get("doc_id", "")
        if doc_id and doc_id in seen_ids:
            continue
        if content and content in seen_texts:
            continue
        seen_ids.add(doc_id)
        seen_texts.add(content)
        deduped.append(msg)
```

**[Pendiente — Media]**

### 10. Embedding function configurable (baja)

(Sin cambios respecto a la versión anterior del plan)

### 11. Métricas de retrieval (baja)

(Sin cambios)

### 9. Embedding function configurable (baja)

### 10. Métricas de retrieval (baja)

(Sin cambios respecto a la versión anterior del plan)

## Orden de implementación

| # | Cambio | Prioridad |
|---|--------|-----------|
| 1 | `_archive_to_chroma()` + archivar en trim (síncrono) | **Crítica** |
| 2 | Archivar en loop de eliminación (mensajes no candidatos) | **Crítica** |
| 3 | Inicializar `_archived_chroma` en `load_character()` | **Alta** |
| 4 | Dos colecciones separadas + watermark en SQLite | **Alta** |
| 5 | Digest extractivo (sin LLM, `_fallback_digest` siempre) | **Alta** |
| 6 | `user_prompt` como query en `SemanticRetrievalStrategy` | **Alta** |
| 7 | Threshold de similitud default 0.5 | **Alta** |
| 8 | `ArchivedMemoryStrategy` = misma clase parametrizada | **Media** |
| 9 | Presupuesto fijo `MEMORY_BUDGET_TOKENS` | **Media** |
| 10 | Retry policy para ChromaDB fallido | **Media** |
| 11 | Deduplicación entre colecciones | **Media** |
| 12 | Embedding function configurable | **Baja** |
| 13 | Métricas de retrieval | **Baja** |

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `engine/memory.py` | `_archive_to_chroma()` + archivar en trim + archivar en loop eliminación |
| `engine/retrieval.py` | `user_prompt` en `SemanticRetrievalStrategy` + `_rag_budget` + `_min_similarity=0.5` |
| `engine/context_builder.py` | Pasar `user_prompt` a estrategias; dedup entre colecciones |
| `engine/chat.py` | Pasar `prompt` a `ContextBuilder` |
| `engine/base.py` | Inicializar `_archive_retries = 0` en `__init__` |
| `engine/character.py` | Inicializar `_archived_chroma` en `load_character` |
| `db/chat_store.py` | Watermark de archivado (`get/update_archived_watermark`) |
| `db/chroma_store.py` | Soporte para embedding function configurable |
| `types/core.py` | Nuevas configs: `memory_rag_budget`, `memory_rag_min_similarity`, `memory_archive_max_retries`, `embedding_model` |

## Riesgos (actualizado)

1. **Orden del trim**: si ChromaDB falla y el KV se trimea igual, se pierden mensajes.
   - Guardado síncrono con `if archived_ok:` bloqueando el resto del trim.
   - Retry policy: N reintentos, luego force-trim como último recurso.

2. **Watermark no monotónico**: si los IDs no son contiguos, `max()` puede marcar como archivado lo que no está.
   - Se guarda el set completo de IDs archivados, no solo el max.

3. **Ruido en retrieval**: threshold bajo recupera fragmentos irrelevantes.
   - Default 0.5, configurable. Evaluar en producción y ajustar.

4. **Loop de eliminación no capturado**: mensajes fuera de `digest_candidates` se pierden.
   - Verificación `if not any(m.id == removed.id ...)` justo antes del `del`.

5. **ChromaDB caído permanentemente**: el trim nunca se ejecuta y el contexto se llena.
   - Retry policy con `memory_archive_force_trim` como último recurso.
