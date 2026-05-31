# Plan mejoras v2

## Estado de implementacion

1. Crear `context digest` estructurado para el trim. [Listo]
2. Resumir solo mensajes candidatos a salir del contexto, no todo el historial. [Listo]
3. Mantener siempre fuera del digest el ultimo mensaje del usuario. [Listo]
4. Insertar un unico bloque `[RESUMEN DE CONVERSACION PREVIA]` y reemplazar digests anteriores. [Listo]
5. Dividir el digest en chunks pequenos y fusionarlos cuando haga falta. [Listo]
6. Usar parametros conservadores para el digest (`temperature=0.1`, `max_tokens` acotado). [Listo]
7. Agregar fallback extractivo cuando la generacion del digest falle o devuelva una forma invalida. [Listo]
8. Guardar/restaurar estado del modelo con `save_state/load_state` si esta disponible. [Listo]
9. Externalizar prompts tecnicos del digest en `config/prompts/helpers`. [Listo]
10. Validar con tests de trim y suite completa. [Listo]

## Resumen de contexto como `context digest`

El resumen actual del trim no deberia ser un resumen narrativo. Debe ser una compresion operacional del contexto: informacion concreta que el modelo necesita para continuar sin perder coherencia.

Nombre recomendado: `context digest` o `estado comprimido`, no "resumen".

## Problema original

El metodo anterior de trim pedia algo parecido a:

```text
Resumi la conversacion en 2-3 oraciones. Solo los hechos clave, sin opiniones.
```

Ese enfoque produce resumenes genericos, por ejemplo:

```text
El usuario y el personaje hablaron sobre cuentos y presentaciones.
```

Eso no sirve para mantener continuidad. El modelo necesita hechos accionables, no prosa bonita.

## Estrategia recomendada

Generar un bloque estructurado con secciones fijas:

```text
[RESUMEN DE CONVERSACION PREVIA]

Hechos estables:
- El usuario se llama LiuniK.
- El personaje se llama Luna.

Estado actual:
- Luna estaba contando un cuento sobre una flor llamada Lira.
- El cuento quedo en curso, pero el usuario cambio de tema.

Preferencias del usuario:
- El usuario pide respuestas mas largas cuando dice "uno mas largo".

Relacion y tono:
- El personaje responde en modo roleplay con acciones entre asteriscos.

Hilos abiertos:
- Responder directamente al ultimo mensaje del usuario.
- No continuar el cuento si el usuario cambia de tema.
```

## Prompt implementado

Los prompts ya no viven hardcodeados en `engine/memory.py`. Se cargan desde:

- `vtool_llama/config/prompts/helpers/context_digest_system.md`
- `vtool_llama/config/prompts/helpers/context_digest_user.md`

El system helper esta escrito en ingles para mejorar obediencia tecnica, pero exige que el digest final salga en espanol.

System:

```text
[CONTEXT DIGEST HELPER]

You are a context compressor for a roleplay chat system.

Do not write a narrative summary.
Do not invent facts.
Do not generalize.
Do not answer the user.
Extract only operational information needed to continue the conversation.

Return the digest in Spanish using exactly these sections:

Hechos estables:
- ...

Estado actual:
- ...

Preferencias del usuario:
- ...

Relacion y tono:
- ...

Hilos abiertos:
- ...

Descartar:
- ...
```

User:

```text
CONVERSATION TO COMPRESS:
#SOURCE

Rules:
- If the user's name appears, preserve it.
- If the user changes topic, preserve the topic change.
- If a story, scene, or roleplay thread is ongoing, state whether it remains open or was interrupted.
- Keep at most 12 bullets total.
- Each bullet must be concrete and verifiable.
- Do not add information that is not present in the conversation.
- Return only the Spanish digest sections requested by the system message.
```

## Flujo recomendado

1. Recolectar mensajes candidatos a ser recortados.
2. Mantener siempre fuera del digest el ultimo mensaje del usuario.
3. Generar digest solo con los mensajes que van a salir del contexto.
4. Insertar o reemplazar un unico bloque:
   `[RESUMEN DE CONVERSACION PREVIA]`
5. No acumular multiples digests.
6. Si el contexto es muy grande, usar dos pasos:
   - digest por chunks
   - merge final estructurado

## Punto critico: que modelo genera el digest

Actualmente `_auto_trim_if_needed()` llama:

```python
self._model_manager.generate(...)
```

Eso usa el mismo `ModelManager` ya cargado en memoria. No carga un modelo nuevo.

Implicaciones:

1. No hay coste de cargar otro modelo.
2. Si el modelo actual esta cargado con el personaje, sigue siendo el mismo objeto `llama_cpp.Llama`.
3. Pero el digest se genera con los mensajes que se le pasan a `generate()`, no automaticamente con el system prompt del personaje.
4. Desde que `ModelManager.generate()` llama `reset()` antes de cada inferencia, se reduce la contaminacion del KV cache anterior.
5. Aun asi, si se esta cerca del limite real de contexto, generar un digest tambien consume contexto y puede fallar si el texto a comprimir es demasiado grande.

## Riesgo actual

Si el contexto esta en sobrecarga y el trim intenta generar un resumen usando una conversacion demasiado larga, el resumen puede fallar por exceso de contexto antes de poder recortar.

Esto es especialmente delicado si:

- `history` trae muchos mensajes.
- Cada mensaje se trunca a 200 chars, pero aun asi el bloque total es grande.
- El modelo tiene `n_ctx` bajo.
- El sistema intenta resumir justo cuando ya esta demasiado cerca del limite.

## Solucion recomendada

1. No resumir todo el historial.
   - Solo resumir los mensajes que se van a remover.

2. Presupuestar el digest.
   - Antes de llamar a `generate()`, calcular tokens del prompt de digest.
   - Si no entra, dividir en chunks pequenos.

3. Usar chunks.
   - Ejemplo: 8-12 mensajes por chunk.
   - Generar digest parcial.
   - Luego fusionar digests parciales en un digest final.

4. Usar parametros conservadores.
   - `temperature=0.1`
   - `max_tokens=250`
   - sin tools
   - prompt estructurado

5. Fallback sin LLM.
   - Si falla la generacion del digest, crear un digest extractivo simple:
     - ultimos nombres detectados
     - ultimos mensajes del usuario
     - ultimo tema activo
     - "Resumen automatico no disponible"

6. No depender del KV cache del personaje.
   - Para digest, usar `generate()` con mensajes limpios.
   - Asegurar `reset()` antes de generar.
   - Restaurar estado si se usa `save_state/load_state`, pero idealmente el digest deberia ser stateless.

## Resultado esperado

El trim no debe crear un resumen bonito. Debe crear una memoria operacional compacta, estable y util. El digest debe preservar hechos importantes, cambios de tema, preferencias, estado de escena y pendientes, sin arrastrar temas cerrados ni contradecir el ultimo mensaje del usuario.
