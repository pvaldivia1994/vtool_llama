# Plan mejoras v19 — Thinking persistente en DB + optimización de contexto

## Objetivo

Guardar el contenido de `<think>` en una columna separada de SQLite, con control de visibilidad al usuario, y optimizar el contexto histórico omitiendo `<think>` de mensajes anteriores al último.

## Diagnóstico

### Problema actual

`chat_with_thinking()` (engine/chat.py:884-930) extrae el thinking del modelo y lo guarda inline en el content:

```python
full_history_content = content
if thinking:
    full_history_content = f"<think>\n{thinking}\n</think>\n{content}"
self._memory.add_assistant_message(self._validate_prose_response(full_history_content))
```

**Problemas:**

1. **Thinking ocupando tokens en contexto histórico**: El `<think>` de cada turno pasado se incluye en el contexto de TODAS las generaciones siguientes. Un modelo razonador gasta ~400 tokens por turno en thinking. Con 10 turnos de historial, son ~4000 tokens perdidos en pensamientos que el modelo no necesita volver a leer.

2. **Sin columna dedicada**: El thinking está mezclado en `content`. No se puede consultar, filtrar, ni mostrar/ocultar independientemente.

3. **Sin control de visibilidad**: Si el thinking se guarda pero no se quiere mostrar (solo como registro interno), no hay forma de separarlo.

### Diagrama del flujo actual

```
Modelo → "<think>razonamiento</think>Luna: texto"
                    │
                    ▼
     chat_with_thinking() extrae thinking
                    │
                    ▼
     content = "<think>...\nLuna: texto"
                    │
                    ▼
     ChatStore.add_message(content=fusionado)
     Historial futuro ve el <think> de cada turno pasado ← desperdicio
```

### Flujo deseado

```
Modelo → "<think>razonamiento</think>Luna: texto"
                    │
                    ▼
     chat_with_thinking() extrae thinking
                    │
                    ├──→ ChatStore.add_message(content="Luna: texto", thinking="razonamiento")
                    │
                    └──→ get_context_messages():
                           ├── último msg: incluir <think>
                           └── msgs anteriores: solo content, sin <think>
```

## Cambios propuestos

### 1. Nueva columna `thinking` en la tabla `messages`

```sql
ALTER TABLE messages ADD COLUMN thinking TEXT DEFAULT '';
```

- `thinking` TEXT: contenido del bloque `<think>` (vacío si no hay)
- No rompe schema existente (columna nullable con default '')
- Backward compatible: mensajes viejos tienen `thinking = ''`

### 2. Guardar thinking separado en ChatStore.add_message()

```python
def add_message(self, ..., thinking: str = "") -> int:
    # ... existing code ...
    cursor.execute("""
        INSERT INTO messages
        (conversation_id, branch_id, message_index, parent_id,
         role, content, tool_calls, tool_call_id, status,
         token_count, speaker_tag, thinking, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (..., thinking, now))
```

### 3. Extender ChatMemory para recibir thinking

```python
def add_assistant_message(self, content, tool_calls=None, speaker_tag="", thinking="") -> int:
    # ... existing code, pasar thinking al store ...
```

- `Message` dataclass: nuevo campo `thinking: str = ""`
- `_message_to_dict()`: incluir `thinking` si no está vacío

### 4. Optimización: omitir `<think>` de mensajes históricos

En `get_context_messages()`, solo incluir `<think>` en el ÚLTIMO mensaje assistant:

```python
def get_context_messages(self) -> list[dict]:
    context_msgs = []
    for i, m in enumerate(self._messages):
        d = self._message_to_dict(m)
        if m.role == "assistant" and m.thinking:
            if i == len(self._messages) - 1:
                # Último mensaje: incluir thinking
                d["content"] = f"<think>\n{m.thinking}\n</think>\n{m.content}"
            else:
                # Mensajes anteriores: solo content, thinking descartado
                d["content"] = m.content or ""
        context_msgs.append(d)
    return context_msgs
```

Esto ahorra ~400 tokens por turno de historial.

### 5. Nuevo campo config `show_thinking` (default: true)

```python
@dataclass
class ConfigSchema:
    ...
    show_thinking: bool = True  # Muestra el thinking al usuario
```

Cuando `show_thinking=False`:
- El thinking se guarda en DB (para consulta futura)
- Pero NO se muestra en la respuesta al usuario
- `chat_with_thinking()` retorna `("", content)` en vez de `(thinking, content)`

### 6. Actualizar stream_chat_with_thinking()

Misma lógica que sync:
- Extraer thinking del stream
- Guardar en la DB con thinking separado
- Yield controlado por `show_thinking`

### 7. Migración de DB

- `ChatStore.__init__()` ejecutar `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` al conectar
- Mensajes existentes sin thinking: `thinking = ''`

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `types/core.py` | `Message.thinking`, `ConfigSchema.show_thinking` |
| `db/chat_store.py` | Schema: columna `thinking`, `add_message()` acepta `thinking`, migración automática |
| `engine/chat_memory.py` | `add_assistant_message()` parámetro `thinking`, `get_context_messages()` optimización |
| `engine/chat.py` `chat_with_thinking()` | Guardar thinking separado, control `show_thinking` |
| `engine/chat.py` `stream_chat_with_thinking()` | Idem para streaming |

## Archivos que NO cambian

- `engine/chat.py` `chat()` y `stream_chat()` — no manejan thinking
- `compiler/` — no hay cambios de formato
- `orquestador/` — no hay cambios de contexto
- `model/` — la generación es agnóstica

## Riesgos

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|---------|------------|
| ALTER TABLE falla en DB existente | Baja | Medio | Ejecutar solo si columna no existe, try/except |
| Mensajes históricos sin thinking revientan | Baja | Bajo | `thinking` default `""`, get attr safe |
| Optimización rompe coherencia del modelo | Baja | Medio | El último mensaje SIEMPRE lleva thinking; solo históricos lo pierden |
| show_thinking=false confunde al usuario | Baja | Bajo | Loggear que thinking fue guardado, documentar |

## Resultado esperado

- El thinking de cada turno se guarda en `messages.thinking` (columna separada)
- El contexto histórico no incluye `<think>` de turnos pasados → ahorro de ~400 tokens/turno
- `show_thinking: false` permite guardar thinking sin mostrarlo al usuario
- Backward compatible: DBs existentes siguen funcionando
