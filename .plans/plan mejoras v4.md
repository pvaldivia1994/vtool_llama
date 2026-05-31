# Plan mejoras v4

## Objetivo

Hacer el sistema de tools mas confiable, predecible y testeable.

El sistema actual tiene una buena base modular, pero mezcla demasiados formatos de tool calling, inyecta politica de tools en el system prompt fijo y ejecuta algunas tools en streaming demasiado pronto.

## Diagnostico

El sistema de tools esta dividido en:

```text
vtool_llama/tools/
├── definitions.py       # INTERNAL_TOOLS, TOOL_USAGE_POLICY
├── parser.py            # fallback textual de tool calls
├── manager.py           # ToolExecutionManager
└── stream_processor.py  # intercepcion de tools en streaming
```

La integracion principal ocurre en:

```text
vtool_llama/engine/chat.py
vtool_llama/engine/base.py
vtool_llama/engine/character.py
vtool_llama/model/inference.py
vtool_llama/model/capacity.py
```

## Lo que esta bien

1. La arquitectura esta separada por responsabilidades.
2. Soporta tool calling estructurado tipo OpenAI.
3. Tiene fallback textual para modelos locales.
4. Separa tools internas de tools externas del usuario.
5. Valida tools externas contra la lista declarada.
6. El streaming intenta ocultar tool calls crudas al usuario.
7. El loop de `chat()` permite ejecutar una tool interna y continuar la respuesta.

## Problemas detectados

### 1. Poca cobertura de tests

Actualmente casi no hay tests dedicados a:

- `parse_text_tool_calls`
- `strip_text_tool_calls`
- `ToolExecutionManager`
- `StreamPostProcessor`
- coercion retry
- tools internas vs externas
- reconstruccion de tool calls en streaming

Esto hace riesgoso modificar el sistema.

### 2. Demasiados formatos textuales soportados

El parser acepta muchos formatos:

```text
{{tool_code:name{...}}}
{{name{...}}}
<|tool_call>call:name{...}<tool_call|>
call:name{...}
<tool_call>name(...)</tool_call>
```

Esto ayuda con modelos locales, pero aumenta:

- falsos positivos
- ambiguedad
- dificultad de debugging
- riesgo de ejecutar algo que el modelo escribio como texto normal

### 3. `supports_tools()` es una heuristica debil

Actualmente revisa si el `tokenizer.chat_template` contiene:

```text
tools
functions
```

Eso no garantiza soporte real de tool calling. Puede dar falsos positivos o falsos negativos.

### 4. Tools internas siempre se pasan al modelo

En `chat()` y `stream_chat()` se hace:

```python
active_tools = (tools or []) + internal_tools
```

Eso significa que `store_long_term_memory` siempre esta visible para el modelo, aunque el turno no tenga nada que memorizar.

Resultado posible:

- llamadas innecesarias
- mas tokens en prompt
- mas probabilidad de tool calls alucinadas

### 5. `TOOL_USAGE_POLICY` aumenta el system prompt fijo

`_inject_personality_into_system_prompt()` agrega la politica de tools al system prompt:

```python
enriched_prompt += "\n\n" + TOOL_USAGE_POLICY
```

Esto aumenta el peso fijo del system prompt, justo el problema que se esta corrigiendo con `compact_system_prompt`.

### 6. Streaming ejecuta tools demasiado pronto

`StreamPostProcessor` ejecuta tool calls cuando detecta un patron completo durante el stream.

Riesgo:

- se guarda una memoria antes de validar la respuesta final
- una tool parcialmente incorrecta puede ejecutarse igual
- es mas dificil revertir efectos secundarios

### 7. Documentacion y codigo no coinciden completamente

La documentacion menciona:

- `get_scene_state`
- `describe_scene`
- aliases internos

Pero `INTERNAL_TOOLS` actualmente solo define:

```text
store_long_term_memory
```

El parser/manager conocen scene tools, pero no estan declaradas como herramientas internas OpenAI.

## Estrategia recomendada

### Fase 1: Tests antes de cambios profundos

Agregar tests para congelar comportamiento actual:

1. Parser textual.
2. Strip de tool calls.
3. Manager con structured calls internas.
4. Manager con external calls validas e invalidas.
5. Coercion retry para triggers de memoria.
6. StreamPostProcessor ocultando tool calls.
7. Reconstruccion de tool calls por chunks.

### Fase 2: Definir contratos oficiales

Mantener dos caminos oficiales:

1. Structured tool calls estilo OpenAI.
2. Fallback textual unico y recomendado:

```text
<tool_call>
{"name":"store_long_term_memory","arguments":{"content":"...","category":"..."}}
</tool_call>
```

Decision aplicada: no mantener formatos legacy textuales porque el proyecto esta iniciando.

### Fase 3: Activacion condicional de tools internas

No pasar siempre `INTERNAL_TOOLS`.

Regla propuesta:

- si el prompt tiene trigger de memoria, activar `store_long_term_memory`
- si config `always_enable_internal_tools=true`, activar siempre
- si el usuario pasa tools externas, mantenerlas siempre

Config propuesta:

```json
{
  "always_enable_internal_tools": false,
  "enable_text_tool_fallback": true,
  "enable_stream_tool_execution": false
}
```

### Fase 4: Sacar politica de tools del system fijo

Mover `TOOL_USAGE_POLICY` fuera del prompt estatico del personaje.

Opciones:

1. Inyectar la politica solo cuando haya tools activas.
2. Crear version compacta de la politica.
3. Inyectarla como system temporal antes del ultimo user.
4. No meterla si el modelo soporta tool calling nativo y las schemas son suficientes.

### Fase 5: Streaming seguro

Cambiar streaming para no ejecutar efectos secundarios inmediatamente.

Nuevo flujo recomendado:

1. Stream detecta tool call.
2. La oculta del usuario.
3. La guarda como candidata.
4. Al final del stream se valida.
5. Si es interna y segura, se ejecuta.
6. Si tiene efecto irreversible, confirmar o registrar con rollback posible.

Para `store_long_term_memory`, ejecutar al final del stream es suficiente.

### Fase 6: Alinear scene tools

Decision aplicada: eliminar referencias internas legacy a `get_scene_state` / `describe_scene`.

Si una app necesita herramientas de escena, debe declararlas como tools externas explicitas.

## Cambios propuestos

1. Agregar tests de tools. [Listo]
   - Parser textual, strip, manager, tools externas, activacion condicional y streaming.
2. Crear helper `get_active_internal_tools(prompt, config)`. [Listo]
   - Activa `store_long_term_memory` por trigger o `always_enable_internal_tools=true`.
3. Agregar config de control de tools internas. [Listo]
   - `always_enable_internal_tools`
   - `enable_text_tool_fallback`
   - `enable_stream_tool_execution`
4. Inyectar `TOOL_USAGE_POLICY` solo cuando haya tools internas activas. [Listo]
5. Compactar `TOOL_USAGE_POLICY`. [Listo]
6. Definir formato textual oficial v2. [Listo]
   - Unico formato textual soportado: `<tool_call>{json}</tool_call>`.
7. Mantener parser legacy con warning/debug. [Cancelado]
   - Decision: no mantener legacy porque el proyecto esta iniciando.
   - Formatos `{{...}}`, `call:...`, `<|tool_call>` y aliases textuales fueron retirados.
8. Cambiar streaming para diferir ejecucion hasta el final. [Listo]
   - `StreamPostProcessor` oculta tool calls y guarda `pending_tool_patterns`.
   - El engine valida/ejecuta candidatos al final cuando `enable_stream_tool_execution=false`.
9. Alinear scene tools con codigo real. [Listo]
   - Scene tools no se declaran ni se ejecutan como internas.
   - Si una app las necesita, debe pasarlas como tools externas explicitas.
10. Actualizar `tools/DETA.md`, `engine/DETA.md` y README. [Listo]

## Orden de implementacion recomendado

1. Tests del comportamiento actual.
2. Config y helper de activacion condicional.
3. Reducir inyeccion de `TOOL_USAGE_POLICY`.
4. Formato textual oficial v2.
5. Streaming diferido.
6. Limpieza de scene tools.

## Riesgos

1. Romper modelos locales que dependian del fallback textual viejo.
   - Mitigacion: el proyecto esta iniciando; se prefiere contrato limpio, tests claros y un unico formato textual.

2. Reducir demasiado la probabilidad de tool use.
   - Mitigacion: activar tools internas por triggers claros y coercion controlada.

3. Perder memoria automatica util.
   - Mitigacion: logs de triggers, tests y metricas de tool calls.

4. Aumentar complejidad del loop de chat.
   - Mitigacion: mover decision de tools a helpers puros y testeables.

## Resultado esperado

El sistema de tools debe ser:

- mas liviano en tokens
- mas facil de testear
- menos propenso a falsas ejecuciones
- compatible con modelos con tool calling nativo
- tolerante con modelos locales sin soporte nativo
- consistente entre chat normal y streaming

La meta no es eliminar flexibilidad, sino convertirla en compatibilidad controlada.
