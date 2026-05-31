# Plan mejoras v8

## Objetivo

Hacer que el core del system prompt viva en posiciones invisibles del KV cache, expandiendo `n_ctx` internamente para que el usuario tenga siempre `n_ctx` tokens libres para conversación.

## Diagnóstico

### Problema: el core ocupa espacio real en `n_ctx`

Con v6 implementamos `reset_keep()` que evita que `reset()` destruya el core. Pero **el core sigue ocupando posiciones** en el KV cache y `create_chat_completion()` lo re-evalúa en cada turno.

```
Hoy (v6):
┌─────────────────────────────────────────────┐
│ n_ctx configurado = 4096                     │
│ [  CORE 2042  |  conversación...           ] │
│                ↑ el usuario perdió 2042      │
│                  tokens de su presupuesto    │
└─────────────────────────────────────────────┘
usage_pct = 53.5%  ← sin haber chateado
```

La solución: cargar el modelo con `n_ctx_real = n_ctx_config + n_keep`, evaluar el core una vez, y que la conversación use solo `n_ctx_config` tokens. El core queda en posiciones [0..n_keep) — invisibles, intocables.

```
Objetivo (v8):
┌─────────────────────────────────────────────┐
│ n_ctx real = 4096 + 2042 = 6138             │
│ [  CORE 2042  |  libre 4096                ]│
│                ↑ el usuario siempre ve 4096  │
│                  disponibles para charlar    │
└─────────────────────────────────────────────┘
usage_pct = 0%  ← antes del primer mensaje
```

### Cómo funciona

```
Warmup:
  evaluar core en [0..n_keep)
  n_tokens = n_keep

reset_keep():
  kv_cache_seq_rm(-1, n_keep, n_tokens)
  n_tokens = n_keep
  → core intacto, conversación borrada

create_chat_completion([user_msgs]):
  empieza en posición n_keep
  evalúa solo la conversación
  → core nunca se re-evalúa

get_token_usage():
  reporta max_tokens = n_ctx_config (lo que ve el usuario)
  n_keep se descuenta del reporte
```

## Cambios propuestos

### 1. Opcional por config

```json
{
  "expand_n_ctx_for_core": true,
  "expand_n_ctx_for_core": false   ← default: desactivado
}
```

Cuando es `false`, el sistema funciona exactamente como hoy (v6). La expansión es **opt-in**.

### 2. ModelManager: cargar con `n_ctx` expandido

En `load_model()`, si `expand_n_ctx_for_core = True`:

```python
# Guardar el n_ctx que el usuario configuró
self._user_n_ctx = self._config.n_ctx

# El n_ctx real se determina después del primer warmup
# Inicialmente cargamos con el n_ctx del usuario
# (porque todavía no sabemos cuánto pesa el core)
```

Problema: no sabemos `n_keep` hasta después del primer warmup, que requiere el modelo cargado. Solución:

1. Cargar modelo con `n_ctx_config + n_ctx_config * 0.5` (estimación inicial amplia)
2. Hacer warmup → medir n_keep
3. Si `expand_n_ctx_for_core`: **re-cargar el modelo** con `n_ctx = n_ctx_config + n_keep`
4. Hacer warmup de nuevo → ahora el core está en posiciones [0..n_keep)

**Alternativa más simple**: cargar siempre con `n_ctx_config + n_keep_max` donde `n_keep_max` es una estimación por exceso (ej: 4096 + 4096 = 8192). El core real siempre será menor.

**Alternativa recomendada**: dos pasadas:
- Primera carga: con `n_ctx = n_ctx_config + n_ctx_config` (margen amplio)
- Warmup → medir `n_keep`
- Segunda carga (interna, transparente): con `n_ctx = n_ctx_config + n_keep`
- Segundo warmup → core en posición correcta

### 3. chat() y stream_chat(): omitir system prompt si expandido

Cuando `expand_n_ctx_for_core = True` y el core ya fue calentado, los mensajes que se pasan a `generate()` **NO deben incluir el system prompt**. El modelo ya lo tiene en posiciones [0..n_keep).

```python
def _get_inference_messages(self) -> list[dict]:
    messages = self._memory.get_context_messages()
    if self._expand_n_ctx_for_core and self._model_manager._n_keep:
        # Filtrar system prompt — ya está en el KV cache
        messages = [m for m in messages if m.get("role") != "system"]
    return messages
```

### 4. reset_keep() ajustado

Cuando `expand_n_ctx_for_core = True`, el `n_keep` ya incluye todo el core. El comportamiento actual de `reset_keep()` es correcto — solo necesita proteger [0..n_keep). No requiere cambios.

### 5. get_token_usage() ajustado

Cuando `expand_n_ctx_for_core = True`:

```python
# Reportar el n_ctx que el usuario CONFIGURÓ, no el expandido
"max_tokens": self._config.n_ctx if not expandido else self._user_n_ctx,
# n_keep no se descuenta del presupuesto del usuario
"effective_context_limit": user_n_ctx - reserved,
# promp_budget_available solo considera conversación
"prompt_budget_available": user_n_ctx - reserved - history_tokens,
```

### 6. warmup con expansión

Cuando `expand_n_ctx_for_core = True`:

```python
# Después del primer warmup:
n_keep = model.n_tokens - 1  # medir core

# Si es primera vez con expansión, recargar modelo con n_ctx expandido
if self._expand_n_ctx_for_core and not self._core_expanded:
    expanded_ctx = self._config.n_ctx + n_keep
    self._log_info(f"Expandiendo n_ctx a {expanded_ctx} para core invisible ({n_keep} tokens)")
    # Recargar modelo con nuevo n_ctx
    self.unload_model()
    self._config.n_ctx = expanded_ctx
    self.load_model()  # carga con el n_ctx expandido
    self._core_expanded = True
    # Segundo warmup con el n_ctx correcto
    self._warmup_character_cache(prompt)
    return
```

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `types/core.py` | Nueva config: `expand_n_ctx_for_core: bool = False` — [Listo] |
| `model/manager.py` | Atributos `_user_n_ctx`, `_core_expanded` — [Listo] |
| `model/model_ops.py` | `load_model(n_ctx_override=...)` + `reload_model_with_expanded_ctx()` — [Listo] |
| `engine/character.py` | `_warmup_character_cache()` con doble-paso si expandido — [Listo] |
| `engine/chat.py` | `_get_inference_messages()` omite system si expandido — [Listo] |
| `engine/base.py` | `get_token_usage()` reporta `_user_n_ctx` si expandido — [Listo] |

## Riesgos

1. **Recargar el modelo es caro**: la doble carga en warmup puede tomar segundos.
   - Mitigación: solo ocurre la primera vez que se calienta un personaje con expansión. Después el `base.state` persiste.

2. **Expandir `n_ctx` aumenta consumo de VRAM**: el KV cache crece proporcionalmente.
   - Mitigación: el feature es opt-in. El usuario decide si tiene VRAM suficiente.

3. **`create_chat_completion()` sin system prompt puede descolocar al modelo**: algunos modelos necesitan ver el system prompt en cada turno.
   - Mitigación: probar experimentalmente. Si el modelo responde mal, la opción es desactivarla.

4. **Compatibilidad con chat templates**: el formato `<|turn|>` asume que el primer mensaje es system. Si se omite, puede romper el template.
   - Mitigación: evaluar si el chat template espera system. Si es el caso, enviar un system vacío o ajustar.

## Resultado esperado

- Con `expand_n_ctx_for_core: true`, el core del system prompt NO ocupa espacio visible
- `kv_cache_usage_pct` empieza en 0% y solo crece con la conversación
- `prompt_budget_available` = `n_ctx - reserved` (sin descuento del core)
- La recarga del modelo ocurre una sola vez por personaje
- Todo es transparente para el usuario: solo ve que tiene más espacio del que esperaba

```
Antes (v6):
  usage_pct = 53.5%  ← la mitad gastada en system prompt
  prompt_budget_available = 1603  ← apenas 1.5KB para conversar

Después (v8):
  usage_pct = 0%  ← solo cuenta conversación
  prompt_budget_available = 3796  ← los 4096 enteros menos reserva
```
