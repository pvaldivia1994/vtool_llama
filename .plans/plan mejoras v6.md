# Plan mejoras v6

## Objetivo

Reemplazar `reset()` en `generate()` por `reset_keep()` que preserve el core del system prompt en el KV cache entre turnos. El `base.state` se conserva para carga inicial. El `_auto_trim_if_needed()` deja de hacer el baile `save_state/load_state` para proteger el core porque `reset_keep()` ya lo mantiene intacto.

## Diagnóstico

### Arquitectura actual

```
load_character()
  └─ _warmup_character_cache()
       ├─ warmup_system_prompt(prompt)   → evalúa system + 1 token
       ├─ save_kv_state("base.state")    → pickle del KV cache completo
       └─ mark_rebuild_done()

chat() / stream_chat()
  │
  ├─ _auto_trim_if_needed()
  │    ├─ is_context_near_limit() → TRUE:
  │    ├─ save_state()            ← backup (core + historial)
  │    ├─ generate(digest)        ← LLAMADA INTERNA:
  │    │    └─ model.reset()      ← BORRA TODO (core + historial)
  │    │    └─ create_chat_completion() → genera digest
  │    ├─ load_state()            ← restaura backup
  │    ├─ recorta ChatMemory
  │    └─ re-mide hasta estar bajo límite
  │
  └─ generate()
       └─ model.reset()           ← BORRA TODO OTRA VEZ
       └─ create_chat_completion()
            └─ re-evalúa TODO desde cero
```

**Problema**: `reset()` destruye el core después del primer mensaje. El warmup solo sirve para el primer `generate()` post-carga.

**El baile contradictorio**: el `save_state/load_state` del trim protege el core del digest interno, pero el `generate()` principal lo destruye igual inmediatamente después.

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `model/manager.py` | Agregar `_n_keep: Optional[int] = None` |
| `model/kv_cache.py` | Nuevo método `reset_keep()` |
| `model/inference.py` | `reset()` → `reset_keep()` en `generate()` |
| `model/model_ops.py` | Resetear `_n_keep` en `unload_model()` y al inicio de `load_model()` |
| `engine/character.py` | Medir y guardar `n_keep` en `_warmup_character_cache()` |
| `engine/memory.py` | Simplificar `_auto_trim_if_needed()` (quitar save/load_state redundante) |
| `engine/base.py` | Agregar `n_keep`, `kv_cache_tokens` y `kv_cache_usage_pct` a `get_token_usage()` |
| `tests/test_kv_cache.py` | Test unitario de `reset_keep()` (nuevo archivo) |

## Estrategia propuesta

### 1. Agregar `ModelManager._n_keep` en `__init__`

**Archivo: `model/manager.py`**

```python
# Línea 25, junto a otros flags:
self._n_keep: Optional[int] = None
```

Se inicializa como `None`. Cuando es `None`, `reset_keep()` se comporta como `reset()` (full clear, legacy).

---

### 2. Implementar `ModelManager.reset_keep()`

**Archivo: `model/kv_cache.py`**

```python
def reset_keep(self: ModelManager) -> None:
    """Borra el KV cache después de n_keep. El core del system prompt queda intacto.

    - Si _n_keep es None: reset completo (legacy, mismo comportamiento que antes).
    - Si _n_keep > 0: usa kv_cache_seq_rm para borrar solo [n_keep..n_tokens).
    - Si n_tokens <= n_keep: no hay nada que borrar, todo es core.
    - Si la API de bajo nivel no está disponible: fallback a reset() completo.
    """
    if self._n_keep is None or self._n_keep <= 0:
        if hasattr(self._model, "reset") and callable(self._model.reset):
            self._model.reset()
        return

    n_tokens = getattr(self._model, "n_tokens", 0)
    if n_tokens <= self._n_keep:
        return  # Todo es core, no hay nada que borrar

    try:
        # Intentar API directa de llama-cpp-python
        ctx = getattr(self._model, "_ctx", None) or getattr(self._model, "ctx", None)
        if ctx is not None:
            # kv_cache_seq_rm(seq_id, start, end) — borra posiciones [start, end)
            if hasattr(ctx, "kv_cache_seq_rm"):
                ctx.kv_cache_seq_rm(-1, self._n_keep, n_tokens)
                self._model.n_tokens = self._n_keep
                self._log("MODEL", f"reset_keep: core intacto ({self._n_keep} tokens, liberados {n_tokens - self._n_keep})")
                return

        # Fallback: reset completo
        if hasattr(self._model, "reset") and callable(self._model.reset):
            self._model.reset()
            self._log("MODEL", "reset_keep: API kv_cache_seq_rm no disponible, reset completo")
    except Exception as e:
        self._log("MODEL", f"reset_keep: error con kv_cache_seq_rm ({e}), fallback a reset completo")
        if hasattr(self._model, "reset") and callable(self._model.reset):
            self._model.reset()


ModelManager.reset_keep = reset_keep
```

**Correcciones vs plan original**:
- `n_tokens` es un atributo entero, no un método — no se llama con `()`
- Se verifica `ctx` tanto en `_ctx` como en `ctx` (según versión de `llama-cpp-python`)
- El mensaje de log muestra cuántos tokens se liberaron
- Se asigna `self._model.n_tokens` — posiblemente de solo-lectura en algunas versiones, atrapado por el `except`

---

### 3. Cambiar `generate()` para usar `reset_keep()`

**Archivo: `model/inference.py`**

```python
def generate(self, messages, ...):
    with self._lock:
        if self._model is None:
            raise ModelNotLoadedError(...)

        self.reset_keep()  # ← reemplaza a model.reset()

        kwargs = { ... }
        result = self._model.create_chat_completion(**kwargs)
        return result
```

Solo cambia la línea de `reset()` por `reset_keep()`.

**Riesgo**: `create_chat_completion()` internamente puede resetear el KV cache igual. Depende de la implementación de `llama-cpp-python`. Si es el caso, `reset_keep()` es inocuo (no empeora nada). Si no lo resetea, el core se reusa y hay speedup.

---

### 4. Resetear `_n_keep` al descargar/cargar modelo

**Archivo: `model/model_ops.py`**

```python
def unload_model(self: ModelManager) -> None:
    with self._lock:
        ...
        self._model = None
        self._tokenize_fn = None
        self._model_info = ModelInfo()
        self._n_keep = None          # ← NUEVO: el core se pierde al descargar
        ...

def load_model(self: ModelManager, model_path=None) -> None:
    with self._lock:
        ...
        self._n_keep = None          # ← NUEVO: nuevo modelo, nuevo core
        ...
```

Si no se resetea `_n_keep`, al cargar un modelo nuevo el `reset_keep()` pensaría que hay un core que proteger, pero los tokens del core anterior son basura para el nuevo modelo.

---

### 5. Medir `n_keep` en `_warmup_character_cache()`

**Archivo: `engine/character.py`**

Después del warmup:

```python
def _warmup_character_cache(self, prompt=None):
    ...
    # Warmup (existente)
    if not cache_valid:
        self._model_manager.warmup_system_prompt(prompt)
        # Medir n_keep DESPUÉS del warmup
        n_keep = max(0, getattr(self._model_manager._model, "n_tokens", 0) - 1)
        if n_keep > 0:
            self._model_manager._n_keep = n_keep
        else:
            self._model_manager._n_keep = None
        self._model_manager.save_kv_state(str(base_kv_path))

        # Guardar n_keep en meta
        expected_meta["n_keep"] = n_keep
        meta_path.write_text(...)
    else:
        self._model_manager.load_kv_state(str(base_kv_path))
        # Restaurar n_keep desde meta
        self._model_manager._n_keep = current_meta.get("n_keep", 0) or None
    ...
```

**Por qué `n_tokens - 1`**: después del warmup, `create_chat_completion(messages=[system], max_tokens=1)` deja en el KV cache:
- `len(formatted_system_tokens)` tokens del system prompt formateado
- 1 token de la generación (max_tokens=1)

`n_keep` debe ser solo los tokens del system prompt. Por eso se resta 1.

**Al cargar `base.state`**: `load_kv_state` restaura el KV cache exactamente al estado post-warmup, donde `n_tokens` = `n_keep + 1`. El `n_keep` guardado en meta se restaura directamente.

---

### 6. Simplificar `_auto_trim_if_needed()` — eliminar save/load_state redundante

**Archivo: `engine/memory.py`**

Con `reset_keep()` en `generate()`, el core ya no se destruye durante la generación del digest. El `save_state/load_state` dentro del trim se vuelve redundante:

```
Antes (sin reset_keep):
  trim: save_state → generate(digest) → RESET destruye core → load_state restaura
  └─ necesario porque el core se perdía en el digest

Con reset_keep:
  trim: save_state → generate(digest) → reset_keep() mantiene core → load_state restaura
  └─ el save/load solo preserva conversación vieja que generate() va a borrar igual
```

**Cambio**: eliminar el bloque de save/load_state alrededor del digest:

```python
# ANTES (memory.py ~270-281):
saved_state = None
raw_model = getattr(self._model_manager, "_model", None)
try:
    if raw_model and hasattr(raw_model, "save_state"):
        saved_state = raw_model.save_state()
    if len(digest_candidates) > 2:
        digest = _digest_with_llm(digest_candidates)
finally:
    if saved_state is not None and raw_model and hasattr(raw_model, "load_state"):
        try:
            raw_model.load_state(saved_state)
        except Exception:
            pass

# DESPUÉS:
if len(digest_candidates) > 2:
    digest = _digest_with_llm(digest_candidates)
# El core sobrevive al digest gracias a reset_keep()
```

**Si `kv_cache_seq_rm` no está disponible**: `reset_keep()` cae a `reset()` completo, y el trim perdería el core. Pero es el mismo comportamiento que hoy (el core se pierde igual con `reset()`). No hay regresión.

---

### 7. `get_token_usage()`

**Archivo: `engine/base.py`** — método `get_token_usage()` (línea 349)

**Diagnóstico**: el método actual cuenta tokens sobre los mensajes de `ChatMemory`. Es una estimación textual que NO refleja el estado real del KV cache:

| Qué mide | Cómo |
|----------|------|
| `system_tokens` | `count_tokens()` sobre el texto del system prompt en RAM |
| `history_tokens` | `count_tokens()` sobre el historial en RAM |
| `total_tokens` | Suma de los anteriores |

**Lo que NO mide**:
- Los tokens reales en el KV cache del modelo (`model.n_tokens`)
- El core protegido (`_n_keep`)
- La diferencia entre la estimación textual y lo que realmente ocupa espacio en el KV cache (el chat template puede agregar tokens de formato)

**Con el plan v6**, donde el KV cache persiste entre turnos y tiene un core protegido, estas métricas son aún más importantes para diagnosticar:

- ¿El core se está preservando correctamente?
- ¿Cuánto del KV cache real está ocupado vs la estimación textual?
- ¿Hay desincronización entre ChatMemory y el KV cache?

**Cambio propuesto**: agregar tres campos al dict de retorno:

```python
# Al final de get_token_usage(), antes del return:

# Métricas del KV cache real (plan v6)
n_keep = getattr(self._model_manager, "_n_keep", None) or 0

kv_cache_tokens = 0
if self._model_manager.is_loaded:
    model = getattr(self._model_manager, "_model", None)
    if model is not None:
        kv_cache_tokens = getattr(model, "n_tokens", 0) or 0

kv_cache_usage_pct = (
    round((kv_cache_tokens / max_tokens) * 100, 1)
    if max_tokens > 0 and kv_cache_tokens > 0
    else 0.0
)
```

Y agregar al return:

```python
"n_keep": n_keep,
"kv_cache_tokens": kv_cache_tokens,
"kv_cache_usage_pct": kv_cache_usage_pct,
```

**Comportamiento cuando no hay modelo cargado o no hay warmup**:
- `n_keep` = 0 (no hay core)
- `kv_cache_tokens` = 0 (no hay KV cache)
- `kv_cache_usage_pct` = 0.0

**Valor diagnóstico**:
- Si `kv_cache_tokens` es significativamente mayor que `total_tokens` estimado, hay que investigar (posible contaminación del KV cache, o el chat template agrega muchos tokens)
- Si `n_keep` > 0 pero `kv_cache_tokens` <= `n_keep`, el core está preservado y no hay conversación en el KV cache
- La diferencia `kv_cache_tokens - n_keep` son los tokens de conversación reales en el KV cache

---

### 8. Tests

**Archivo nuevo: `tests/test_kv_cache.py`**

Los tests deben:
1. **Mockear `_model.n_tokens` y `_model._ctx`** (no podemos cargar un modelo real en tests unitarios)
2. Verificar que `reset_keep()` con `_n_keep=None` llama a `model.reset()`
3. Verificar que `reset_keep()` con `_n_keep > 0` y `n_tokens > n_keep` llama a `kv_cache_seq_rm`
4. Verificar que `reset_keep()` con `n_tokens <= n_keep` no llama a nada (todo es core)
5. Verificar que si `kv_cache_seq_rm` falla, hay fallback a `model.reset()`

Ejemplo de test con mock:

```python
def test_reset_keep_keeps_core():
    mgr = ModelManager(config=MockConfig(), logger_fn=print, error_fn=print)
    mgr._model = MagicMock()
    mgr._model.n_tokens = 500
    mgr._model._ctx = MagicMock()
    mgr._n_keep = 100

    mgr.reset_keep()

    mgr._model._ctx.kv_cache_seq_rm.assert_called_once_with(-1, 100, 500)
    assert mgr._model.n_tokens == 100

def test_reset_keep_fallback_when_no_ctx():
    mgr = ModelManager(config=MockConfig(), logger_fn=print, error_fn=print)
    mgr._model = MagicMock()
    mgr._model.n_tokens = 500
    del mgr._model._ctx  # no ctx available
    mgr._n_keep = 100

    mgr.reset_keep()

    mgr._model.reset.assert_called_once()
```

## Flujo final deseado

### Sin trim (cabe en el contexto)

```
load_character("Luna")
  └─ _warmup_character_cache()
       ├─ warmup_system_prompt(prompt) → KV cache: [core_tokens..., gen_token]
       ├─ n_keep = n_tokens - 1        → solo core, sin el gen_token
       ├─ save_kv_state("base.state")
       └─ meta["n_keep"] = n_keep

chat("Hola")
  └─ _auto_trim_if_needed() → no hace falta
  └─ generate()
       └─ reset_keep() → kv_cache_seq_rm(-1, n_keep, n_tokens)
       └─ create_chat_completion() → core en KV cache, solo evalúa historial

chat("Cómo estás?")
  └─ generate()
       └─ reset_keep() → core intacto otra vez
       └─ create_chat_completion()
```

### Con trim (contexto cerca del límite)

```
chat("msg largo...")
  └─ _auto_trim_if_needed()
       ├─ is_context_near_limit() → TRUE
       ├─ generate(digest)
       │    └─ reset_keep() → core intacto (el save_state ya no es necesario)
       │    └─ create_chat_completion() → genera digest
       ├─ recorta ChatMemory + inserta digest
       └─ re-mide → OK
  └─ generate()
       └─ reset_keep() → core intacto
       └─ create_chat_completion() → historial más chico gracias al trim
```

### Cambio de personaje

```
load_character("Otro")
  └─ cancel_load()
  └─ _warmup_character_cache()
       ├─ base.state inválido
       ├─ model.reset() ← reset COMPLETO (se destruye core anterior)
       ├─ warmup + save_kv_state con nuevo n_keep
       └─ ...
```

### Descarga/recarga de modelo

```
unload_model()
  └─ _model = None
  └─ _n_keep = None ← el core se fue con el modelo

load_model("otro_modelo.gguf")
  └─ _model = Llama(...)
  └─ _n_keep = None ← se resetea explícitamente
  └─ (próximo load_character hará warmup y seteará n_keep)
```

## Cambios propuestos

1. **`model/manager.py`** — agregar `self._n_keep: Optional[int] = None`: [Listo]
2. **`model/kv_cache.py`** — implementar `ModelManager.reset_keep()`: [Listo]
   - Usar `kv_cache_seq_rm` si `_n_keep` está definido y la API está disponible
   - Fallback a `reset()` completo si no
   - `n_tokens` como atributo entero, no callable
   - Verificar `_ctx` y `ctx` (según versión)
3. **`model/inference.py`** — `reset()` → `reset_keep()` en `generate()`: [Listo]
4. **`model/model_ops.py`** — resetear `_n_keep = None` en:
   - `unload_model()` (el core se pierde con el modelo): [Listo]
   - `load_model()` al inicio (nuevo modelo, nuevo core): [Listo]
5. **`engine/character.py`** — en `_warmup_character_cache()`:
   - Medir `n_keep = max(0, n_tokens - 1)` después del warmup: [Listo]
   - Guardar `n_keep` en `base.state.meta.json`: [Listo]
   - Restaurar `_n_keep` desde meta al cargar `base.state`: [Listo]
6. **`engine/memory.py`** — en `_auto_trim_if_needed()`:
   - Eliminar `save_state()`/`load_state()` alrededor del digest: [Listo]
   - (El core sobrevive gracias a `reset_keep()`, el save/load era redundante): [Listo]
7. **`engine/base.py`** — en `get_token_usage()`:
   - Agregar `n_keep` desde `ModelManager._n_keep`: [Listo]
   - Agregar `kv_cache_tokens` desde `model.n_tokens`: [Listo]
   - Agregar `kv_cache_usage_pct`: [Listo]
   - Valores default 0 si el modelo no está cargado o no hay warmup: [Listo]
8. **`tests/test_kv_cache.py`** — tests unitarios mockeados:
   - `reset_keep()` fallback a `reset()` si `_n_keep` es None: [Listo]
   - `reset_keep()` llama `kv_cache_seq_rm` si hay core: [Listo]
   - `reset_keep()` no hace nada si `n_tokens <= n_keep`: [Listo]
   - `reset_keep()` falla gracefulmente si `_ctx` no existe: [Listo]
   - `_n_keep` se resetea a None en `unload_model()`: [Listo]
   - `_n_keep` se restaura desde meta al cargar `base.state`: [Listo]

## Riesgos

1. **`kv_cache_seq_rm` es API interna de `llama-cpp-python`**: puede cambiar entre versiones.
   - Mitigación: try/except con fallback a `reset()` completo. El sistema funciona igual, solo pierde la optimización.

2. **`n_tokens` como atributo de solo-lectura**: en algunas versiones no se puede asignar.
   - Mitigación: la asignación está dentro del try/except. Si falla, cae a reset completo.

3. **`create_chat_completion()` puede resetear el KV cache internamente**: si llama a `llama_kv_cache_clear()` por su cuenta, `reset_keep()` es inocuo (no empeora, solo no mejora).
   - Mitigación: verificar experimentalmente con logging de `n_tokens` antes y después de `reset_keep()`.

4. **Contaminación entre turnos**: si `reset_keep()` no limpia bien, el modelo puede "ver" basura de turnos anteriores.
   - Mitigación: `kv_cache_seq_rm` borra todas las posiciones `[n_keep, n_tokens)`. Es equivalente a reset para la conversación. El core es idéntico al original.

5. **El trim sin save/load_state puede perder contexto**: si `reset_keep()` falla a `reset()` completo durante la generación del digest, el core se pierde igual que antes. No hay regresión vs comportamiento actual.

## Resultado esperado

- `base.state` sigue existiendo para carga inicial rápida
- `reset_keep()` mantiene el core del system prompt entre turnos
- `generate()` es potencialmente más rápido (depende del backend)
- `_auto_trim_if_needed()` más simple y rápido (sin save/load_state innecesario)
- `unload_model()`/`load_model()` resetean `_n_keep` limpiamente
- Fallback a `reset()` completo si la API de bajo nivel no está disponible
- Cero cambios en la API pública
- Tests unitarios con mocks que no requieren modelo real
