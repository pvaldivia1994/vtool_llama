# Referencia de Comandos — vtool_llama v0.2.2

## Índice

1. [Sistemas de Comandos](#1-sistemas-de-comandos)
2. [Slash Commands Incorporados](#2-slash-commands-incorporados)
3. [Tool Calling (Herramientas Externas)](#3-tool-calling-herramientas-externas)
4. [Auto-Tools (Herramientas Internas)](#4-auto-tools-herramientas-internas)
5. [Cómo Agregar Slash Commands Personalizados](#5-cómo-agregar-slash-commands-personalizados)
6. [Cómo Usar Tool Calling](#6-cómo-usar-tool-calling)
7. [Referencia Rápida](#7-referencia-rápida)

---

## 1. Sistemas de Comandos

La librería tiene **tres sistemas de comandos independientes**:

| Sistema | Disparador | Pasa por LLM | Definido en |
|---------|-----------|:------------:|-------------|
| **Slash Commands** | Texto que empieza con `/` | No (ejecución directa) | `slash_commands.py` + registros en `engine.py` |
| **Tool Calling** | Tools definidas por el usuario | Sí (el LLM decide llamarlas) | Parámetro `tools` de `chat()` / `stream_chat()` |
| **Auto-Tools** | Herramientas internas inyectadas automáticamente | Sí (el LLM decide usarlas) | `engine.py` (`remember_memory`) |

---

## 2. Slash Commands Incorporados

### 2.1 ¿Dónde están definidos?

Todos se registran en `engine.py`, método `_register_default_slash_commands()` (línea 1451). Cada comando tiene un handler separado dentro de la misma clase.

```
engine.py
└── VToolLlama
    ├── _register_default_slash_commands()  ← registro de todos
    ├── _cmd_mem()         → /mem
    ├── _cmd_rebuild()     → /rebuild
    ├── _cmd_state()       → /state
    ├── _cmd_memories()    → /memories
    ├── _cmd_mood()        → /mood
    ├── _cmd_rel()         → /rel
    ├── _cmd_help()        → /help
    ├── _cmd_save_episode() → /save_episode
    └── _cmd_episodes()    → /episodes
```

El sistema base está en `slash_commands.py` (clase `SlashCommandRegistry`).

### 2.2 Catálogo Completo

#### `/mem <texto>`

Guarda una memoria persistente en `long_term.json`. Prioridad máxima (1.0) y `always_include=True`.

```
Uso:   /mem El usuario se llama Juan y es desarrollador
Salida: ✓ Memoria guardada (id: a1b2c3d4): El usuario se llama Juan y es desarrollador
```

**Código** (`engine.py:1529-1538`):
```python
def _cmd_mem(self, args: str) -> str:
    if not args.strip():
        return "Uso: /mem <texto a recordar>"
    entry = self._character_manager.add_memory(
        content=args.strip(), always_include=True, priority=1.0,
    )
    return f"✓ Memoria guardada (id: {entry.id}): {entry.content}"
```

---

#### `/memories`

Lista todas las memorias guardadas con su ID, tags y pin.

```
Uso:   /memories
Salida:
  Memorias:
  [a1b2c3d4] El usuario se llama Juan y es desarrollador 📌
  [e5f6g7h8] Le gusta el café sin azúcar [gustos, comida]
```

**Código** (`engine.py:1550-1560`):
```python
def _cmd_memories(self, args: str) -> str:
    memories = self._character_manager.memories
    if not memories:
        return "No hay memorias guardadas."
    lines = []
    for m in memories:
        tags = f" [{', '.join(m.tags)}]" if m.tags else ""
        pin = " 📌" if m.always_include else ""
        lines.append(f"  [{m.id}] {m.content}{tags}{pin}")
    return "Memorias:\n" + "\n".join(lines)
```

---

#### `/rel <trust> <familiarity>`

Actualiza el Relationship Engine: confianza y familiaridad (0.0 a 1.0). Sin argumentos muestra valores actuales.

```
Uso:   /rel 0.9 0.8
Salida: ✓ Relación actualizada: Trust=0.90, Familiarity=0.80

Uso:   /rel
Salida:
  Estado de relación actual:
  Confianza: 0.90
  Familiaridad: 0.80
```

**Código** (`engine.py:1589-1606`):
```python
def _cmd_rel(self, args: str) -> str:
    if not args:
        rel = self._character_manager.relationship_state
        return f"Estado de relación actual:\nConfianza: {rel.trust_level:.2f}\nFamiliaridad: {rel.familiarity:.2f}"
    parts = args.split()
    if len(parts) == 2:
        try:
            trust = float(parts[0])
            fam = float(parts[1])
            self._character_manager.relationship_state.trust_level = trust
            self._character_manager.relationship_state.familiarity = fam
            self._character_manager.save_state()
            return f"✓ Relación actualizada: Trust={trust:.2f}, Familiarity={fam:.2f}"
        except ValueError:
            pass
    return "Uso: /rel <trust> <familiarity> (ej: /rel 0.8 0.5)"
```

---

#### `/mood <layer> <value> [intensity]`

Aplica un CharacterMod temporal que sobreescribe una capa del DNA.

| Parámetro | Descripción | Ejemplo |
|-----------|-------------|---------|
| `layer` | Capa a sobreescribir: `speech`, `traits`, `emotion` | `speech` |
| `value` | Nuevo valor que reemplaza al original | `asustado y tembloroso` |
| `intensity` | Opcional. Prioridad si hay múltiples mods (default: 1.0) | `1.5` |

```
Uso:   /mood speech asustado 1.5
Salida: ✓ Mod aplicado a 'speech': asustado (Intensidad 1.5)

Uso:   /mood traits agresivo y peligroso
Salida: ✓ Mod aplicado a 'traits': agresivo y peligroso (Intensidad 1.0)
```

**Código** (`engine.py:1562-1587`):
```python
def _cmd_mood(self, args: str) -> str:
    if not args:
        return "Uso: /mood <layer> <value> [intensity] (ej: /mood speech silencioso 1.0)"
    parts = args.split()
    if len(parts) < 2:
        return "Error: Formato incorrecto. Uso: /mood <layer> <value>"
    layer = parts[0]
    value = " ".join(parts[1:])
    intensity = 1.0
    if len(parts) >= 3:
        try:
            intensity = float(parts[-1])
            value = " ".join(parts[1:-1])
        except ValueError:
            pass
    from .types import CharacterMod
    mod = CharacterMod(id=f"temp_{layer}", target_layer=layer,
                       override_value=value, intensity=intensity)
    self._character_manager.set_mod(mod)
    self._inject_personality_into_system_prompt()
    return f"✓ Mod aplicado a '{layer}': {value} (Intensidad {intensity:.1f})"
```

---

#### `/rebuild`

Ejecuta una llamada interna al LLM que analiza el historial reciente y actualiza `relationship_state.json` (trust, familiarity, dynamics). También regenera el KV Cache.

```
Uso:   /rebuild
Salida: ✓ Estado de personalidad reconstruido.
```

**Código** (`engine.py:1540-1543`):
```python
def _cmd_rebuild(self, args: str) -> str:
    self.rebuild_personality_state()
    return "✓ Estado de personalidad reconstruido."
```

---

#### `/state`

Muestra el estado actual del agente en formato JSON: nombre del personaje y si necesita rebuild.

```
Uso:   /state
Salida:
  {
    "name": "elara",
    "needs_rebuild": false
  }
```

**Código** (`engine.py:1545-1548`):
```python
def _cmd_state(self, args: str) -> str:
    state = self.get_state_info()
    return json.dumps(state, ensure_ascii=False, indent=2)
```

---

#### `/save_episode`

Toma los últimos 5 mensajes del historial, genera un resumen con el LLM, y guarda un snapshot versionado (`episode_NNN.json`). Nunca sobreescribe archivos anteriores.

```
Uso:   /save_episode
Salida: ✓ Episodio #3 guardado. Resumen: El usuario y Elara exploraron la biblioteca...
```

**Código** (`engine.py:1612-1618`):
```python
def _cmd_save_episode(self, args: str) -> str:
    try:
        episode = self.save_episode()
        return f"✓ Episodio #{episode.episode_id} guardado. Resumen: {episode.summary[:100]}..."
    except Exception as e:
        return f"Error al guardar episodio: {e}"
```

---

#### `/episodes [load N | delete N]`

Gestiona los episodios guardados.

| Subcomando | Descripción |
|------------|-------------|
| *(sin args)* | Lista todos los episodios con ID, fecha, mensajes y resumen |
| `load N` | Hace rollback al episodio N (restaura ese contexto) |
| `delete N` | Elimina el episodio N |

```
Uso:   /episodes
Salida:
  Episodios guardados:
  #001 [2026-05-26T14:30] (5 msgs) El usuario y Elara exploraron... ← actual
  #002 [2026-05-27T10:15] (5 msgs) Elara enseñó un hechizo...
  
  Uso: /episodes load N | /episodes delete N

Uso:   /episodes load 2
Salida: ✓ Episodio #2 restaurado (rollback).

Uso:   /episodes delete 1
Salida: ✓ Episodio #1 eliminado.
```

**Código** (`engine.py:1620-1652`):
```python
def _cmd_episodes(self, args: str) -> str:
    parts = args.strip().split() if args else []
    if len(parts) == 2 and parts[0] == "load":
        try:
            ep_id = int(parts[1])
            self._character_manager.load_episode(ep_id)
            self._inject_personality_into_system_prompt()
            return f"✓ Episodio #{ep_id} restaurado (rollback)."
        except (ValueError, Exception) as e:
            return f"Error: {e}"
    if len(parts) == 2 and parts[0] == "delete":
        try:
            ep_id = int(parts[1])
            ok = self._character_manager.delete_episode(ep_id)
            return f"✓ Episodio #{ep_id} eliminado." if ok else f"Episodio #{ep_id} no encontrado."
        except (ValueError, Exception) as e:
            return f"Error: {e}"
    episodes = self._character_manager.list_episodes()
    if not episodes:
        return "No hay episodios guardados."
    lines = ["Episodios guardados:"]
    for ep in episodes:
        current = " ← actual" if (self._character_manager.current_episode
            and ep["episode_id"] == self._character_manager.current_episode.episode_id) else ""
        lines.append(f"  #{ep['episode_id']:03d} [{ep['timestamp'][:16]}] ({ep['message_count']} msgs) {ep['summary']}{current}")
    lines.append("\nUso: /episodes load N | /episodes delete N")
    return "\n".join(lines)
```

---

#### `/scene_view`

No es un slash command tradicional — el motor lo intercepta **antes** de la ejecución normal y transforma el prompt en un SYSTEM COMMAND interno que fuerza una descripción inmersiva de escena en tercera persona con dobles asteriscos.

```
Uso:   /scene_view
Salida:  ** Elara se ajusta el manto mientras observa el horizonte. El sol
         se oculta tras las montañas, pintando el cielo de tonos naranjas
         y púrpuras. El viento agita su cabello mientras sus dedos rozan
         el grimorio en su cinturón... **
```

**Código** (`engine.py:214-216` para `chat()`, `engine.py:353-355` para `stream_chat()`):
```python
if prompt.strip().lower() == "/scene_view":
    prompt = "(SYSTEM COMMAND: El usuario ha solicitado una vista de escena. \
Describe detalladamente la escena actual, el entorno, la iluminación \
y exactamente lo que estás haciendo en este preciso instante en tercera \
persona de forma inmersiva, usando dobles asteriscos. \Ejemplo: ** [Nombre] \
barre el patio con melancolía... **)"
    slash_result = None
```

---

#### `/help`

Lista todos los comandos registrados con su descripción.

```
Uso:   /help
Salida:
  Comandos disponibles:
    /episodes — Lista todos los episodios guardados. Uso: /episodes [load N | delete N]
    /help — Muestra la lista de comandos disponibles.
    /mem — Agrega una memoria persistente. Uso: /mem <texto>
    /memories — Lista todas las memorias persistentes.
    /mood — Cambia un valor de mood. Uso: /mood <key> <value>
    /rebuild — Reconstruye el estado de personalidad del agente.
    /rel — Modifica o consulta el relationship state. Uso: /rel <trust> <familiarity>
    /save_episode — Guarda un snapshot de la conversación actual como episodio versionado.
    /scene_view — Obliga al personaje a describir la escena actual...
    /state — Muestra el estado actual del agente.
```

**Código** (`engine.py:1608-1610`):
```python
def _cmd_help(self, args: str) -> str:
    return self._slash_commands.get_help_text()
```

---

## 3. Tool Calling (Herramientas Externas)

### 3.1 ¿Dónde está definido?

El sistema de herramientas se maneja en `engine.py`, dentro de los métodos `chat()` y `stream_chat()`. La validación contra alucinaciones está en `_validate_tool_calls()` (`engine.py:1411-1449`).

### 3.2 Formato de Definición

Las tools siguen el **formato OpenAI** estándar:

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Obtiene el clima actual de una ubicación.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Ciudad, ej: Madrid, Tokio"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"]
                    }
                },
                "required": ["location"]
            }
        }
    }
]
```

### 3.3 Ciclo Completo de Tool Calling

```python
import json
from vtool_llama import VToolLlama

llm = VToolLlama(auto_load=True)

# Mapa de funciones locales
def get_weather(location: str, unit: str = "celsius") -> str:
    return json.dumps({"location": location, "temperature": "22", "unit": unit})

FUNCTIONS_MAP = {"get_weather": get_weather}

# 1. Enviar prompt + tools
result = llm.chat("¿Cómo está el clima en Tokio?", tools=TOOLS_DEFINITION)

# 2. ¿El modelo llamó a una herramienta?
if isinstance(result, dict) and "tool_calls" in result:
    for tc in result["tool_calls"]:
        fn_name = tc["function"]["name"]
        args = json.loads(tc["function"]["arguments"])

        # 3. Ejecutar la función local
        output = FUNCTIONS_MAP[fn_name](**args)

        # 4. Registrar la respuesta en el historial
        llm.add_tool_message(content=output, tool_call_id=tc["id"])

    # 5. El modelo genera la respuesta final
    respuesta = llm.chat("Redacta la respuesta final.")
    print(respuesta)
```

### 3.4 Anti-alucinación

El método `_validate_tool_calls()` (`engine.py:1411-1449`) filtra cualquier tool_call que no coincida con las herramientas definidas por el usuario:

```python
def _validate_tool_calls(self, tool_calls: list[dict], tools: list[dict]) -> list[dict]:
    valid_names = set()
    for tool in tools:
        if "function" in tool:
            valid_names.add(tool["function"].get("name", ""))

    validated = []
    for tc in tool_calls:
        fn_name = tc.get("function", {}).get("name", "")
        if fn_name in valid_names:
            validated.append(tc)
        else:
            self._log_warning(
                f"Tool call '{fn_name}' no existe en las herramientas "
                f"definidas. Ignorando (posible alucinación del modelo)."
            )
    return validated if validated else None
```

---

## 4. Auto-Tools (Herramientas Internas)

### 4.1 ¿Dónde está definido?

La herramienta `remember_memory` se define e inyecta en `engine.py`, dentro de `chat()` (línea 189) y `stream_chat()` (línea 363).

### 4.2 Definición

```python
internal_tools = [
    {
        "type": "function",
        "function": {
            "name": "remember_memory",
            "description": "Guarda información en tu memoria a largo plazo. IMPORTANTE: DEBES usar esta herramienta INMEDIATAMENTE siempre que el usuario te pida que recuerdes, guardes o memorices un dato.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "El dato exacto a recordar, escrito de forma concisa."
                    }
                },
                "required": ["content"]
            }
        }
    }
]
```

### 4.3 Ciclo de Ejecución (Reasoning Loop)

El Auto-Tool se inyecta **automáticamente en cada llamada** combinándose con las tools del usuario:

```python
active_tools = (tools or []) + internal_tools
```

Cuando el LLM decide usar `remember_memory`:

1. Se parsean los argumentos JSON
2. Se llama a `add_memory(content, priority=1.0)` que guarda en `long_term.json`
3. Se registra la tool_call y su respuesta en el historial
4. El bucle continúa (máximo 3 iteraciones) para que el LLM genere la respuesta textual
5. Se antepone un prefijo: `** {nombre} recordará esto **\n\n`

Ejemplo:

```
Usuario: "Recuerda que soy alérgico al polen"

Asistente (output):
** Elara recordará esto **

Entendido, tendré en cuenta que eres alérgico al polen. Evitaré mencionar lugares con muchas flores.
```

### 4.4 Límite de Seguridad

```python
MAX_LOOPS = 3  # engine.py:239
```

Si el LLM intenta llamar herramientas internas más de 3 veces seguidas, el bucle se rompe y retorna un mensaje de error.

---

## 5. Cómo Agregar Slash Commands Personalizados

### 5.1 Usando el Decorador (recomendado)

```python
from vtool_llama import VToolLlama

llm = VToolLlama()

@llm.slash_commands.command("git", description="Ejecuta un comando git")
def handle_git(args: str) -> str:
    import subprocess
    result = subprocess.run(["git"] + args.split(), capture_output=True, text=True)
    return result.stdout or result.stderr
```

### 5.2 Usando `register()` directamente

```python
def handle_custom(args: str) -> str:
    return f"Ejecutado con argumentos: {args}"

llm.slash_commands.register("custom", handle_custom, description="Un comando personalizado")
```

### 5.3 Agregando al Registro Interno (para modificaciones a la librería)

Si estás modificando la librería y quieres agregar un comando al sistema base:

```python
# En engine.py, método _register_default_slash_commands()
def _register_default_slash_commands(self) -> None:
    # ... comandos existentes ...

    self._slash_commands.register(
        "mi_comando",
        self._cmd_mi_comando,
        "Descripción de mi comando.",
    )

# Luego agregar el handler en la misma clase
def _cmd_mi_comando(self, args: str) -> str:
    """Handler para /mi_comando."""
    return f"Procesado: {args}"
```

### 5.4 Reglas del Handler

| Regla | Explicación |
|-------|-------------|
| Firma | `def handler(args: str) -> str` |
| Argumentos | Todo lo que sigue al nombre del comando, como string único |
| Retorno | String que se devuelve al usuario (se muestra en consola) |
| Errores | Atrapar excepciones internamente o se capturan automáticamente |
| Efectos secundarios | El handler puede modificar cualquier estado interno |

---

## 6. Cómo Usar Tool Calling

### 6.1 Definir Herramientas en Formato OpenAI

```python
SALUDO_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "saludar_usuario",
            "description": "Saluda al usuario por su nombre.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {
                        "type": "string",
                        "description": "Nombre del usuario."
                    },
                    "idioma": {
                        "type": "string",
                        "enum": ["es", "en", "fr"]
                    }
                },
                "required": ["nombre"]
            }
        }
    }
]

FUNCTIONS = {
    "saludar_usuario": lambda nombre, idioma="es": {
        "es": f"¡Hola {nombre}!",
        "en": f"Hello {nombre}!",
        "fr": f"Bonjour {nombre}!",
    }.get(idioma, f"¡Hola {nombre}!")
}
```

### 6.2 Flujo en chat() (síncrono)

```python
# 1. El usuario pregunta algo que requiere la tool
respuesta = llm.chat("Saluda a Juan en francés, por favor", tools=SALUDO_TOOLS)

# 2. El modelo devolvió tool_calls?
if isinstance(respuesta, dict) and "tool_calls" in respuesta:
    for tc in respuesta["tool_calls"]:
        fn_name = tc["function"]["name"]
        args = json.loads(tc["function"]["arguments"])
        result = FUNCTIONS[fn_name](**args)

        # 3. Registrar el resultado de la tool
        llm.add_tool_message(content=result, tool_call_id=tc["id"])

    # 4. Pedir al modelo la respuesta final
    final = llm.chat("Dame la respuesta final.")
    print(final)
else:
    # El modelo respondió directamente sin tools
    print(respuesta)
```

### 6.3 Flujo en stream_chat() (asíncrono)

```python
respuesta = llm.stream_chat("Saluda a Juan en francés", tools=SALUDO_TOOLS)

full_text = ""
tool_call_obj = None

for chunk in respuesta:
    if isinstance(chunk, dict) and "tool_calls" in chunk:
        tool_call_obj = chunk
    else:
        print(chunk, end="")
        full_text += chunk

# Si hubo tool_calls
if tool_call_obj:
    for tc in tool_call_obj["choices"][0]["message"]["tool_calls"]:
        fn_name = tc["function"]["name"]
        args = json.loads(tc["function"]["arguments"])
        result = FUNCTIONS[fn_name](**args)
        llm.add_tool_message(content=result, tool_call_id=tc["id"])

    # El modelo genera la respuesta final
    for token in llm.stream_chat("Dame la respuesta final"):
        print(token, end="")
```

### 6.4 Combinar Tools Externas con Auto-Tools

No necesitas hacer nada especial — las herramientas internas (`remember_memory`) se combinan automáticamente con las externas. El motor distingue entre:

- **Tool call interna** (`remember_memory`): Se ejecuta y el reasoning loop continúa.
- **Tool call externa** (definida por el usuario): Se devuelve al usuario como `dict` y el motor **no** continúa (detiene el reasoning loop).

### 6.5 Validación contra Alucinaciones

El motor descarta automáticamente cualquier tool_call cuyo nombre no exista ni en las tools del usuario ni en las internas. Esto previene que el LLM invente nombres de herramientas.

---

## 7. Referencia Rápida

### Todos los Slash Commands

| Comando | Args | Capa | Descripción |
|---------|------|:----:|-------------|
| `/mem` | `texto` | Memory | Guarda memoria persistente (priority=1.0) |
| `/memories` | — | Memory | Lista todas las memorias |
| `/save_episode` | — | Memory | Guarda snapshot episódico |
| `/episodes` | `[load N \| delete N]` | Memory | Gestiona episodios |
| `/rel` | `[trust fam]` | State | Consulta o modifica relación |
| `/mood` | `layer value [intensity]` | Mods | Aplica modificador temporal |
| `/rebuild` | — | State | Reconstruye personalidad vía LLM |
| `/state` | — | State | Muestra dump JSON del estado |
| `/scene_view` | — | — | Fuerza descripción inmersiva de escena |
| `/help` | — | — | Lista comandos disponibles |

### Archivos Clave

| Archivo | Contenido |
|---------|-----------|
| `slash_commands.py` | Clase `SlashCommandRegistry` (registro y ejecución) |
| `engine.py` (línea 1451) | Registro de comandos por defecto (`_register_default_slash_commands`) |
| `engine.py` (líneas 1529-1652) | Handlers de cada comando (`_cmd_mem`, `_cmd_rel`, etc.) |
| `engine.py` (línea 189) | Definición e inyección de Auto-Tools (`remember_memory`) |
| `engine.py` (línea 1411) | Validación anti-alucinación (`_validate_tool_calls`) |
| `tokenizer_utils.py` | Utilidades de tokenización (no comandos, pero relevante para contexto) |

### APIs Públicas para Comandos

```python
# Desde VToolLlama (para el usuario de la librería)
llm.slash_commands                          # Acceso al registro de comandos
llm.slash_commands.register(name, fn, desc) # Registrar comando
llm.slash_commands.command(name, desc)      # Decorador para registrar
llm.slash_commands.get_help_text()          # Texto de ayuda formateado
llm.slash_commands.list_commands()          # Dict con todos los comandos

# Para tool calling
llm.chat(prompt, tools=my_tools)            # Enviar con herramientas
llm.stream_chat(prompt, tools=my_tools)     # Streaming con herramientas
llm.add_tool_message(content, call_id)      # Registrar respuesta de tool

# Para Auto-Tools (automático, no requiere intervención del usuario)
# remember_memory se inyecta en cada chat()/stream_chat()
```
