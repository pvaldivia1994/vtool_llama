# Plan mejoras v5

## Objetivo

Hacer que `load_character` sea robusto ante fallos, cancelable en toda su duración, thread-safe, y que nunca deje el sistema en un estado inconsistente.

## Diagnóstico

El sistema tiene dos capas bien diferenciadas:

- **`CharacterManager.load_character()`** — carga base del personaje (DNA, memoria, estado, mods, soul). Corre bajo lock, tiene checkpoints de cancelación entre cada paso, y devuelve `CharacterLoadResult`.
- **`VToolLlama.load_character()`** — orquestación que integra al personaje con config, stores (SQLite + Chroma), ContextBuilder, chat template, warmup de KV cache, y reconstrucción de contexto. **No corre bajo lock, no tiene checkpoints de cancelación, y no tiene rollback.**

La capa del manager está sólida. La capa de orquestación es frágil y puede dejar estados inconsistentes.

## Problemas detectados

### 1. `VToolLlama.load_character()` es monolítico y sin rollback

130+ líneas secuenciales que hacen de todo: mergear config, cerrar stores viejos, abrir stores nuevos, construir ContextBuilder, reconstruir contexto, hacer warmup.

Si algo falla en la mitad (ej: `ChatStore()` explota, ChromaDB falla, warmup crashea), el sistema queda en un estado imposible de razonar:

- Se cerraron los stores viejos (líneas 47-57).
- El personaje ya está "cargado" en el manager (porque `CharacterManager.load_character()` terminó exitosamente).
- Pero los stores nuevos, el ContextBuilder, y el warmup están a medio inicializar.
- `_inject_personality_into_system_prompt()` se llama igual (línea 147), operando sobre memoria potencialmente corrupta.

### 2. Sin checkpoints de cancelación en la orquestación

`CharacterManager.load_character()` tiene `_check_cancel()` entre cada paso (DNA → memoria → estado → mods → soul). Pero `VToolLlama.load_character()` no tiene ninguno.

Si un usuario cambia de personaje mientras `VToolLlama.load_character()` está en medio de `_warmup_character_cache()` (pesado, puede tardar segundos), el flag `_cancel_loading` ya está en `False` porque el manager terminó. No hay forma de cortar.

Flujo del bug:
1. Usuario carga personaje A → `CharacterManager.load_character("A")` termina rápido.
2. `VToolLlama.load_character()` empieza warmup (lento).
3. Usuario carga personaje B → `CharacterManager.load_character("B")` arranca, llama `cancel_load()`.
4. **El cancel no tiene efecto** porque `_cancel_loading` se resetea a `False` al entrar al manager (línea 138), y el warmup de A sigue corriendo.
5. Personaje A termina warmup, pisando config/stores que B ya empezó a configurar.

### 3. Sin lock en la capa de orquestación

`CharacterManager.load_character()` corre bajo `self._lock`. Pero `VToolLlama.load_character()` muta:
- `self._config` (línea 41)
- `self._chat_store` (línea 82)
- `self._context_builder` (línea 116)
- `self._memory` (línea 128-135, 146-147, 153)

Sin lock. Si dos threads llaman `load_character()` concurrente, es **race condition garantizada**.

### 4. Error handling contradictorio en `CharacterManager.load_character()`

```python
except Exception as e:
    result.success = False
    result.error = str(e)
    raise  # ← relanza
```

Captura el error, llena el `result`, y **relanza la excepción**. El `result` con `success=False` nunca es visto por nadie porque la excepción pasa de largo en `VToolLlama.load_character()` (que no tiene try/except propio).

O se captura y se devuelve el result, o no se captura y se deja propagar. Hacer ambas cosas es ruido y código muerto.

### 5. `char_dir` como guardia silencioso

Buena parte del orquestador está envuelto en `if char_dir:` (líneas 37, 80, 142, etc.). Si `_char_dir` es `None` después de una carga "exitosa" del manager, todo eso se skipea **sin logs, sin warnings**.

Es un caso borde, pero si ocurre, el usuario no tiene forma de saber que el personaje se cargó sin stores, sin contexto, sin warmup.

### 6. `list_characters()` lee disco cada vez

```python
def list_characters(self) -> list[dict]:
    for d in self._base_dir.iterdir():
        identity_data = self._read_json_dict(d / "dna" / "identity.json")
        ...
```

Abre y parsea un JSON por personaje. Con 3 personajes es imperceptible. Con 50+ se siente. No hay caché de metadatos.

### 7. El flag `resume_conversation` no se refleja en el manager

`VToolLlama.load_character()` decide si reanudar o crear nueva conversación en SQLite (líneas 122-126). Pero `CharacterManager` no tiene este concepto — el manager siempre carga el DNA/estado igual. La asimetría no es un bug, pero es ruido arquitectónico: la decisión de "nueva conversación vs reanudar" debería ser visible en toda la cadena.

### 8. `_warmup_character_cache()` es pesado y no informa progreso

Si el KV cache no es válido, regenerarlo puede tomar varios segundos (especialmente con modelos grandes). No hay callback de progreso, no hay log informativo de "esto va a tardar". El usuario ve el sistema congelado.

## Estrategia propuesta

### 1. Separar `VToolLlama.load_character()` en fases con protección

Refactorizar en métodos privados con responsabilidades únicas:

```python
def load_character(self, name, ...):
    _phase_1_cancel_and_lock()
    try:
        _phase_2_load_manager(name)         # CharacterManager.load_character
        _phase_3_merge_config()              # config override
        _phase_4_close_stores()              # close old SQLite + Chroma
        _phase_5_apply_chat_template()       # Jinja2 template antes del warmup
        _phase_6_init_stores()               # new ChatStore, Chroma
        _phase_7_build_context()             # ContextBuilder + strategies
        _phase_8_rebuild_context()           # load_context desde SQLite
        _phase_9_warmup()                    # _warmup_character_cache
        _phase_10_inject_personality()       # _inject_personality
        _phase_11_activate()                 # marcar personaje como activo
    except Exception:
        _phase_rollback()                    # limpiar estado inconsistente
        raise
```

Cada fase debe ser atómica en cuanto a efectos visibles: o todo lo que hace la fase se completa, o no modifica estado global.

**[Pendiente]**

### 2. Agregar checkpoints de cancelación en la orquestación

Añadir `self._character_manager._check_cancel()` entre cada fase del orquestador. Para que funcione, el flag `_cancel_loading` debe mantenerse accesible desde `VToolLlama.load_character()` incluso después de que el manager terminó.

Solución propuesta: el flag `_cancel_loading` debe vivir en el manager pero ser setteable desde afuera, o mejor: mover la lógica de cancelación a un objeto compartido (ej: `LoadCancellationToken`) que ambas capas consulten.

**Alternativa más simple**: que `VToolLlama.load_character()` tenga su propio flag de cancelación y lo verifique entre fases.

**[Pendiente]**

### 3. Agregar lock de orquestación

`VToolLlama` debe tener su propio lock (además del del manager) que proteja toda la sección de carga. Nada de mutar `self._config`, `self._chat_store`, etc., sin lock.

```python
self._load_lock = threading.Lock()

def load_character(self, ...):
    with self._load_lock:
        ...
```

**[Pendiente]**

### 4. Decidir política de error handling en `CharacterManager.load_character()`

**Opción A**: capturar, llenar result, NO relanzar. Devolver `CharacterLoadResult(success=False)` y que el caller decida.

**Opción B**: no capturar `Exception`, solo `LoadCancelledError`. Dejar que las excepciones reales (JSON corrupto, permisos, etc.) propaguen naturalmente.

Recomendación: **Opción B**. El `CharacterLoadResult` es útil para cancelación, pero para errores reales es mejor que la excepción se propague con su stack trace completo.

**[Pendiente]**

### 5. Reemplazar `if char_dir:` con verificación explícita y logging

Donde hoy hay `if char_dir:`, poner:

```python
if not char_dir:
    self._log_warning("load_character: char_dir es None, skipping stores/context/warmup")
    return
```

Y considerar si tiene sentido que `char_dir` sea `None` después de una carga exitosa. Si no, es un error y debería lanzar excepción.

**[Pendiente]**

### 6. Cachear metadatos de `list_characters()`

Mantener un archivo `characters/_index.json` con metadatos ligeros (name, role, background, has_soul) que se actualice al crear/eliminar personajes.

`list_characters()` lee ese índice en vez de escanear directorios. Si no existe, hace el escaneo completo y lo regenera.

**[Pendiente]**

### 7. Mover `resume_conversation` al manager o a un contrato compartido

Si `CharacterManager` va a ser reutilizable fuera de `VToolLlama`, debería entender el concepto de "nueva conversación vs reanudar". Alternativa: documentar que esa decisión es responsabilidad exclusiva del orquestador.

Para v5 alcanza con documentarlo y asegurarse de que el flag sea consistente: si `resume_conversation=False` pero el manager cargó estado previo del personaje, el `ChatMemory` arranca limpio.

**[Parcial] — ya existe el flag, falta consistencia con manager**

### 8. Agregar callback de progreso al warmup

`_warmup_character_cache()` debería aceptar un `progress_callback: Optional[Callable[[int, str], None]]` opcional, y reportar:
- `(0, "Compilando prompt...")`
- `(25, "Generando KV cache...")`
- `(50, "Guardando estado base...")`
- `(75, "Verificando integridad...")`
- `(100, "Listo")`

Así apps web/UI pueden mostrar una barra de progreso.

**[Pendiente]**

### 9. Agregar flag `_loading` en VToolLlama

Similar al flag del manager, para que el sistema sepa que hay una carga en curso y pueda:
- Rechazar llamadas a `chat()`/`stream_chat()` durante la carga.
- Mostrar estado "cargando..." en APIs externas.
- Prevenir doble carga.

**[Pendiente]**

## Cambios propuestos

1. Refactorizar `VToolLlama.load_character()` en fases atómicas con rollback. [Pendiente]
2. Agregar checkpoints de cancelación en el orquestador. [Pendiente]
3. Agregar `self._load_lock` en `VToolLlama` para proteger la carga. [Pendiente]
4. Cambiar `CharacterManager.load_character()` a Opción B (no relanzar Exception genérica). [Pendiente]
5. Reemplazar `if char_dir:` con logging explícito y early return. [Pendiente]
6. Cachear metadatos de personajes para `list_characters()`. [Pendiente]
7. Documentar y reforzar consistencia de `resume_conversation`. [Parcial]
8. Agregar `progress_callback` a `_warmup_character_cache()`. [Pendiente]
9. Agregar `VToolLlama._loading` flag. [Listo]
10. Agregar tests específicos:
    - Doble carga concurrente no corrompe estado. [Pendiente]
    - Cancelación durante warmup funciona. [Pendiente]
    - Fallo en fase 6 no deja stores colgados. [Pendiente]
    - char_dir=None no skipea silenciosamente. [Pendiente]
    - `list_characters()` usa caché cuando existe. [Pendiente]

## Riesgos

1. **Refactor muy grande** — tocar `load_character()` puede romper todo el flujo de carga.
   - Mitigación: tests primero que congelen el comportamiento actual, después refactor.

2. **Lock de orquestación puede causar deadlocks** — si el lock del manager y el de `VToolLlama` se adquieren en distinto orden.
   - Mitigación: siempre adquirir `_load_lock` primero, después `_manager._lock`. Documentar el orden.

3. **Cache de `list_characters()` desactualizado** — si alguien crea personajes manualmente (sin usar `create_character()`).
   - Mitigación: regenerar el índice si falta o si hay discrepancia en directorios.

4. **Callback de progreso aumenta acoplamiento** — `_warmup_character_cache()` hoy es pura, un callback la haría menos testeable.
   - Mitigación: el callback es opcional y `None` por defecto. Tests usan `None`.

## Resultado esperado

`load_character` debe ser un pipeline con estas garantías:

- **Cancelable en cualquier punto**: desde que arranca hasta que termina, se puede interrumpir limpiamente.
- **Thread-safe**: dos llamadas concurrentes no producen data races ni estado inconsistente.
- **Rollback automático**: si falla en cualquier fase, los stores y recursos anteriores se restauran o limpian.
- **Visible**: logs claros de cada fase, warnings si algo se skipea, progreso si tarda.
- **Rápido para lists**: `list_characters()` no escanea disco en cada llamada.
- **Testeable**: cada fase es un método atómico que se puede testear y mockear por separado.
