# Plan Base — Template para implementación

## Propósito

Este archivo sirve como estructura base para cualquier plan de mejora o implementación en `vtool_llama`. Copiar y completar según necesidad.

## Estructura del proyecto

```
vtool_llama/
├── vtool_llama/
│   ├── engine/           # Core: chat, character, memory, base
│   ├── compiler/         # Compilación del system prompt
│   ├── orquestador/      # Tags, contexto, inyección
│   ├── model/            # ModelManager, inferencia, KV cache
│   ├── db/               # SQLite (ChatStore), ChromaDB
│   ├── character/        # CharacterManager, DNA
│   ├── tools/            # Tool calling, parser, streaming
│   ├── types/            # Dataclasses compartidas
│   ├── config/           # Config global, templates .jinja
│   └── characters/       # Personajes (luna, default, etc.)
├── tests/                # Tests unitarios + integración
└── .plans/               # Planes de mejora
```

## Reglas para implementar

1. **Un cambio por commit** — no mezclar refactor con features
2. **Tests primero o a la par** — 72+ tests existentes, no romperlos
3. **Backward compatibility** — cambios opt-in via config, default false
4. **Documentar siempre** — archivos DETA.md, AGENT.md, README.md
5. **No código muerto** — si no se usa, eliminarlo

## Formato del plan

```markdown
# Plan mejoras vX

## Objetivo
[Una línea]

## Diagnóstico
[Problema actual con ejemplos de código]

## Cambios propuestos
### 1. [Nombre del cambio]
[Código/diagrama del cambio]

### 2. [Siguiente cambio]
...

## Archivos afectados
| Archivo | Cambio |
|---------|--------|

## Riesgos
[Lo que podría salir mal y mitigación]

## Resultado esperado
[Cómo se comporta el sistema después]
```

## Tags del sistema (v13+)

```
[LUNA][ACT] *acción*           → Personaje actúa
[LUNA][SPEAK] diálogo          → Personaje habla
[LUNA][THOUGHT] *pensamiento*  → Personaje piensa
[PLAYER][SPEAK] texto          → Usuario habla
[PLAYER][ACT] *acción*         → Usuario actúa
[DEFINE]                       → Definición permanente
[STATE]                        → Estado actual
[SCENE]                        → Descripción de escena
```

## Configuraciones clave

```json
{
  "history_limit": 40,          → Tamaño del deque de mensajes
  "expand_n_ctx_for_core": true, → Core invisible en KV cache
  "inject_dynamic_state": false, → Estado dinámico desactivado
  "temperature": 0.92,
  "repeat_penalty": 1.1
}
```
