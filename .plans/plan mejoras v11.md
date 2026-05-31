# Plan mejoras v11

## Objetivo

Indexar secciones clave del personaje (identidad, background, reglas, escenario) en ChromaDB durante `load_character()`, usando tags semánticos `[CHARACTER][*]` para que el retrieval semántico los recupere como refuerzo contextual cuando el usuario haga preguntas relacionadas.

## Cambio propuesto

### 1. Indexar secciones del character en ChromaDB durante load_character()

En `_warmup_character_cache()`, después de compilar el prompt, extraer las secciones del DNA y guardarlas como documentos individuales en la colección `archived_memory`.

```python
# Al final de _warmup_character_cache(), si hay chroma disponible:
self._index_character_core()
```

### 2. `_index_character_core()` — nuevo método

```python
def _index_character_core(self) -> None:
    """Indexa secciones clave del personaje en ChromaDB para refuerzo semántico."""
    archived = getattr(self, "_archived_chroma", None)
    if not archived or not archived.is_available:
        return

    # Limpiar índices previos del personaje
    existing = archived.get_all_documents()
    old_ids = [d["id"] for d in existing if d["id"].startswith("charcore_")]
    if old_ids:
        archived.delete_ids(old_ids)

    manager = self._character_manager

    # Secciones a indexar
    docs = []

    if manager.identity.name:
        docs.append({
            "id": "charcore_identity",
            "document": f"[CHARACTER][IDENTITY] Your name is {manager.identity.name}. "
                        f"Your role is {manager.identity.role}. Your age is {manager.identity.age}.",
            "metadata": {"type": "charcore", "section": "identity"},
        })

    if manager.identity.background:
        docs.append({
            "id": "charcore_background",
            "document": f"[CHARACTER][BACKGROUND] {manager.identity.background}",
            "metadata": {"type": "charcore", "section": "background"},
        })

    if manager.identity.scenario:
        docs.append({
            "id": "charcore_scenario",
            "document": f"[CHARACTER][SCENARIO] {manager.identity.scenario}",
            "metadata": {"type": "charcore", "section": "scenario"},
        })

    if manager.personality_dna.traits:
        docs.append({
            "id": "charcore_traits",
            "document": f"[CHARACTER][TRAITS] {', '.join(manager.personality_dna.traits)}",
            "metadata": {"type": "charcore", "section": "traits"},
        })

    if manager.rules.core_rules:
        doc = "\n".join(f"- {r}" for r in manager.rules.core_rules)
        docs.append({
            "id": "charcore_rules",
            "document": f"[CHARACTER][RULES]\n{doc}",
            "metadata": {"type": "charcore", "section": "rules"},
        })

    if manager.speech.style or manager.speech.tone:
        style = manager.speech.style or "Not specified"
        tone = manager.speech.tone or "Not specified"
        verbosity = manager.speech.verbosity or "Not specified"
        docs.append({
            "id": "charcore_speech",
            "document": f"[CHARACTER][SPEECH] Style: {style}. Tone: {tone}. Verbosity: {verbosity}.",
            "metadata": {"type": "charcore", "section": "speech"},
        })

    if docs:
        archived.add_documents_batch(docs)
        self._log_debug("CHAR", f"Indexadas {len(docs)} secciones del personaje en ChromaDB")
```

### 3. Llamada desde `_warmup_character_cache()`

Después de guardar `base.state` y marcar rebuild como hecho, llamar a `_index_character_core()`.

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `engine/character.py` | Nuevo `_index_character_core()` + llamada en warmup |
| `db/chroma_store.py` | Nuevo `delete_ids()` para limpieza |

## Resultado esperado

- Durante `load_character()`, las secciones clave se indexan en `archived_memory`
- IDs: `charcore_identity`, `charcore_background`, `charcore_scenario`, etc.
- `SemanticRetrievalStrategy` (configurada con `archived_memory`) puede recuperarlas cuando el usuario haga preguntas relacionadas
- Al recargar el personaje, los índices viejos se limpian y se recrean
