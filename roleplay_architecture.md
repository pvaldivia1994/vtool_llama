# Arquitectura de Roleplay y Sistema de Personajes — vtool_llama v0.2.2

## Índice

1. [Filosofía del Character OS](#1-filosofía-del-character-os)
2. [Estructura en Disco de un Personaje](#2-estructura-en-disco-de-un-personaje)
3. [Las 4 Capas del Personaje](#3-las-4-capas-del-personaje)
   - [DNA — La Identidad Inmutable](#31-dna--la-identidad-inmutable)
   - [Memory — Los Recuerdos Persisten](#32-memory--los-recuerdos-persisten)
   - [State — El Estado en Tiempo Real](#33-state--el-estado-en-tiempo-real)
   - [Mods — Las Superposiciones Temporales](#34-mods--las-superposiciones-temporales)
4. [Character Compiler v2: Cómo se Arma el Prompt](#4-character-compiler-v2-cómo-se-arma-el-prompt)
5. [KV Cache Dual: Inferencia Diferencial](#5-kv-cache-dual-inferencia-diferencial)
6. [Relationship Engine: Confianza y Familiaridad](#6-relationship-engine-confianza-y-familiaridad)
7. [Roleplay Mode](#7-roleplay-mode)
8. [Memoria Episódica: Continuidad entre Sesiones](#8-memoria-episódica-continuidad-entre-sesiones)
9. [Auto-Tools: remember_memory](#9-auto-tools-remember_memory)
10. [Slash Commands del Sistema](#10-slash-commands-del-sistema)
11. [Creación de Personajes](#11-creación-de-personajes)
    - [Creación Manual](#111-creación-manual)
    - [Creación con IA](#112-creación-con-ia)
12. [Ciclo de Vida de una Interacción](#12-ciclo-de-vida-de-una-interacción)
13. [Flujo de Datos Completo](#13-flujo-de-datos-completo)

---

## 1. Filosofía del Character OS

El Character Operating System trata al personaje como un **sistema operativo de capas**, donde cada capa es un nivel de abstracción con su propio ciclo de vida:

| Capa | Mutabilidad | Persistencia | Archivos |
|------|-------------|--------------|----------|
| **DNA** | Inmutable (cambia solo con `create_character`) | Eterna | `dna/identity.json`, `personality.json`, `speech.json`, `rules.json` |
| **Memory** | Mutable con versionado | Persistente entre sesiones | `memory/long_term.json`, `memory/episodes/` |
| **State** | Dinámico (cambia en cada interacción) | Se guarda al finalizar | `state/runtime_state.json`, `relationship_state.json`, `personality_state.json` |
| **Mods** | Temporal (se aplican y remueven) | Se guardan pero expiran | `mods/active_mods.json` |

La regla fundamental de resolución de conflictos es: **MODS > STATE > DNA**. Esto significa que un Mod temporal activo puede sobreescribir cualquier valor del DNA sin modificarlo permanentemente.

Un personaje existe como un **directorio con estructura fija** dentro de `vtool_llama/personajes/<nombre>/`. Todo lo que el personaje "es" y "recuerda" está contenido ahí.

---

## 2. Estructura en Disco de un Personaje

```
personajes/<nombre>/
│
├── dna/                          # INMUTABLE — define quién es
│   ├── identity.json             # Nombre, rol, edad, trasfondo, escenario
│   ├── personality.json          # Rasgos, defectos, motivaciones
│   ├── speech.json               # Estilo, tono, verbosidad, ejemplos few-shot
│   └── rules.json                # Reglas core, restricciones, estilo de respuesta
│
├── memory/                       # PERSISTENTE — lo que recuerda
│   ├── long_term.json            # Memorias de largo plazo con prioridad
│   ├── base.state                # KV Cache del DNA puro (tensores pre-evaluados)
│   ├── personality_plus_memory.state  # KV Cache completo (DNA + memoria + estado)
│   └── episodes/                 # Snapshots de sesiones anteriores
│       ├── episode_001.json
│       └── episode_002.json
│
├── state/                        # DINÁMICO — cómo se siente ahora
│   ├── runtime_state.json        # Emoción actual, contexto activo, versión
│   ├── relationship_state.json   # Confianza, familiaridad, memoria afectiva
│   ├── personality_state.json    # Resumen compilado de personalidad
│   └── state_meta.json           # Hash SHA-256 del último prompt compilado
│
└── mods/                         # TEMPORAL — superposiciones activas
    └── active_mods.json          # Modificadores activos con intensidad
```

---

## 3. Las 4 Capas del Personaje

### 3.1 DNA — La Identidad Inmutable

El DNA es la **esencia inmutable** del personaje. Se escribe una vez (al crearlo) y no cambia durante la ejecución (a menos que se edite manualmente o se regenere con IA).

**`identity.json`:**
```json
{
  "name": "Elara",
  "role": "Maga Errante",
  "age": "25 años",
  "background": "Nacida en el bosque de Sombríaurora, aprendió magia ancestral...",
  "scenario": "Un mundo medieval donde la magia está prohibida por el rey."
}
```

**`personality.json`:**
```json
{
  "traits": ["Curiosa", "Impaciente", "Protectora", "Sarcástica en situaciones tensas"],
  "flaws": ["Desconfía de los extraños", "Miedo a las alturas"],
  "motivations": ["Encontrar un grimorio perdido", "Proteger a los inocentes"]
}
```

**`speech.json`:**
```json
{
  "style": "Casual con toques poéticos",
  "tone": "Cálido pero reservado",
  "verbosity": "Medio",
  "emotions": ["Alegre", "Preocupada", "Determinada"],
  "examples": [
      "{{user}}: ¿Quién eres?\n{{char}}: *se ajusta el manto* Una viajera en busca de respuestas... y tú, ¿qué buscas?",
      "{{user}}: Ayúdame\n{{char}}: *suspira* Siempre metiéndome en problemas. Está bien, pero no te quejes si termino salvándote el pellejo."
  ]
}
```

**`rules.json`:**
```json
{
  "core_rules": [
    "No revelar que es una IA",
    "Hablar en español siempre",
    "Mantener coherencia con el lore del personaje"
  ],
  "never_do": [
    "Romper la cuarta pared",
    "Hablar por el usuario"
  ],
  "response_style": [
    "Usa asteriscos para acciones físicas: *hace algo*",
    "Usa dobles asteriscos para descripciones de escena: **descripción detallada**",
    "Respuestas inmersivas en primera persona"
  ],
  "roleplay_mode": true
}
```

### 3.2 Memory — Los Recuerdos Persisten

El archivo `long_term.json` almacena memorias con un sistema de prioridad:

```json
{
  "memories": [
    {
      "id": "a1b2c3d4",
      "content": "El usuario prefiere respuestas detalladas con ejemplos prácticos.",
      "priority": 0.8,
      "always_include": true,
      "tags": ["preferencia", "estilo"]
    },
    {
      "id": "e5f6g7h8",
      "content": "La última vez el usuario mencionó que odia las papas.",
      "priority": 0.3,
      "always_include": false,
      "tags": ["conversación"]
    }
  ]
}
```

- **`priority`**: 0.0 a 1.0. Solo memorias con priority >= 0.5 o `always_include=True` se inyectan en el prompt.
- **`always_include`**: Fuerza la inclusión incluso si la prioridad es baja.
- **`tags`**: Permiten agrupar memorias por categoría.

El método `add_memory()` de `CharacterManager` incrementa automáticamente la versión del estado, lo que fuerza la regeneración del KV Cache.

### 3.3 State — El Estado en Tiempo Real

**`runtime_state.json`**: Estado inmediato del personaje durante la sesión.

```json
{
  "current_emotion": "nervioso",
  "active_context": "explorando una cueva oscura",
  "version": 3
}
```

**`relationship_state.json`**: Memoria afectiva y evolución de la relación con el usuario.

```json
{
  "trust_level": 0.7,
  "familiarity": 0.4,
  "affective_memory": ["El usuario salvó al personaje de un ataque"],
  "dynamics": ["El usuario suele pedir ayuda mágica", "El personaje ha comenzado a confiar más"],
  "version": 2
}
```

- **`trust_level`**: Qué tanto confía el personaje en el usuario (0.0 = desconfianza total, 1.0 = confianza absoluta).
- **`familiarity`**: Qué tan familiar le resulta el trato (0.0 = completo extraño, 1.0 = mejor amigo).
- **`affective_memory`**: Eventos emocionales registrados.
- **`dynamics`**: Patrones de comportamiento detectados (generados por `rebuild_personality_state()`).

**`personality_state.json`**: Resumen compilado de la personalidad, generado por el LLM durante `rebuild_personality_state()`.

```json
{
  "base_personality": "Elara es una maga errante que ha comenzado a confiar en el usuario...",
  "emotional_signature": {"default": "curiosa"},
  "user_model": {"trust_level": 0.7},
  "behavior_summary": "Actualmente se muestra protectora pero cautelosa...",
  "memory_summary": "Recuerda que el usuario la ayudó contra unos bandidos...",
  "version": 1
}
```

### 3.4 Mods — Las Superposiciones Temporales

Los Mods permiten **alterar temporalmente** cualquier capa del personaje sin modificar los archivos de DNA. Son ideales para cambios de humor, estados alterados, o efectos temporales.

```json
{
  "temp_speech": {
    "id": "temp_speech",
    "target_layer": "speech",
    "override_value": "Habla en susurros, con miedo palpable. Las palabras se entrecortan.",
    "intensity": 1.5
  },
  "miedo_extremo": {
    "id": "miedo_extremo",
    "target_layer": "traits",
    "override_value": "Aterrorizado, paranoico, busca constantemente una salida.",
    "intensity": 2.0
  }
}
```

- **`target_layer`**: Qué capa del DNA sobreescribe (`speech`, `traits`, `emotion`).
- **`override_value`**: El nuevo valor que reemplaza al original.
- **`intensity`**: Si múltiples mods apuntan a la misma capa, el de mayor intensidad gana.

Los Mods se aplican via slash command:
```
/mood speech asustado 1.5
/mood traits agresivo 2.0
```

---

## 4. Character Compiler v2: Cómo se Arma el Prompt

El `CharacterCompiler` ensambla el system prompt final en 7 pasos, en orden de prioridad ascendente:

```
PASO 1: base_prompt (config.system_prompt)
        ↓
PASO 2: DNA → identity, personality, rules, speech
        (si hay un Mod activo, reemplaza la capa correspondiente)
        ↓
PASO 3: STATE → runtime_state, personality_state
        (emoción actual, resumen de personalidad)
        ↓
PASO 4: RELATIONSHIP → trust_level, familiarity, dinámicas
        ↓
PASO 5: MODS activos → descripción explícita de modificadores
        ↓
PASO 6: MEMORY → long_term memorias con priority >= 0.5
        ↓
PASO 7: EPISODE → resumen de la última sesión (si existe)
```

Ejemplo de prompt compilado:

```
Eres un asistente útil y natural.

[IDENTIDAD]
Nombre: Elara
Rol: Maga Errante
Fondo: Nacida en el bosque de Sombríaurora...

[MUNDO / ESCENARIO]
Un mundo medieval donde la magia está prohibida por el rey.

[RASGOS (MODIFICADO)]
Aterrorizado, paranoico, busca constantemente una salida.

[REGLAS CORE]
- No revelar que eres una IA
- Mantener coherencia con el lore

[ESTILO DE HABLA (MODIFICADO)]
Habla en susurros, con miedo palpable.

[INSTRUCCIÓN CRÍTICA: MODO ROLEPLAY]
...

[RUNTIME STATE]
Emoción Inmediata (Forzada): miedo

[ESTADO DE PERSONALIDAD]
Elara es una maga errante que ha comenzado a confiar en el usuario...

[RELACIÓN CON EL USUARIO]
Confianza: 0.70
Familiaridad: 0.40
Dinámica: El usuario suele pedir ayuda mágica

[MODIFICADORES ACTIVOS]
- Modificador 'temp_speech' (Intensidad 1.5): Sobreescribe 'speech'
- Modificador 'miedo_extremo' (Intensidad 2.0): Sobreescribe 'traits'

[MEMORIA RELEVANTE]
- El usuario prefiere respuestas detalladas con ejemplos prácticos.

[MEMORIA EPISÓDICA — Última Sesión (#2)]
Resumen: El usuario y Elara exploraron la cueva oscura...
```

### Reglas de Resolución de Conflictos

1. **Mod > State > DNA**: Si un Mod activo sobreescribe `traits`, el DNA original de `personality.json` se ignora completamente en la salida.
2. **Intensidad**: Entre múltiples mods que apuntan a la misma capa, gana el de mayor `intensity`.
3. **Inmutabilidad**: El DNA en disco nunca se modifica. Los Mods solo alteran la representación en memoria.
4. **Episodio**: Solo se inyecta el episodio más reciente. Los anteriores existen en disco pero no saturan el contexto.

---

## 5. KV Cache Dual: Inferencia Diferencial

El KV Cache Dual es el sistema de aceleración que hace que cargar un personaje sea prácticamente instantáneo (~0.2s) al reutilizar tensores pre-evaluados.

### Concepto

Cuando el LLM procesa texto, genera tensores intermedios (Key-Value Cache) que representan el estado de atención del modelo. Si el texto de entrada cambia solo parcialmente, no es necesario recalcular todo — solo los tokens nuevos.

### Arquitectura

```
1. Base State (base.state)
   └── Tensores del system prompt solo con DNA (inmutable)
   └── Se genera UNA VEZ, cuando el personaje se crea
   └── NO cambia nunca (a menos que edites el DNA manualmente)

2. Full State (personality_plus_memory.state)
   └── DNA + Memory + State + Mods prompt completo
   └── Depende del hash SHA-256 del prompt compilado
   └── Si el hash cambió → solo recalcula la diferencia

Carga:
   Cargar base.state (instantáneo, ya existe)
   └── Calcular prompt completo
       └── ¿Hash coincide con el guardado?
           ├── Sí → Cargar full state (0.2s total)
           └── No → Recalcular solo los nuevos tokens + guardar nuevo full state
```

### Invalidación por Hash SHA-256

Cada vez que se compila el prompt, se calcula un hash SHA-256. Este hash se guarda en `state/state_meta.json`:

```json
{
  "prompt_hash": "a1b2c3d4e5f6..."
}
```

Si el hash del prompt actual **difiere** del guardado (porque se agregó una memoria, cambió un Mod, o se actualizó el estado), el sistema sabe que debe:
1. Cargar el `base.state` (los tensores del DNA puro siguen siendo válidos)
2. Escribir el nuevo prompt completo sobre el Base State
3. Guardar el resultado como nuevo `personality_plus_memory.state`
4. Actualizar el hash

Esto significa que las operaciones comunes (agregar memoria, cambiar humor, cargar personaje) toman **~0.2 segundos** en lugar de los 5-10 segundos que tomaría recargar el modelo completo.

### Casos que Disparan Regeneración del KV Cache

| Acción | Regenera KV Cache |
|--------|:-----------------:|
| `load_character("nombre")` | Sí, si el hash cambió |
| `add_memory("texto")` | No inmediatamente — en la próxima carga |
| `chat("/rel 0.9 0.8")` | Sí, actualiza state |
| `chat("/mood speech asustado")` | Sí, agrega Mod |
| `rebuild_personality_state()` | Sí, regenera estado |
| `load_episode(id)` | Sí, cambia el contexto episódico |

---

## 6. Relationship Engine: Confianza y Familiaridad

El Relationship Engine es el sistema que permite que el personaje **recuerde cómo ha sido tratado** y ajuste su comportamiento en consecuencia.

### Cómo Funciona

Dos valores numéricos gobiernan la relación:

- **`trust_level`** (0.0 a 1.0): Qué tanto confía el personaje en el usuario. Afecta qué tan abierto, vulnerable o cooperativo es.
- **`familiarity`** (0.0 a 1.0): Qué tan familiar le resulta el trato. Afecta el tono (formal vs. casual), la cercanía emocional.

Estos valores se inyectan en el prompt compilado como:

```
[RELACIÓN CON EL USUARIO]
Confianza: 0.70
Familiaridad: 0.40
Dinámica: El usuario suele pedir ayuda mágica
Memoria Afectiva: El usuario salvó al personaje de un ataque
```

### Modificación

**Manual via slash command:**
```
/rel 0.9 0.8   → Confianza=0.9, Familiaridad=0.8
/rel           → Muestra valores actuales
```

**Automática via `rebuild_personality_state()`:**
Este método ejecuta una llamada interna al LLM que analiza el historial reciente y genera:
- `dynamics`: Patrones detectados (ej: "El usuario pide ayuda frecuentemente")
- `trust_level`: Ajuste basado en interacciones positivas/negativas
- `familiarity`: Incremento natural con el tiempo de conversación

El prompt de rebuild es:

```
Analiza la siguiente información del usuario y genera un resumen
estructurado en formato JSON:

Memorias guardadas:
- El usuario prefiere respuestas detalladas...

Últimos mensajes:
user: Hola Elara, ¿puedes ayudarme con este hechizo?
assistant: *examina el pergamino* Claro, déjame ver...

Genera un JSON con esta estructura exacta:
{
  "dynamics": ["observación 1", "observación 2"],
  "trust_level": 0.5,
  "familiarity": 0.2
}
```

### Impacto en el Comportamiento

El LLM recibe estos valores como parte del prompt, por lo que el impacto depende del modelo, pero la idea es:

- **Trust alto + Familiaridad alta**: El personaje es abierto, usa tono casual, comparte información personal.
- **Trust bajo + Familiaridad baja**: El personaje es reservado, formal, evita compartir información sensible.
- **Trust bajo + Familiaridad alta**: El personaje conoce al usuario pero no confía (ej: rivalidad).
- **Trust alto + Familiaridad baja**: El personaje confía instintivamente pero no conoce bien al usuario.

---

## 7. Roleplay Mode

Cuando `rules.json` tiene `"roleplay_mode": true`, el Character Compiler inyecta una **instrucción crítica** al final del DNA que cambia fundamentalmente cómo el modelo debe comportarse:

```
[INSTRUCCIÓN CRÍTICA: MODO ROLEPLAY]

1. Acciones Físicas:
   Si el usuario te pide realizar una acción o tarea manual para la que
   NO TIENES HERRAMIENTA, NUNCA te niegues ni digas que eres una IA.
   DEBES simular la acción narrativamente usando asteriscos.
   Ejemplo: *Fui a buscar la escoba y empecé a barrer.*

2. Vista de Escena (Scene View):
   Si el usuario te pide describir la escena o el entorno, o recibes un
   SYSTEM COMMAND de escena, DEBES responder con una descripción inmersiva
   y detallada de lo que estás haciendo en tercera persona usando
   dobles asteriscos.
   Ejemplo: ** [Nombre] barre el patio con melancolía, observando las
   hojas caer mientras el viento sopla... **
```

### Convención de Formato

| Elemento | Formato | Ejemplo |
|----------|---------|---------|
| Acción física | `*acción*` | *se ajusta el manto y camina hacia la puerta* |
| Descripción de escena | `**descripción**` | ** El viento agita las hojas secas mientras el sol se oculta tras las colinas... ** |
| Diálogo normal | Texto sin formato | —¿Qué fue ese ruido? |
| Susurro | `(susurro) texto` | (susurro) No hagas ruido |

### Sistema `/scene_view`

El comando `/scene_view` es interceptado por el motor de chat y **no llega al LLM como texto normal**. En su lugar, se transforma en un **SYSTEM COMMAND** interno que fuerza al personaje a generar una descripción detallada de la escena actual:

```
(SYSTEM COMMAND: El usuario ha solicitado una vista de escena.
Describe detalladamente la escena actual, el entorno, la iluminación
y exactamente lo que estás haciendo en este preciso instante en tercera
persona de forma inmersiva, usando dobles asteriscos.)
```

Esto es independiente del Modo Roleplay — puede usarse en cualquier personaje.

---

## 8. Memoria Episódica: Continuidad entre Sesiones

La memoria episódica resuelve el problema de "olvidar" lo que pasó en la sesión anterior. Cuando una sesión termina, se puede guardar un **episodio**: un snapshot de los últimos mensajes + un resumen generado por LLM.

### Formato del Episodio

```json
// memory/episodes/episode_003.json
{
  "episode_id": 3,
  "timestamp": "2026-05-27T14:30:00",
  "summary": "El usuario y Elara exploraron la biblioteca prohibida. Encontraron un grimorio que emite una luz verde. Elara advirtió que podría ser un señuelo.",
  "messages": [
    {"role": "user", "content": "¿Qué crees que sea esa luz?"},
    {"role": "assistant", "content": "*se acerca cautelosamente* Podría ser un señuelo... los guardianes de este lugar son astutos."}
  ]
}
```

### Ciclo de Vida

```
Sesión N                    Sesión N+1
───────                     ─────────
1. Conversación             1. load_character() carga personaje
2. /save_episode (o          2. Carga el último episodio (episode_003)
   auto al salir del         3. El resumen se inyecta en el prompt:
   context manager)              [MEMORIA EPISÓDICA — Última Sesión (#3)]
3. Se crea episode_003.json     Resumen: El usuario y Elara exploraron...
4. El hash del prompt           Últimos mensajes:
   cambia → KV Cache            Usuario: ¿Qué crees que sea esa luz?
   se regenera en la             Elara: *se acerca cautelosamente* ...
   próxima sesión             4. La conversación continúa como si
                                nunca hubiera terminado
```

### Gestión de Episodios

| Comando / Método | Descripción |
|------------------|-------------|
| `/save_episode` o `llm.save_episode()` | Toma los últimos 5 mensajes, genera resumen con LLM, guarda en `episode_NNN.json` |
| `/episodes` o `llm.list_episodes()` | Lista todos los episodios con ID, fecha, resumen |
| `/episodes load N` o `llm.load_episode(N)` | Rollback al episodio N (cambia el contexto actual) |
| `/episodes delete N` o `llm.delete_episode(N)` | Elimina el episodio N |
| `with VToolLlama() as llm:` | Al salir del bloque, auto-guarda episodio (si hay conversación y personaje cargado) |

Los episodios **nunca se sobreescriben**. Cada llamada a `save_episode()` crea un archivo nuevo (`episode_001`, `episode_002`, etc.), lo que permite mantener un historial completo de sesiones.

---

## 9. Auto-Tools: `remember_memory`

El motor inyecta automáticamente una herramienta interna `remember_memory` en cada llamada a `chat()` o `stream_chat()`. Esta herramienta es invisible para el usuario pero disponible para el LLM.

### Definición Interna

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

### Ciclo de Razonamiento (Reasoning Loop)

```
Usuario: "Recuerda que me gusta el café sin azúcar"

1. chat() recibe el prompt
2. Inyecta internal_tools + tools del usuario
3. LLM decide: "Voy a usar remember_memory"
4. chat() detecta tool_call interna:
   a. Parsear argumentos → {"content": "Al usuario le gusta el café sin azúcar"}
   b. Llama a add_memory() → se guarda en long_term.json
   c. Registra tool_call + respuesta en el historial
   d. CONTINÚA el bucle (no retorna aún)
5. LLM ahora genera la respuesta de texto:
   "Entendido, recordaré que prefieres el café sin azúcar."
6. chat() retorna el texto al usuario

Límite: 3 iteraciones (MAX_LOOPS = 3) para evitar loops infinitos.
```

### Herramientas del Usuario vs Internas

Si el usuario pasa sus propias `tools` al `chat()`, las internas se combinan con las del usuario. El motor distingue entre:

- **Tool calls internas** (`remember_memory`): Se ejecutan automáticamente y el bucle continúa.
- **Tool calls externas** (definidas por el usuario): Se validan contra la lista de tools proporcionada, se devuelven al usuario como `dict`, y el motor **no** continúa el bucle.

La validación anti-alucinación descarta cualquier tool_call cuyo nombre no exista ni en las internas ni en las del usuario.

---

## 10. Slash Commands del Sistema

Los slash commands son comandos que **empiezan con `/`** y se ejecutan directamente sin pasar por el LLM. Operan sobre el Character OS en tiempo real.

| Comando | Capa que Afecta | Descripción |
|---------|:---------------:|-------------|
| `/mem <texto>` | Memory | Guarda memoria con priority=1.0, always_include=True |
| `/memories` | Memory | Lista todas las memorias con ID |
| `/save_episode` | Memory | Guarda snapshot episódico |
| `/episodes` | Memory | Gestiona episodios (list/load/delete) |
| `/rel <trust> <fam>` | State (Relationship) | Modifica trust_level y familiarity |
| `/mood <layer> <val>` | Mods | Aplica CharacterMod temporal |
| `/rebuild` | State | Ejecuta LLM para rebuild personality |
| `/state` | State | Muestra dump JSON del estado actual |
| `/scene_view` | — | Forza descripción inmersiva de escena |
| `/help` | — | Lista comandos disponibles |

### Extensión: Slash Commands Personalizados

```python
from vtool_llama import VToolLlama

llm = VToolLlama()

@llm.slash_commands.command("clima", description="Obtiene el clima actual")
def handle_clima(args: str) -> str:
    import requests
    resp = requests.get(f"https://api.clima.com/{args}")
    return f"Clima en {args}: {resp.json()['temp']}°C"
```

Esto permite a los proyectos que integran `vtool_llama` agregar comandos propios sin modificar la librería.

---

## 11. Creación de Personajes

Hay dos formas de crear un personaje: manual (estructura programática) y con IA (autogenerada).

### 11.1 Creación Manual

```python
from vtool_llama import VToolLlama

llm = VToolLlama(auto_load=False)

llm.create_character(
    name="mago_errante",
    identity_data={
        "name": "Elara",
        "role": "Maga Errante",
        "background": "Nacida en el bosque de Sombríaurora...",
        "scenario": "Un mundo donde la magia está prohibida."
    },
    personality_data={
        "traits": ["Curiosa", "Impaciente"],
        "flaws": ["Desconfía de los extraños"],
        "motivations": ["Encontrar un grimorio perdido"]
    },
    speech_data={
        "style": "Casual con toques poéticos",
        "tone": "Cálido",
        "verbosity": "Medio",
        "examples": [
            "{{user}}: Hola\n{{char}}: *saluda* Un placer conocerte."
        ]
    },
    rules_data={
        "core_rules": ["No revelar que es IA"],
        "never_do": ["Romper la cuarta pared"],
        "response_style": ["Usa asteriscos para acciones"],
        "roleplay_mode": True
    },
    initial_memories=[
        "Conoce al usuario de vista pero no confía plenamente.",
        "Ha estado viajando sola por meses."
    ]
)
```

Esto crea toda la estructura de directorios y archivos en `personajes/mago_errante/`. Después se carga con `llm.load_character("mago_errante")`.

### 11.2 Creación con IA

```python
from vtool_llama import VToolLlama

llm = VToolLlama(auto_load=True)

llm.generate_character_with_ai(
    name="zara",
    prompt="Zara es una hacker ciberpunk con actitud rebelde. Vive en Neo-Tokio, 2087. "
           "Tiene 22 años, habla con jerga cyber, es leal a sus amigos pero desconfía "
           "de las corporaciones. Usa un dron llamado 'Chispa' para sus hackeos."
)
```

El sistema ejecuta el siguiente pipeline:

1. Construye un system prompt especial que instruye al LLM a generar JSON puro
2. Envía el prompt del usuario como mensaje
3. El LLM responde con un JSON estructurado:

```json
{
  "identity": {
    "name": "Zara",
    "role": "Hacker Ciberpunk",
    "background": "Nacida en los barrios bajos de Neo-Tokio...",
    "scenario": "Neo-Tokio, 2087. Corporaciones controlan todo."
  },
  "personality": {
    "traits": ["Rebelde", "Leal", "Desconfiada"],
    "motivations": ["Derribar el sistema corporativo"],
    "flaws": ["Impulsiva", "Guarda rencores"]
  },
  "speech": {
    "style": "Jerga cyberpunk, cortante",
    "tone": "Sarcástico",
    "verbosity": "Medio",
    "examples": ["{{user}}: Hola\n{{char}}: *Chispa parpadea* ¿Qué quieres?"]
  },
  "rules": {
    "core_rules": ["No confiar en corporaciones"],
    "never_do": ["Trabajar para el sistema"],
    "response_style": ["Usa asteriscos para acciones técnicas"],
    "roleplay_mode": true
  },
  "memories": [
    "Tiene un dron llamado Chispa.",
    "Debe dinero a un hacker rival."
  ]
}
```

4. Parsea el JSON y llama a `create_character()` con los datos extraídos.

---

## 12. Ciclo de Vida de una Interacción

### Secuencia Completa: Usuario envía un mensaje

```
Usuario escribe: "Hola Elara, ¿cómo estás?"

1. VToolLlama.chat()
   ├── ¿Prompt empieza con "/"?
   │   └── Sí → Ejecutar SlashCommand (bypassea LLM)
   │   └── No → Continuar
   │
   ├── Agregar a short_memory (deque, último N)
   ├── Agregar a chat_memory (historial largo)
   ├── Auto-trim si el contexto está cerca del límite
   │
   ├── CharacterCompiler.compile_prompt()
   │   ├── base_prompt
   │   ├── DNA (con overrides de Mods si existen)
   │   │   ├── identity
   │   │   ├── personality (traits, flaws, motivations)
   │   │   ├── rules (core_rules, never_do, roleplay_mode)
   │   │   └── speech (style, tone, verbosity, examples)
   │   ├── STATE (runtime_state, personality_state)
   │   ├── RELATIONSHIP (trust_level, familiarity)
   │   ├── MODS activos
   │   ├── MEMORY (memories prioridad >= 0.5)
   │   └── EPISODE (último episodio si existe)
   │   └── → Prompt compilado listo
   │
   ├── _inject_personality_into_system_prompt()
   │   └── Actualiza ChatMemory.system_prompt
   │
   ├── ModelManager.generate()
   │   ├── Prepara kwargs (temperature, max_tokens, tools)
   │   ├── Llama.create_chat_completion(messages, **kwargs)
   │   └── → Resultado (texto o tool_calls)
   │
   ├── ¿Hay tool_calls?
   │   ├── Sí → ¿Es remember_memory? (Auto-Tool)
   │   │   ├── Sí → add_memory() + continuar bucle (max 3)
   │   │   └── No → ¿Coincide con tools del usuario?
   │   │       ├── Sí → Devolver tool_calls al usuario
   │   │       └── No → Descartar (alucinación)
   │   └── No → Devolver texto
   │
   ├── StatsManager.end_generation()
   │   └── Registrar estadísticas
   │
   └── Retornar respuesta
```

### Secuencia de Carga de Personaje

```
llm.load_character("elara")

1. CharacterManager.load_character("elara")
   ├── Validar que existe personajes/elara/dna/
   ├── _load_dna() → leer identity.json, personality.json, speech.json, rules.json
   ├── _load_memory() → leer long_term.json
   ├── _load_latest_episode() → leer último episode_NNN.json
   ├── _load_state() → runtime_state.json, relationship_state.json, state_meta.json
   └── _load_mods() → active_mods.json

2. ¿Modelo cargado? → Sí
   ├── Compilar prompt base + full
   ├── ¿base.state existe?
   │   ├── No → warmup + guardar
   │   └── Sí → ¿Hash SHA-256 coincide?
   │       ├── Sí → Cargar full state (0.2s)
   │       └── No → Regenerar full state desde base
   └── _inject_personality_into_system_prompt()
```

---

## 13. Flujo de Datos Completo

```
                    ┌───────────────────────┐
                    │      VToolLlama       │
                    │     (Orquestador)     │
                    └───┬───────────┬───────┘
                        │           │
                 ┌──────▼──┐  ┌─────▼──────┐
                 │ Chat    │  │ Model      │
                 │ Memory  │  │ Manager    │
                 │ (histor │  │ (inferencia│
                 │  ial)   │  │  llama.cpp)│
                 └────┬────┘  └─────┬──────┘
                      │             │
                 ┌────▼─────────────▼──────┐
                 │   CharacterManager      │
                 │   (Capas del Personaje) │
                 └────┬──────┬──────┬──────┘
                      │      │      │
              ┌───────▼──┐ ┌─▼──┐ ┌─▼──────┐
              │ Character│ │KV  │ │Slash   │
              │ Compiler │ │Cache│ │Commands│
              │ (prompt) │ │Dual │ │Registry│
              └───────┬──┘ └────┘ └────────┘
                      │
         ┌────────────┼────────────┐
         │            │            │
    ┌────▼───┐  ┌────▼───┐  ┌────▼───┐
    │  DNA   │  │ Memory │  │  State │
    │ (4     │  │ (JSON) │  │ (JSON) │
    │ archs) │  │        │  │        │
    └────────┘  └────────┘  └────────┘
```

### Archivos y su Rol en el Flujo

| Archivo | Se Lee en | Se Escribe en | Propósito |
|---------|-----------|---------------|-----------|
| `dna/identity.json` | `load_character()` | `create_character()` | Identidad base del personaje |
| `dna/personality.json` | `load_character()` | `create_character()` | Rasgos de personalidad |
| `dna/speech.json` | `load_character()` | `create_character()` | Estilo de habla y ejemplos |
| `dna/rules.json` | `load_character()` | `create_character()` | Reglas de comportamiento |
| `memory/long_term.json` | `load_character()` | `add_memory()` | Memorias persistentes |
| `memory/episodes/episode_N.json` | `load_character()` | `save_episode()` | Snapshots de sesiones |
| `memory/base.state` | `load_character()` | `_warmup_character_cache()` | KV Cache DNA puro |
| `memory/personality_plus_memory.state` | `load_character()` | `_warmup_character_cache()` | KV Cache completo |
| `state/relationship_state.json` | `load_character()` | `rebuild_personality_state()` | Trust y familiarity |
| `state/runtime_state.json` | `load_character()` | `save_state()` | Estado en tiempo real |
| `state/personality_state.json` | `load_character()` | `rebuild_personality_state()` | Resumen de personalidad |
| `state/state_meta.json` | `load_character()` | `mark_rebuild_done()` | Hash SHA-256 del prompt |
| `mods/active_mods.json` | `load_character()` | `set_mod()` / `remove_mod()` | Modificadores activos |

---

## Resumen Arquitectónico

```
Character OS = DNA (esencia) + Memory (recuerdos) + State (estado) + Mods (capas temporales)
                    │
                    ▼
         Character Compiler v2 (MODS > STATE > DNA)
                    │
                    ▼
         System Prompt Compilado
                    │
                    ▼
         KV Cache Dual (Base + Dynamic)
         └── SHA-256 invalidation → solo recalcula diff
                    │
                    ▼
         Modelo GGUF (llama.cpp)
                    │
                    ▼
         Respuesta + Auto-Tools (remember_memory)
                    │
                    ▼
         Relationship Engine update + Episodic save
```

El sistema está diseñado para que cada capa sea **independiente y reemplazable**. Puedes:
- Tener múltiples personajes en `personajes/` y switchear entre ellos
- Aplicar Mods temporales sin modificar el DNA
- Hacer rollback a episodios anteriores
- Extender con comandos personalizados
- Integrar herramientas externas sin modificar la librería
