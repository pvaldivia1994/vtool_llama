"""slash_commands.py — VToolLlama slash command handlers."""

from __future__ import annotations

import json
from typing import Optional

from .base import VToolLlama


def _handle_slash_command(self: VToolLlama, text: str) -> Optional[str]:
    if not text or not text.startswith("/"):
        return None

    if self._slash_commands.is_slash_command(text):
        self._log_debug("SLASH", f"Ejecutando comando: {text}")
        result = self._slash_commands.handle(text)
        return result

    return None

VToolLlama._handle_slash_command = _handle_slash_command


def _register_default_slash_commands(self: VToolLlama) -> None:
    self._slash_commands.register(
        "mem", self._cmd_mem,
        "Agrega una memoria persistente. Uso: /mem <texto>",
    )
    self._slash_commands.register(
        "rebuild", self._cmd_rebuild,
        "Reconstruye el estado de personalidad del agente.",
    )
    self._slash_commands.register(
        "state", self._cmd_state,
        "Muestra el estado actual del agente.",
    )
    self._slash_commands.register(
        "memories", self._cmd_memories,
        "Lista todas las memorias persistentes.",
    )
    self._slash_commands.register(
        "mood", self._cmd_mood,
        "Cambia un valor de mood. Uso: /mood <key> <value>",
    )
    self._slash_commands.register(
        "rel", self._cmd_rel,
        "Modifica o consulta el relationship state. Uso: /rel <trust> <familiarity>",
    )
    self._slash_commands.register(
        "help", self._cmd_help,
        "Muestra la lista de comandos disponibles.",
    )
    self._slash_commands.register(
        "scene_view", self._cmd_scene_view,
        "Describe la escena actual basándose en los últimos mensajes de la conversación.",
    )
    self._slash_commands.register(
        "save_episode", self._cmd_save_episode,
        "Guarda un snapshot de la conversación actual como episodio versionado.",
    )
    self._slash_commands.register(
        "episodes", self._cmd_episodes,
        "Gestiona episodios guardados.",
        sub={
            "": "Listar episodios",
            "load N": "Restaurar episodio N (checkout no destructivo)",
            "delete N": "Eliminar episodio N",
        },
    )
    self._slash_commands.register(
        "history", self._cmd_history,
        "Muestra los últimos mensajes del chat. Uso: /history [N=10]",
    )
    self._slash_commands.register(
        "autosave", self._cmd_autosave,
        "Activa auto-guardado cada N mensajes. Uso: /autosave <N> (0 = desactivar)",
    )
    self._slash_commands.register(
        "semantic", self._cmd_semantic,
        "Indexa la conversación en ChromaDB.",
        sub={
            "": "Indexado incremental",
            "rebuild": "Reconstruir índice completo",
        },
    )
    self._slash_commands.register(
        "clean", self._cmd_clean,
        "Limpia todo el historial de chat de la sesión actual.",
    )
    self._slash_commands.register(
        "config", self._cmd_config,
        "Muestra la configuración actual del modelo y el personaje.",
    )
    self._slash_commands.register(
        "tick", self._cmd_tick,
        "El personaje actúa según el contexto actual sin intervención del usuario.",
    )
    self._slash_commands.register(
        "resume", self._cmd_resume,
        "Genera un resumen de toda la conversación y lo guarda como episodio.",
    )
    self._slash_commands.register(
        "context", self._cmd_context,
        "Gestiona el contexto inyectable del personaje.",
        sub={
            "character <texto>": "Agregar estado emocional/mental/físico",
            "thoughts <texto>": "Agregar pensamientos internos",
            "goals <texto>": "Agregar objetivos activos",
            "time <texto>": "Agregar momento del día/clima",
            "world <texto>": "Agregar eventos del entorno",
            "memory <texto>": "Agregar hechos importantes",
            "scene <texto>": "Agregar descripción de escena",
            "player <texto>": "Agregar acción del jugador (el character reacciona a esto)",
            "custom <texto>": "Agregar contexto personalizado",
            "list": "Listar entradas activas",
            "rm <id>": "Eliminar entrada por ID",
            "clear": "Limpiar todas las entradas",
            "debug": "Mostrar bloque exacto que se inyecta",
        },
    )

VToolLlama._register_default_slash_commands = _register_default_slash_commands


def _cmd_mem(self: VToolLlama, args: str) -> str:
    if not args.strip():
        return "Uso: /mem <texto a recordar>"
    entry = self._character_manager.add_memory(
        content=args.strip(),
        always_include=True,
        priority=1.0,
    )
    return f"✓ Memoria guardada (id: {entry.id}): {entry.content}"

VToolLlama._cmd_mem = _cmd_mem


def _cmd_rebuild(self: VToolLlama, args: str) -> str:
    self.rebuild_personality_state()
    return "✓ Estado de personalidad reconstruido."

VToolLlama._cmd_rebuild = _cmd_rebuild


def _cmd_state(self: VToolLlama, args: str) -> str:
    state = self.get_state_info()
    return json.dumps(state, ensure_ascii=False, indent=2)

VToolLlama._cmd_state = _cmd_state


def _cmd_memories(self: VToolLlama, args: str) -> str:
    memories = self._character_manager.memories
    if not memories:
        return "No hay memorias guardadas."
    lines = []
    for m in memories:
        tags = f" [{', '.join(m.tags)}]" if m.tags else ""
        pin = " 📌" if m.always_include else ""
        lines.append(f"  [{m.id}] {m.content}{tags}{pin}")
    return "Memorias:\n" + "\n".join(lines)

VToolLlama._cmd_memories = _cmd_memories


def _cmd_mood(self: VToolLlama, args: str) -> str:
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

    from ..types import CharacterMod
    mod = CharacterMod(id=f"temp_{layer}", target_layer=layer, override_value=value, intensity=intensity)
    self._character_manager.set_mod(mod)
    self._inject_personality_into_system_prompt()
    return f"✓ Mod aplicado a '{layer}': {value} (Intensidad {intensity:.1f})"

VToolLlama._cmd_mood = _cmd_mood


def _cmd_rel(self: VToolLlama, args: str) -> str:
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

VToolLlama._cmd_rel = _cmd_rel


def _cmd_help(self: VToolLlama, args: str) -> str:
    query = args.strip()
    if query:
        cmds = self._slash_commands.list_commands()
        if query in cmds:
            return f"/{query} — {cmds[query]}"
        return f"Comando '{query}' no encontrado. Usá /help para ver todos."
    return self._slash_commands.get_help_text()

VToolLlama._cmd_help = _cmd_help


def _cmd_save_episode(self: VToolLlama, args: str) -> str:
    try:
        episode = self.save_episode()
        return f"✓ Episodio #{episode.episode_id} guardado. Resumen: {episode.summary[:100]}..."
    except Exception as e:
        return f"Error al guardar episodio: {e}"

VToolLlama._cmd_save_episode = _cmd_save_episode


def _cmd_scene_view(self: VToolLlama, args: str) -> str:
    if not self._model_manager.is_loaded:
        return "No hay modelo cargado."

    history = self.get_chat_history(limit=15)
    if not history:
        return "No hay historial de chat para describir la escena."

    lines = []
    for msg in history:
        if msg["role"] == "user":
            lines.append(f"Usuario: {msg['content']}")
        elif msg["role"] == "assistant":
            name = self._character_manager.character_name or "Personaje"
            lines.append(f"{name}: {msg['content']}")

    conversation = "\n".join(lines)
    query = args.strip()

    if query:
        prompt = (
            "Analiza toda la conversación, pero da prioridad absoluta a los eventos "
            "más recientes para determinar el estado actual de la historia.\n\n"

            "Si información antigua contradice información reciente, considera válida "
            "la información más reciente.\n\n"

            "Respondé únicamente a la consulta utilizando el estado actual de la escena.\n\n"

            "Reglas:\n"
            "- Basate únicamente en información presente en la conversación.\n"
            "- No inventes hechos, pensamientos, emociones, objetos o personajes.\n"
            "- Si la información no existe o no puede inferirse razonablemente, indicá que no está claro.\n"
            "- Ignorá elementos que ya no formen parte de la escena actual.\n"
            "- Priorizá siempre los eventos más recientes.\n"
            "- Respondé de forma directa.\n"
            "- Máximo un párrafo.\n"
            "- No hagas resúmenes de la historia.\n"
            "- No agregues explicaciones sobre tu razonamiento.\n\n"

            f"CONSULTA:\n{query}\n\n"
            f"CONVERSACIÓN:\n{conversation}"
        )

        prefix = f"**{query}:** "

    else:
        prompt = (
            "Reconstruí únicamente la escena actual utilizando toda la conversación.\n\n"

            "Los eventos más recientes tienen prioridad absoluta.\n"
            "Si algo ocurrió anteriormente pero ya no forma parte de la situación actual, no lo menciones.\n\n"

            "Describí únicamente:\n"
            "- Qué está ocurriendo ahora.\n"
            "- Quiénes están presentes ahora.\n"
            "- Dónde se desarrolla la escena si es conocido.\n"
            "- Información relevante que siga vigente en este momento.\n\n"

            "Reglas:\n"
            "- Usá únicamente información presente en la conversación.\n"
            "- No inventes detalles.\n"
            "- No inventes emociones, sonidos, olores, pensamientos o acciones.\n"
            "- No agregues información implícita que no esté respaldada por el contexto.\n"
            "- No hagas un resumen de toda la historia.\n"
            "- Concentrate exclusivamente en el estado actual de la escena.\n"
            "- Respondé en un único párrafo.\n"
            "- Sé directo, concreto y objetivo.\n"
            "- Máximo 100 palabras.\n"
            "- No uses listas ni encabezados.\n\n"

            f"CONVERSACIÓN:\n{conversation}"
        )

        prefix = ""

    try:
        result = self._model_manager.generate(
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            max_tokens=512,
            temperature=0.7,
        )
        respuesta = result["choices"][0]["message"].get("content", "").strip()
        output = f"{prefix}{respuesta}" if prefix else respuesta

        # Guardar escena vía orquestador
        if not query and self._chat_store and self._memory._conversation_id:
            from ..orquestador import ContextInjector
            injector = ContextInjector(
                self._chat_store,
                self._memory._conversation_id,
                self._memory._branch_id,
            )
            injector.save_scene(respuesta)
            self._character_manager._prompt_dirty = True
            self._log_debug("SCENE", "Nueva escena guardada en SQLite.")
            if self._config.inject_scene_context:
                output += "\n\n(La escena se inyectará en el contexto del próximo mensaje.)"

        return output
    except Exception as e:
        return f"Error: {e}"

VToolLlama._cmd_scene_view = _cmd_scene_view


def _cmd_episodes(self: VToolLlama, args: str) -> str:
    parts = args.strip().split() if args else []

    if len(parts) == 2 and parts[0] == "load":
        try:
            ep_id = int(parts[1])
            self.load_episode(ep_id)
            return f"✓ Episodio #{ep_id} restaurado (checkout no destructivo)."
        except (ValueError, Exception) as e:
            return f"Error: {e}"

    if len(parts) == 2 and parts[0] == "delete":
        try:
            ep_id = int(parts[1])
            ok = self.delete_episode(ep_id)
            return f"✓ Episodio #{ep_id} eliminado." if ok else f"Episodio #{ep_id} no encontrado."
        except (ValueError, Exception) as e:
            return f"Error: {e}"

    episodes = self.list_episodes()
    if not episodes:
        return "No hay episodios guardados."
    lines = ["📋 Episodios guardados:"]
    for ep in episodes:
        ts = ep.get('timestamp', '')
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(ts)
            fecha = dt.strftime("%d/%m/%y %H:%M")
        except Exception:
            fecha = ts[:16] if ts else "?"

        topic = f" [{ep.get('topic', '')}]" if ep.get('topic') else ""
        msgs = ep.get('message_count', 0)
        summary = ep['summary'] + "…" if len(ep['summary']) >= 80 else ep['summary']
        lines.append(f"  #{ep['episode_id']:03d}  {fecha}{topic}  ({msgs} msgs)")
        lines.append(f"      {summary}")
    lines.append("")
    lines.append("  /episodes load N   — Volver al episodio N")
    lines.append("  /episodes delete N — Eliminar episodio N")
    return "\n".join(lines)

VToolLlama._cmd_episodes = _cmd_episodes


def _cmd_history(self: VToolLlama, args: str) -> str:
    try:
        n = max(1, min(50, int(args.strip()))) if args.strip() else 10
    except ValueError:
        n = 10

    history = self.get_chat_history(limit=n, include_context=True)
    if not history:
        return "No hay historial de chat."

    lines = [f"📜 Últimos {len(history)} mensajes:"]
    for msg in history:
        role_icon = "👤" if msg["role"] == "user" else "🤖" if msg["role"] == "assistant" else "📌"
        content = msg["content"][:120] + "…" if len(msg["content"]) > 120 else msg["content"]
        lines.append(f"  {role_icon} {content}")
    return "\n".join(lines)

VToolLlama._cmd_history = _cmd_history


def _cmd_autosave(self: VToolLlama, args: str) -> str:
    try:
        n = int(args.strip())
    except (ValueError, AttributeError):
        return "Uso: /autosave <N> (cada N mensajes, 0 = desactivar)"

    self.active_auto_save_at(n)
    return f"✓ Auto-save {'activado' if n > 0 else 'desactivado'} cada {n} mensajes." if n > 0 else "✓ Auto-save desactivado."

VToolLlama._cmd_autosave = _cmd_autosave


def _cmd_semantic(self: VToolLlama, args: str) -> str:
    if not self._semantic_chroma:
        return "ChromaDB no configurado. Usá semantic_memory=True al cargar el personaje."

    rebuild = args.strip().lower() == "rebuild"
    try:
        count = self.index_conversation(incremental=not rebuild)
        return f"✓ Indexados {count} chunks semánticos{' (rebuild completo)' if rebuild else ''}."
    except Exception as e:
        return f"Error indexando: {e}"

VToolLlama._cmd_semantic = _cmd_semantic


def _cmd_clean(self: VToolLlama, args: str) -> str:
    # 1) Limpiar RAM
    self._memory.clear()

    # 2) Limpiar SQLite (soft-delete todos los mensajes activos)
    if self._chat_store and self._memory._conversation_id:
        msgs = self._chat_store.get_branch_messages(
            self._memory._conversation_id, self._memory._branch_id, limit=5000
        )
        for m in msgs:
            if m.status == "active":
                self._chat_store.soft_delete_message(m.id)
        self._chat_store.mark_semantic_dirty(self._memory._conversation_id)

    # 3) Limpiar ChromaDB semántico
    if self._semantic_chroma and self._semantic_chroma.is_available:
        self._semantic_chroma.clear()

    # 4) Limpiar memorias persistentes (long_term.json)
    if self._character_manager:
        self._character_manager.memories.clear()
        self._character_manager._needs_rebuild = True
        self._character_manager.save_state()

    # 5) Resetear active_leaf
    if self._memory._conversation_id and self._chat_store:
        self._chat_store.set_active_leaf(
            self._memory._conversation_id, self._memory._branch_id, 0
        )
    self._memory._active_leaf_id = 0

    self._log_info("Memoria limpiada completamente (RAM + SQLite + ChromaDB + long_term).")
    return "🧹 Memoria limpiada completamente."

VToolLlama._cmd_clean = _cmd_clean


def _cmd_config(self: VToolLlama, args: str) -> str:
    import json
    from dataclasses import asdict

    base = asdict(self._config_manager.get())

    if self._character_manager.is_loaded and self._character_manager._char_dir:
        char_config_path = self._character_manager._char_dir / "config.json"
        if char_config_path.exists():
            with open(char_config_path, "r", encoding="utf-8") as f:
                overrides = json.load(f)
        else:
            overrides = {}
    else:
        overrides = {}

    actual = asdict(self._config)

    lines = [f"Personaje: {self._character_manager.character_name if self._character_manager.is_loaded else 'Ninguno'}"]

    if self._model_manager.is_loaded:
        info = self._model_manager.get_model_info()
        lines.append(f"Modelo: {info.get('model_name', '?')}")
        lines.append(f"Contexto: {info.get('context_size', 0)} tokens")

    lines.append("")
    lines.append("── Configuración activa ──")

    # Mostrar solo campos relevantes
    relevant = ["temperature", "top_p", "top_k", "repeat_penalty", "max_tokens",
                "n_ctx", "n_batch", "gpu_layers", "threads", "flash_attn",
                "debug", "chat_memory_limit", "auto_summary_interval",
                "semantic_memory_enabled", "disable_thinking", "system_prompt"]

    for key in relevant:
        if key in actual:
            val = actual[key]
            override = " ⬅ personaje" if key in overrides else ""
            lines.append(f"  {key}: {val}{override}")

    return "\n".join(lines)

VToolLlama._cmd_config = _cmd_config


def _cmd_context(self: VToolLlama, args: str) -> str:
    from ..orquestador import ContextInjector, CONTEXT_TYPES

    # Scene se crea manualmente o via /scene_view
    user_types = dict(CONTEXT_TYPES)  # incluye scene

    if not self._chat_store or not self._memory._conversation_id:
        return "No hay personaje cargado."

    injector = ContextInjector(
        self._chat_store,
        self._memory._conversation_id,
        self._memory._branch_id,
    )
    parts = args.strip().split(maxsplit=1) if args.strip() else []
    cmd = parts[0].lower() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    if cmd == "debug":
        contexts = injector.get_active_contexts()
        if not contexts:
            return "No hay entradas de contexto activas."
        lines = ["🧠 Bloque exacto que se inyecta en el prompt:\n"]
        for ctx in contexts:
            lines.append(f"  system: {ctx}")
        lines.append(f"\nTotal: {len(contexts)} entradas activas.")
        return "\n".join(lines)

    if cmd == "list":
        entries = injector.list()
        if not entries:
            return "No hay entradas de contexto."
        lines = ["📋 Contexto inyectable:"]
        for e in entries:
            lines.append(f"  #{e.id} {e.tag} {e.content[:80]}")
        return "\n".join(lines)

    if cmd == "rm":
        try:
            eid = int(rest.strip())
            ok = injector.remove(eid)
            self._character_manager._prompt_dirty = True
            return f"✓ Entrada #{eid} eliminada." if ok else f"Entrada #{eid} no encontrada."
        except (ValueError, IndexError):
            return "Uso: /context rm <id>"

    if cmd == "clear":
        n = injector.clear()
        self._character_manager._prompt_dirty = True
        return f"✓ {n} entradas de contexto eliminadas."

    if cmd in user_types:
        if not rest:
            from ..orquestador import CONTEXT_DEFINITIONS
            definicion = CONTEXT_DEFINITIONS.get(cmd, "")
            tag = injector.tag_for_type(cmd)
            if definicion:
                return f"{tag} — {definicion}"
            return f"{tag} Sin descripción disponible."
        cid = injector.add(cmd, rest)
        self._character_manager._prompt_dirty = True
        tag = injector.tag_for_type(cmd)
        return f"✓ {tag} {rest}\n(Entrada #{cid} — se inyectará en el próximo chat.)"

    tipos = ", ".join(user_types.keys())
    return (
        "Uso: /context <tipo> <texto>\n"
        f"Tipos: {tipos}\n\n"
        "  /context list              — listar entradas\n"
        "  /context rm <id>           — eliminar entrada\n"
        "  /context clear             — limpiar todo\n"
        "  /context debug             — mostrar bloque exacto que se inyecta\n\n"
        "Ejemplos:\n"
        "  /context character Está triste\n"
        "  /context time Es un nuevo día\n"
        "  /context thoughts Piensa en su pasado\n"
        "  /context world Llueve en la ciudad"
    )

VToolLlama._cmd_context = _cmd_context


def _cmd_tick(self: VToolLlama, args: str) -> str:
    """El personaje actúa según el contexto actual sin mensaje del usuario."""
    if not self._model_manager.is_loaded:
        return "No hay modelo cargado."
    if not self._memory._conversation_id:
        return "No hay personaje cargado."

    messages = self._memory.get_context_messages()

    # Agregar contexto activo al prompt actual
    from ..orquestador import ContextInjector
    if self._chat_store and self._memory._conversation_id:
        inj = ContextInjector(self._chat_store, self._memory._conversation_id, self._memory._branch_id)

        prompt_extra = args.strip()
        if prompt_extra:
            inj.add("player", prompt_extra)

        active = inj.get_active_contexts()
        for ctx in active:
            messages.append({"role": "system", "content": ctx})

    messages.append({"role": "user", "content": "[CONTINUE]"})

    try:
        result = self._model_manager.generate(
            messages=messages,
            stream=False,
            max_tokens=512,
            temperature=0.8,
        )
        response = result["choices"][0]["message"].get("content", "").strip()
        if not response:
            return "El personaje no respondió."

        self._memory.add_assistant_message(response)

        from ..orquestador import ContextInjector
        if self._chat_store and self._memory._conversation_id:
            injector = ContextInjector(
                self._chat_store,
                self._memory._conversation_id,
                self._memory._branch_id,
            )
            active = injector.list(only_active=True)
            if active:
                injector.mark_delivered([e.id for e in active])

        return response
    except Exception as e:
        return f"Error: {e}"

VToolLlama._cmd_tick = _cmd_tick


def _cmd_resume(self: VToolLlama, args: str) -> str:
    """Genera un resumen de toda la conversación y lo guarda como episodio."""
    if not self._model_manager.is_loaded:
        return "No hay modelo cargado."
    if not self._chat_store or not self._memory._conversation_id:
        return "No hay personaje cargado."

    history = self.get_chat_history(limit=100, include_context=False)
    if not history:
        return "No hay historial para resumir."

    lines = []
    for msg in history:
        if msg["role"] == "user":
            lines.append(f"Usuario: {msg['content']}")
        elif msg["role"] == "assistant":
            name = self._character_manager.character_name or "Personaje"
            lines.append(f"{name}: {msg['content']}")

    conversation = "\n".join(lines)

    try:
        result = self._model_manager.generate(
            messages=[{
                "role": "system",
                "content": (
                    "Resumí toda la conversación en un párrafo. "
                    "Incluí los eventos importantes, cambios emocionales, "
                    "decisiones clave y el estado actual de la historia. "
                    "Sé objetivo y conciso. Máximo 4 oraciones."
                ),
            }, {
                "role": "user",
                "content": f"CONVERSACIÓN:\n{conversation}",
            }],
            stream=False,
            max_tokens=256,
            temperature=0.3,
        )
        resume = result["choices"][0]["message"].get("content", "").strip()
        if not resume:
            return "No se pudo generar el resumen."

        # Guardar como episodio en SQLite
        last_id = history[-1]["id"] if history else 0
        conv = self._chat_store.get_conversation(self._memory._conversation_id)
        self._chat_store.add_summary(
            conversation_id=self._memory._conversation_id,
            branch_id=self._memory._branch_id,
            start_message_id=history[0]["id"] if history else 0,
            end_message_id=last_id,
            summary=resume,
            reason="manual",
        )
        self._log_debug("EPISODE", "Resumen guardado como episodio.")
        return f"📝 Resumen guardado:\n\n{resume}"

    except Exception as e:
        return f"Error generando resumen: {e}"

VToolLlama._cmd_resume = _cmd_resume
