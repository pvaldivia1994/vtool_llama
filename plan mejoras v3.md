# Plan mejoras v3

## Objetivo

Reducir el peso del system prompt inicial sin perder identidad, continuidad ni coherencia del personaje.

El problema actual no es solo el trim del historial: si el system prompt ocupa mas de la mitad de `n_ctx`, queda muy poco espacio para conversacion, memoria dinamica, herramientas y respuesta.

Ejemplo real:

```text
n_ctx: 4096
system: 2349
reserved: 300
limite efectivo: 3796
espacio para conversacion: 1447
```

El KV cache acelera la evaluacion del prompt base, pero no libera ventana de contexto. Todo token del system prompt sigue ocupando espacio dentro de `n_ctx`.

## Principio clave

El system prompt inicial debe contener solo lo que el modelo necesita siempre.

Lo demas debe vivir como contexto recuperable, resumen compacto o memoria dinamica.

## Problemas detectados

1. El prompt estatico del personaje mezcla capas esenciales y capas situacionales.
   - Identidad, reglas duras, estilo, mundo, soul, memoria, ejemplos y definiciones pueden terminar todos en el bloque inicial.
   - Eso hace que cada turno arranque con una carga fija demasiado grande.

2. El KV cache puede ocultar el coste de velocidad, pero no el coste de contexto.
   - `base.state` evita recalcular tokens ya evaluados.
   - Pero esos tokens siguen ocupando posicion en la ventana.

3. Algunas capas no necesitan estar siempre presentes.
   - `few_shot`, historia larga, detalles del soul, contradicciones, heridas, escenario extendido y memorias pueden ser utiles solo cuando el turno lo pide.

4. El system prompt no tiene presupuesto duro.
   - El compilador puede generar un prompt grande sin saber cuanto espacio deja para la conversacion.

5. Falta una version compacta y operacional del personaje.
   - El modelo necesita una "capsula" estable, no necesariamente todo el DNA completo.

## Estrategia propuesta

### 1. Crear `character capsule`

Generar una version compacta del personaje para vivir siempre en system.

Debe tener entre 400 y 800 tokens como objetivo inicial.

Contenido recomendado:

```text
[CHARACTER CAPSULE]

Name:
Role:
Core identity:
Stable personality:
Speech style:
Relationship stance:
Hard boundaries:
Language:
Continuity rules:
```

Reglas:

- Debe estar en ingles si son instrucciones tecnicas.
- Debe indicar explicitamente que el personaje responde siempre en espanol salvo que el usuario pida otro idioma.
- No debe incluir prosa larga, biografia completa ni ejemplos extensos.
- Debe preservar lo que no puede cambiar sin romper el personaje.

### 2. Separar prompt full vs prompt compact

Durante `load_character()` o rebuild:

```text
base_prompt_full.yaml      # version completa para debug, rebuild y auditoria
base_prompt_compact.yaml   # version usada como system prompt inicial
base.state                 # warmup del prompt compact usado en runtime
```

El prompt full no desaparece. Sirve como fuente de verdad y para regenerar la capsula.

### 3. Mover capas grandes a retrieval dinamico

Capas candidatas a salir del system inicial:

- soul completo
- life timeline
- memoria larga
- few-shot examples
- escenario extendido
- detalles psicologicos secundarios
- contradicciones menores
- definiciones internas extensas

Estas capas deben entrar solo si el turno las necesita mediante:

- SQLite summaries
- ChromaDB semantic retrieval
- context injector
- bloques dinamicos compactos

### 4. Presupuesto por capas

Agregar presupuesto al compilador.

Ejemplo inicial:

```text
system_compact_target: 800
system_compact_max: 1200
dynamic_context_target: 1200
reserved_response: 300-800
recent_chat_budget: resto
```

Cada capa debe poder reportar:

- tokens estimados
- si es obligatoria
- si es degradable
- si puede moverse a retrieval

### 5. Degradacion progresiva del prompt

Si el system compact supera el presupuesto:

1. Reducir wording ornamental.
2. Quitar ejemplos.
3. Comprimir background.
4. Convertir listas largas en bullets cortos.
5. Mover detalles a memoria semantica.
6. Mantener siempre identidad, reglas duras e idioma.

### 6. Prompt helper para generar capsula

Crear helpers en:

```text
vtool_llama/config/prompts/helpers/character_capsule_system.md
vtool_llama/config/prompts/helpers/character_capsule_user.md
```

Recomendacion:

- instrucciones tecnicas en ingles
- salida estructurada en ingles o bilingue, pero con regla clara de respuesta visible en espanol
- sin narrativa
- sin inventar
- maximo de bullets por seccion

### 7. Runtime con dos fuentes

En runtime:

1. System inicial: `base_prompt_compact.yaml`.
2. Contexto dinamico: estado emocional, relacion, escena activa.
3. Retrieval: solo memoria/soul/escenario relevantes.
4. Chat reciente: ultimos turnos.
5. Context digest: reemplaza historial recortado.

El modelo recibe menos prompt fijo y mas contexto relevante al turno.

## Cambios propuestos

1. Agregar configuracion:

```json
{
  "compact_system_prompt": true,
  "system_prompt_target_tokens": 800,
  "system_prompt_max_tokens": 1200
}
```

2. Agregar helpers:

```text
config/prompts/helpers/character_capsule_system.md
config/prompts/helpers/character_capsule_user.md
```

3. Agregar metodos:

```python
CharacterManager.build_compact_system_prompt()
CharacterManager.build_full_system_prompt()
CharacterCompiler.compile_compact_prompt(...)
```

4. Cambiar warmup:

```text
warmup base.state con base_prompt_compact.yaml
guardar base_prompt_full.yaml para auditoria
guardar base_prompt_compact.yaml para runtime
guardar meta con hashes de ambos
```

5. Cambiar `get_token_usage()` para reportar:

```text
system_compact_tokens
system_full_tokens
system_saved_tokens
```

6. Agregar debug:

```text
/prompt_budget
```

Debe mostrar:

- tokens del system compact
- tokens del full prompt
- ahorro estimado
- tokens por capa
- capas movidas a retrieval

## Tareas

1. Medir tokens por capa del prompt actual. [Listo]
   - `CharacterCompiler.get_layer_token_breakdown(...)` reporta tokens por capa.
   - `VToolLlama.get_prompt_layer_usage()` expone el diagnostico con presupuesto efectivo.
   - Cada capa reporta fase (`static`/`dynamic`), tokens, chars, si es obligatoria y si es movible.
2. Definir lista de capas obligatorias vs movibles. [Listo]
   - `LAYER_POLICIES` centraliza `required`, `movable` y `compact`.
   - El diagnostico y el compactador comparten la misma clasificacion.
3. Crear helpers `character_capsule_*`. [Listo]
   - `config/prompts/helpers/character_capsule_system.md`.
   - `config/prompts/helpers/character_capsule_user.md`.
4. Implementar `compile_compact_prompt()`. [Listo]
   - Primera version deterministica, basada en DNA, sin inferencia LLM.
   - Genera `[CHARACTER CAPSULE]` con identidad, personalidad estable, habla, limites, estilo e idioma.
5. Guardar `base_prompt_full.yaml` y `base_prompt_compact.yaml`. [Listo]
   - `_warmup_character_cache()` guarda runtime, full y compact.
   - Metadata incluye hash full y hash compact.
6. Hacer warmup con prompt compact. [Listo]
   - Si `compact_system_prompt=true`, `build_system_prompt()` retorna el prompt compact y ese prompt alimenta `base.state`.
7. Mover soul/memorias largas a retrieval dinamico. [Parcial]
   - El prompt compact excluye `soul`, `beliefs_contradictions`, `few_shot_examples`, `memory`, `psychology` y `persona` del system fijo.
   - Falta reforzar retrieval especifico para soul/life timeline por turno.
8. Agregar diagnostico de presupuesto por capa. [Listo]
   - `get_prompt_layer_usage()` reporta full static, compact static, ahorro y presupuesto restante.
9. Agregar tests de reduccion de system prompt. [Listo]
   - Tests para policies, prompt compact y seleccion por config.
10. Documentar el nuevo flujo en README y DETA. [Listo]

## Riesgos

1. Perder personalidad por comprimir demasiado.
   - Mitigacion: tests de continuidad y reglas duras obligatorias.

2. Retrieval insuficiente.
   - Mitigacion: fallback a summaries y memoria always_include.

3. Capsula generada con informacion inventada.
   - Mitigacion: prompt extractor, no creativo; validacion contra DNA original.

4. Inconsistencia entre full y compact.
   - Mitigacion: hashes, rebuild automatico si cambia full prompt.

## Resultado esperado

El system prompt inicial deberia bajar de miles de tokens a una capsula compacta.

Con `n_ctx=4096`, el objetivo es pasar de algo como:

```text
System: 2349
Espacio conversacion: 1447
```

a algo como:

```text
System compact: 700-1000
Espacio conversacion: 2700-3000
```

Esto daria mas aire al chat, al digest, al retrieval dinamico y a la respuesta, sin depender de que el KV cache resuelva un problema que realmente es de capacidad de contexto.
