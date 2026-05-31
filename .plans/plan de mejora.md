# Plan de mejora del trim de contexto

## Diagnostico

El sistema actual de trim funciona como una valvula de emergencia, pero no como una gestion completa y confiable del contexto. Evita que el historial crezca sin limite en RAM, pero puede perder informacion util, dejar turnos incompletos y no garantiza que el prompt final enviado al modelo entre realmente en el presupuesto.

Nota de estado: este diagnostico describe el punto de partida. La implementacion actual ya hace el trim obligatorio, crea un `context digest` estructurado, lo inyecta como bloque system activo, lo guarda en SQLite y carga sus prompts tecnicos desde `vtool_llama/config/prompts/helpers`.

## Problemas detectados

1. El resumen se genera pero no se reinyecta al contexto actual.
   - `_auto_trim_if_needed()` genera un resumen y lo guarda en SQLite con `add_summary(...)`.
   - Sin embargo, ese resumen no se agrega al `ChatMemory` ni al prompt final.
   - Resultado: el modelo pierde los mensajes recortados y no recibe el resumen que deberia reemplazarlos.

2. Los tests y la implementacion no coinciden.
   - `tests/test_auto_trim.py` espera un bloque `[RESUMEN DE CONVERSACION PREVIA]`.
   - El codigo actual no inserta ese bloque.
   - Tambien hay tests que esperan proteccion explicita del KV cache con `save_state/load_state`, pero el trim actual no lo hace.

3. El conteo de tokens es aproximado respecto al prompt real.
   - El trim cuenta texto plano concatenando `m.content`.
   - No cuenta el chat template real, roles, separadores, tool calls, estado dinamico, soul context ni contexto inyectado.
   - Puede creer que hay espacio cuando el prompt final realmente ya esta cerca del limite.

4. El trim ocurre antes de inyectar contexto dinamico.
   - En `chat()` se llama `_auto_trim_if_needed()` antes de inyectar personalidad, soul context y estado dinamico.
   - Eso significa que el trim decide con una version incompleta del prompt.

5. Recorta mensajes sueltos, no turnos completos.
   - El loop elimina el primer mensaje no-system que encuentra.
   - Puede dejar respuestas sin pregunta, preguntas sin respuesta o secuencias de tools incompletas.
   - Esto puede degradar la coherencia del modelo.

6. El objetivo de trim documentado no coincide con el codigo.
   - La documentacion dice que se recorta hasta aproximadamente 60% del limite efectivo.
   - El codigo solo recorta hasta dejar de estar cerca del limite segun `is_context_near_limit(...)`.

7. `trim_memory()` manual no hace trim real.
   - Si el modelo esta cargado, solo informa que el deque maneja el limite.
   - Esto puede ser confuso porque el nombre del metodo promete una accion que no ocurre.

8. Hay confusion entre `chat_memory_limit` y `history_limit`.
   - `ChatMemory` se inicializa con `chat_memory_limit`.
   - `reload_config()` luego cambia `_history_limit` usando `history_limit`.
   - Esto mezcla dos conceptos distintos y puede producir comportamiento dificil de predecir.

9. `auto_trim_context` no deberia ser opcional.
   - Con modelos locales y contexto limitado, permitir desactivar el trim aumenta el riesgo de errores por exceso de contexto.
   - El trim deberia ser una garantia interna siempre activa, no una opcion de configuracion.

## Solucion propuesta

1. Hacer que el trim sea parte obligatoria del pipeline. [Listo]
   - Eliminar o ignorar `auto_trim_context`.
   - El comportamiento deberia ser siempre equivalente a `auto_trim_context=True`.
   - Si se mantiene la clave por compatibilidad, no deberia permitir desactivar la proteccion.

2. Construir el contexto final antes de decidir si hay que recortar. [Parcial]
   - Usar `ContextBuilder` como fuente principal para armar el prompt final.
   - Contar tokens sobre los mensajes reales que se van a enviar al modelo.
   - Usar `ModelManager.count_messages_tokens(messages)` cuando el modelo este cargado.

3. Proteger siempre el ultimo mensaje del usuario. [Listo]
   - El ultimo `user` debe entrar completo salvo que por si solo exceda el limite.
   - Si excede, se debe truncar de forma explicita y registrar un warning.

4. Recortar por turnos completos. [Parcial]
   - Agrupar mensajes en unidades conversacionales:
     - user + assistant
     - assistant tool_call + tool result + assistant follow-up
   - Eliminar primero los turnos mas antiguos y menos prioritarios.

5. Reinyectar resumen activo. [Listo]
   - Cuando se recorte historial, crear o actualizar un unico bloque system:
     `[RESUMEN DE CONVERSACION PREVIA]`
   - Ese bloque debe contener un `context digest` operacional, no un resumen narrativo.
   - Ese bloque debe reemplazar semanticamente los turnos eliminados.
   - No deben acumularse multiples resumenes; siempre debe existir maximo uno activo.

6. Guardar resumen en SQLite y usarlo en el contexto. [Listo]
   - `add_summary(...)` debe seguir guardando persistencia historica.
   - Pero el resumen activo tambien debe entrar al prompt actual mediante `ChatMemory` o `ContextBuilder`.

7. Definir presupuesto por secciones. [Pendiente]
   - Ejemplo:
     - system prompt: obligatorio
     - ultimo user: obligatorio
     - estado dinamico: obligatorio si existe
     - contexto inyectado: alta prioridad
     - resumen activo: alta prioridad
     - ultimos turnos: prioridad media
     - memoria semantica: prioridad ajustable
   - Cada seccion debe reportar tokens y permitir debug.

8. Hacer visible el diagnostico. [Pendiente]
   - Agregar un modo debug que muestre:
     - tokens por seccion
     - mensajes recortados
     - si se genero resumen
     - presupuesto total, reservado y usado

9. Alinear tests con el comportamiento esperado. [Parcial]
   - Restaurar o implementar los tests que esperan `[RESUMEN DE CONVERSACION PREVIA]`.
   - Agregar tests para:
     - ultimo user protegido
     - trim por turnos completos
     - `auto_trim_context=False` no desactiva la proteccion
     - conteo con `count_messages_tokens`
     - no acumulacion de resumenes
     - prompt final dentro del presupuesto real

10. Externalizar prompts tecnicos del digest. [Listo]
   - Crear `vtool_llama/config/prompts/helpers/context_digest_system.md`.
   - Crear `vtool_llama/config/prompts/helpers/context_digest_user.md`.
   - Mantener instrucciones tecnicas en ingles y salida del digest en espanol.

## Resultado esperado

El modelo deberia recibir siempre un contexto coherente, compacto y dentro del presupuesto real. Cuando haya que recortar, no se perdera la continuidad principal porque los turnos antiguos quedaran sustituidos por un resumen activo. El usuario no tendra que configurar `auto_trim_context`: la libreria debe proteger el contexto automaticamente en todos los casos.

---

# Plan de mejora de `load_character`

## Diagnostico

`load_character` cumple demasiadas responsabilidades en un solo flujo: carga datos del personaje, mergea configuracion, abre SQLite, construye estrategias de contexto, aplica memoria semantica, calienta KV cache, limpia memoria, inyecta prompt, aplica chat template y reconstruye historial.

La idea general es buena, pero el orden actual puede producir estados inconsistentes, arrastre de conversaciones anteriores y KV cache desincronizado.

## Problemas detectados

1. El KV cache puede quedar desactualizado.
   - `_warmup_character_cache()` carga `base.state` si existe.
   - No valida primero si el hash del prompt actual coincide con el hash del estado guardado.
   - Luego llama `mark_rebuild_done(prompt)`, marcando como valido un cache que podria pertenecer a un prompt viejo.

2. El chat template se aplica despues del warmup.
   - Si `chat_template_file` cambia el formato del prompt, el KV cache se calienta con un formato distinto al que se usara en inferencia.
   - El orden deberia ser: aplicar template primero, luego compilar/calentar prompt.

3. La configuracion mergeada no se propaga completamente.
   - `VToolLlama.load_character()` asigna `self._config = merged`.
   - Pero `ModelManager` fue creado antes con la config original.
   - Si el personaje overridea `temperature`, `top_p`, `max_tokens`, etc., `ModelManager.generate()` puede seguir usando defaults viejos.

4. La carga restaura automaticamente la ultima conversacion.
   - `get_or_create_conversation(name)` recupera la conversacion mas reciente del personaje.
   - Luego `load_context(...)` reconstruye el contexto desde SQLite.
   - Esto puede ser correcto para continuidad, pero tambien puede causar arrastre si el usuario esperaba una sesion nueva.

5. No se cierra explicitamente el `ChatStore` anterior.
   - Al cambiar de personaje se crea un nuevo `ChatStore`.
   - No se ve un `close()` del store anterior.
   - En Windows esto puede dejar archivos `.db` bloqueados.

6. El personaje queda parcialmente activo si falla la carga interna.
   - `CharacterManager.load_character()` asigna `_character_name` y `_char_dir` antes de completar la carga de DNA, memoria, estado, mods y sistemas avanzados.
   - Si falla algo despues, puede quedar estado parcialmente cargado.

7. Hay confusion entre contexto inmediato y limite historico.
   - `ChatMemory` se inicializa con `chat_memory_limit`.
   - `history_limit` existe y se usa en otros lugares.
   - Esto vuelve dificil razonar cuantos mensajes entran realmente al contexto inmediato.

8. `load_character` mezcla carga de personaje con preparacion de inferencia.
   - Cargar DNA/estado no deberia depender de si el modelo esta cargado.
   - Preparar prompt, template y KV cache deberia ser una fase separada.

9. El KV cache y el reset de inferencia estan en tension.
   - Si `ModelManager.generate()` resetea el estado antes de cada inferencia para evitar contaminacion, el beneficio del warmup de KV cache queda en duda.
   - Hay que decidir una estrategia unica: contexto explicito limpio o KV cache diferencial bien controlado.

## Solucion propuesta

1. Separar `load_character` en fases claras. [Parcial]
   - Fase 1: cargar datos del personaje desde disco.
   - Fase 2: aplicar configuracion del personaje.
   - Fase 3: preparar modelo/chat template si el modelo esta cargado.
   - Fase 4: abrir stores y contexto.
   - Fase 5: reconstruir o iniciar conversacion.
   - Fase 6: activar personaje solo cuando todo lo critico haya terminado.

2. Propagar configuracion mergeada a todos los subsistemas. [Listo]
   - Actualizar `self._config`.
   - Actualizar `self._model_manager._config`.
   - Actualizar `self._soul_generator._config` si corresponde.
   - Actualizar limites de `ChatMemory` de forma consistente.

3. Aplicar chat template antes del warmup. [Listo]
   - Si existe `chat_template_file`, cargarlo inmediatamente despues de mergear config.
   - Solo despues compilar prompt y decidir KV cache.

4. Validar KV cache por hash antes de cargarlo. [Listo]
   - Guardar junto al `base.state` un metadata file con:
     - prompt_hash
     - model_path/model_name
     - chat_template_hash
     - config relevante (`n_ctx`, template, etc.)
   - Si cualquier valor no coincide, regenerar cache.
   - Nunca llamar `mark_rebuild_done(prompt)` despues de cargar un cache sin validarlo.

5. Cerrar stores anteriores al cambiar de personaje. [Listo]
   - Antes de crear un nuevo `ChatStore`, llamar `self._chat_store.close()` si existe.
   - Limpiar referencias a stores semanticos anteriores.

6. Hacer explicita la politica de conversacion. [Listo]
   - Agregar parametro o config:
     - `resume_conversation=True`
     - `new_conversation=False`
   - Por defecto puede continuar la ultima conversacion, pero debe ser una decision visible.
   - Si se inicia nueva conversacion, crear nuevo conversation_id en SQLite.

7. Activar el personaje al final de la carga. [Pendiente]
   - Leer y validar todos los archivos antes de asignar `_character_name` como estado activo definitivo.
   - Si falla la carga, conservar el personaje anterior o dejar estado limpio.

8. Unificar limites de memoria. [Parcial]
   - Definir un solo concepto para mensajes recientes en RAM/contexto inmediato.
   - Separar claramente:
     - historial persistente SQLite
     - historial reciente para contexto
     - presupuesto de tokens real

9. Decidir estrategia de KV cache. [Parcial]
   - Opcion A: desactivar warmup persistente por ahora y usar contexto explicito con `reset()` siempre.
   - Opcion B: implementar KV cache diferencial completo, con restore seguro por turno y validacion estricta.
   - Para estabilidad, la opcion A es mas simple y menos propensa a contaminacion.

10. Agregar tests de carga. [Pendiente]
   - Cambio de personaje cierra DB anterior.
   - Config del personaje llega a `ModelManager`.
   - Template se aplica antes de warmup.
   - KV cache viejo no se acepta si cambia prompt/template/modelo.
   - Fallo a mitad de carga no deja personaje parcialmente activo.
   - Cargar personaje puede elegir entre continuar conversacion o iniciar una nueva.

## Resultado esperado

`load_character` deberia dejar el sistema en un estado completamente coherente: personaje activo, config aplicada, modelo alineado, contexto reconstruido segun una politica explicita y sin caches viejos contaminando inferencia. Cambiar de personaje deberia ser seguro, reversible y sin arrastre accidental de estado.

---

# Plan de mejora de SQLite y ChromaDB

## Diagnostico

La arquitectura base es correcta: SQLite debe ser la fuente de verdad del historial conversacional y ChromaDB debe funcionar como indice semantico derivado y reconstruible.

SQLite es adecuado para guardar mensajes, branches, summaries, tool calls y snapshots de contexto. ChromaDB es adecuado para busqueda semantica, pero no deberia ser considerado fuente primaria de datos.

El problema actual no es la eleccion tecnologica, sino algunas inconsistencias de ciclo de vida, filtrado, sincronizacion y estructura de rutas.

## Problemas detectados

1. El `ChatStore` anterior no se cierra al cambiar de personaje.
   - `load_character()` crea un nuevo `ChatStore`.
   - No hay cierre explicito del store anterior.
   - En Windows esto puede dejar archivos `.db` bloqueados.

2. ChromaDB de conversacion usa IDs aleatorios.
   - `index_conversation()` genera `doc_id = uuid.uuid4().hex[:12]`.
   - En rebuild se hace `clear()`, asi que funciona, pero dificulta trazabilidad.
   - No se puede relacionar facilmente un chunk con sus mensajes originales.

3. El indexado incremental no filtra branch.
   - `get_messages_since(conversation_id, since_id=last_id)` trae mensajes por `id`.
   - No filtra `branch_id`.
   - En conversaciones con branching puede indexar mensajes de ramas distintas.

4. La busqueda semantica no filtra por conversacion ni branch.
   - `SemanticRetrievalStrategy` llama `self._chroma_store.search(query, top_k=3)`.
   - Aunque los documentos tienen metadata `conversation_id` y `branch_id`, no se usa `where`.
   - Si la coleccion contiene mas de una conversacion o branch, puede recuperar contexto incorrecto.

5. El sync hash es debil.
   - Actualmente se calcula con `hashlib.sha256(str(last_msg_id).encode())`.
   - Eso solo representa el ultimo ID, no el contenido indexado ni la branch.
   - No detecta cambios reales de contenido, deletes, branch changes o rebuild parcial.

6. Documentacion y schema no coinciden.
   - `db/DETA.md` menciona tabla/metodos `memories`.
   - El schema actual no define tabla `memories`.
   - Esto confunde el modelo mental de la persistencia.

7. Inconsistencia de rutas del Soul System.
   - `list_characters()` busca `characters/<name>/soul/soul.json`.
   - `SoulGenerator` y `RuntimeSoulAccessor` usan `characters/<name>/soul.json`.
   - README tambien documenta una estructura diferente (`soul/soul.json` y `soul/life_timeline`).
   - Esto puede hacer que el sistema crea que un personaje no tiene alma aunque si exista.

8. El ChromaDB del Soul System usa otra ruta.
   - Se usa `characters/<name>/memory/life_timeline`.
   - La documentacion menciona `characters/<name>/soul/life_timeline`.
   - Hay que escoger una estructura unica.

9. `ContextInjector.mark_delivered()` manipula transacciones manualmente.
   - Usa `self._store._tx().__enter__().execute(...)`.
   - Eso entra al context manager sin cerrarlo de forma limpia.
   - Puede dejar transacciones abiertas o comportamiento dificil de depurar.

10. ChromaDB no tiene una politica clara de reconstruccion.
   - La conversacion en SQLite es la fuente primaria.
   - Chroma deberia poder borrarse y reconstruirse de forma determinista.
   - Hoy eso esta parcialmente implementado, pero faltan IDs estables y filtros estrictos.

## Solucion propuesta

1. Tratar ChromaDB como indice derivado. [Listo]
   - SQLite guarda la verdad.
   - ChromaDB solo guarda representaciones semanticas reconstruibles.
   - Si Chroma falla, la conversacion debe seguir funcionando sin perdida.

2. Cerrar recursos al cambiar de personaje. [Listo]
   - Antes de crear un nuevo `ChatStore`, llamar `self._chat_store.close()` si existe.
   - Antes de reemplazar `_semantic_chroma`, llamar `close()` si existe.
   - Esto reduce locks de archivos en Windows.

3. Usar IDs deterministas para chunks semanticos. [Listo]
   - Ejemplo: `conv_<conversation_id>_<branch_id>_<start_id>_<end_id>`.
   - Esto facilita debug, evita duplicados accidentales y permite update/upsert futuro.

4. Filtrar indexado incremental por branch. [Listo]
   - Crear metodo en `ChatStore`, por ejemplo:
     - `get_branch_messages_since(conversation_id, branch_id, since_id, limit)`
   - `index_conversation()` debe indexar solo la branch activa salvo que se pida rebuild global.

5. Filtrar busqueda semantica por metadata. [Listo]
   - `SemanticRetrievalStrategy` debe pasar:
     - `where={"conversation_id": conversation_id}`
   - Si la branch importa:
     - `where={"$and": [{"conversation_id": conversation_id}, {"branch_id": branch_id}]}`
   - Asi se evita traer recuerdos semanticos de otra conversacion o rama.

6. Mejorar el sync hash. [Listo]
   - Calcular hash con:
     - conversation_id
     - branch_id
     - start_id/end_id
     - ids de mensajes
     - contenido o hash de contenido
   - Guardar hash por branch, no solo por conversacion.

7. Alinear documentacion y schema. [Pendiente]
   - Si no existe tabla `memories`, eliminarla de `db/DETA.md`.
   - Si se quiere memoria factual en SQLite, agregar schema y metodos reales.
   - La documentacion debe reflejar exactamente lo que existe.

8. Unificar estructura del Soul System. [Listo]
   - Elegir una ruta canonica.
   - Recomendacion:
     - `characters/<name>/soul/soul.json`
     - `characters/<name>/soul/beliefs.json`
     - `characters/<name>/soul/life_timeline/`
   - Migrar o soportar fallback desde rutas antiguas:
     - `characters/<name>/soul.json`
     - `characters/<name>/memory/life_timeline/`

9. Agregar API formal para actualizar summaries/contextos. [Listo]
   - Crear metodos en `ChatStore`, por ejemplo:
     - `mark_summary_delivered(summary_id, delivered_message_id)`
     - `update_summary_end(summary_id, end_message_id)`
   - `ContextInjector` no debe tocar `_tx()` directamente.

10. Separar colecciones Chroma por responsabilidad. [Listo]
   - Conversacion:
     - path: `_memory/semantic`
     - collection: `conversation_chunks`
   - Soul:
     - path: `soul/life_timeline`
     - collection: `life_timeline`
   - Nunca mezclar documentos de soul con chunks de conversacion.

11. Agregar estado de salud y debug. [Pendiente]
   - Comando o metodo para mostrar:
     - SQLite path activo
     - conversation_id
     - branch_id
     - active_leaf
     - cantidad de mensajes
     - Chroma disponible/no disponible
     - chunks indexados
     - sync dirty/last_synced

12. Agregar tests especificos. [Parcial]
   - Cambiar de personaje cierra DB anterior.
   - Indexado incremental no mezcla branches.
   - Busqueda semantica filtra por conversation_id.
   - Rebuild produce IDs deterministas.
   - Chroma se puede borrar y reconstruir desde SQLite.
   - Rutas de soul son consistentes.
   - `ContextInjector.mark_delivered()` no usa `_tx().__enter__()` manual.

## Resultado esperado

SQLite debe ser la historia completa y confiable de la conversacion. ChromaDB debe ser un acelerador semantico reconstruible, filtrado y trazable. Cambiar de personaje o branch no debe mezclar memoria, bloquear archivos ni recuperar contexto de otra conversacion. El Soul System debe usar rutas consistentes y separadas de la memoria semantica conversacional.
