"""inline.py — InlineProcessor para comandos #, [], :, * en mensajes del usuario."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .base import VToolLlama

HASH_PATTERN = re.compile(r'#(\w+)(?:\s+(.*?))?#', re.DOTALL)
SCENE_PATTERN = re.compile(r'\[(\w+(?:\s+\w+)+[^\]]*?)\]')  # [DOS O MAS PALABRAS] → scene
TIME_PAREN_PATTERN = re.compile(r'\((\w+(?:\s+\w+)+[^)]*?)\)')  # (DOS O MAS PALABRAS) → time
CHAR_DASH_PATTERN = re.compile(r'-(\w+(?:\s+\w+)+[^-]*?)-')  # -TEXTO LARGO- → #char (pensamiento personaje)
THOUGHT_PATTERN = re.compile(r':([^:]+?):')                  # :texto: → pensamiento
ACTION_PATTERN = re.compile(r'\*(.*?)\*')                     # *texto* → acción


class InlineProcessor:
    """Procesa comandos inline en el mensaje del usuario.

    Pipeline: HashCommands (#) → SceneContext ([]) → Action/Thought (* / :)
    Cada paso extrae su patrón, lo ejecuta, y preserva el texto
    circundante como segmentos cronológicos.
    """

    def __init__(self):
        self._hash_commands: dict[str, dict] = {}

    def register(self, name: str, handler: Callable, description: str) -> None:
        self._hash_commands[name.lower()] = {"handler": handler, "desc": description}

    def has_inline_commands(self, text: str) -> bool:
        return bool(HASH_PATTERN.search(text)
                     or SCENE_PATTERN.search(text)
                     or TIME_PAREN_PATTERN.search(text)
                     or CHAR_DASH_PATTERN.search(text)
                     or ACTION_PATTERN.search(text)
                     or THOUGHT_PATTERN.search(text))

    def process(self, text: str, llm: VToolLlama) -> list[dict]:
        """Procesa el texto y retorna lista de mensajes.
        Cada mensaje: {"role": "user", "tag": "SAYS"|"DOES"|"THINKS", "content": str}
        El contenido NO incluye el tag del speaker — eso lo agrega chat()
        usando _user_tag.
        """
        # Paso 1: extraer #comando# → segmentos de texto
        segments = self._extract_hash(text, llm)

        # Paso 2: extraer [scene] de cada segmento
        segments = self._extract_scene(segments, llm)

        # Paso 3: extraer (time) de cada segmento → ContextInjector.add('time', texto)
        segments = self._extract_time(segments, llm)

        # Paso 4: extraer -texto- → #char (pensamiento del personaje)
        segments = self._extract_char_dash(segments, llm)

        # Paso 5: dividir por *acción* y :pensamiento: boundaries
        segments = self._split_by_markers(segments)

        # Paso 5: armar mensajes con tags SAYS/DOES/THINKS
        return self._build_messages(segments)

    def _extract_hash(self, text: str, llm: VToolLlama) -> list[str]:
        """Extrae #comando args# REGISTRADOS, ejecuta handler.
        Comandos no registrados se dejan como texto literal.
        Retorna segmentos de texto."""
        segments: list[str] = []
        last_end = 0

        for match in HASH_PATTERN.finditer(text):
            cmd_name = match.group(1).lower()

            if cmd_name not in self._hash_commands:
                continue  # no registrado → se deja como texto literal

            prefix = text[last_end:match.start()]
            if prefix.strip():
                segments.append(prefix.strip())

            cmd_args = (match.group(2) or "").strip()
            try:
                self._hash_commands[cmd_name]["handler"](cmd_args, llm)
            except Exception as e:
                llm._log_warning(f"HASH command #{cmd_name} error: {e}")
            last_end = match.end()

        suffix = text[last_end:]
        if suffix.strip():
            segments.append(suffix.strip())

        return segments if segments else [text]

    def _extract_scene(self, segments: list[str], llm: VToolLlama) -> list[str]:
        """De cada segmento, extrae [texto] → ContextInjector.add('scene', texto)."""
        if not llm._chat_store or not llm._memory._conversation_id:
            return segments

        from ..orquestador import ContextInjector

        injector = ContextInjector(
            llm._chat_store,
            llm._memory._conversation_id,
            llm._memory._branch_id,
        )
        result: list[str] = []

        for segment in segments:
            cleaned = segment
            for match in SCENE_PATTERN.finditer(segment):
                content = match.group(1).strip()
                if content:
                    injector.add("scene", content)
                    llm._log_debug("INLINE", f"[scene] {content}")
                cleaned = cleaned.replace(match.group(0), "", 1)
            cleaned = cleaned.strip()
            if cleaned:
                result.append(cleaned)

        return result if result else segments

    def _extract_time(self, segments: list[str], llm: VToolLlama) -> list[str]:
        """De cada segmento, extrae (texto multi-palabra) → ContextInjector.add('time', texto).
        El () se elimina del texto del usuario (como [] y #)."""
        if not llm._chat_store or not llm._memory._conversation_id:
            return segments

        from ..orquestador import ContextInjector

        injector = ContextInjector(
            llm._chat_store,
            llm._memory._conversation_id,
            llm._memory._branch_id,
        )
        result: list[str] = []

        for segment in segments:
            cleaned = segment
            for match in TIME_PAREN_PATTERN.finditer(segment):
                content = match.group(1).strip()
                if content:
                    injector.add("time", content)
                    llm._log_debug("INLINE", f"(time) {content}")
                cleaned = cleaned.replace(match.group(0), "", 1)
            cleaned = cleaned.strip()
            if cleaned:
                result.append(cleaned)

        return result if result else segments

    def _extract_char_dash(self, segments: list[str], llm: VToolLlama) -> list[str]:
        """De cada segmento, extrae -texto multi-palabra- → buffer _char_thought_buffer.
        Se inyecta en el turno actual como [ASSISTANT=Name][THINKS] *texto*.
        El -texto- se elimina del mensaje del usuario."""
        name = (llm._character_manager.character_name or "ASSISTANT").capitalize()
        buffer = getattr(llm, "_char_thought_buffer", None)
        if buffer is None:
            return segments

        result: list[str] = []
        for segment in segments:
            cleaned = segment
            for match in CHAR_DASH_PATTERN.finditer(segment):
                content = match.group(1).strip()
                if content:
                    buffer.append((name, content))
                    llm._log_debug("INLINE", f"-char- buffer: [ASSISTANT={name}][THINKS] *{content}*")
                cleaned = cleaned.replace(match.group(0), "", 1)
            cleaned = cleaned.strip()
            if cleaned:
                result.append(cleaned)

        return result if result else segments

    def _split_by_markers(self, segments: list[str]) -> list[str]:
        """Divide segmentos por *acción* y :pensamiento: boundaries.
        Cada *...* y :...: se convierte en su propio segmento.
        El texto entre marcadores se mantiene como segmento SAYS."""
        import re
        # Combina los patrones en uno: busca *...* o :...: o texto entre ellos
        SPLIT_RE = re.compile(r'(\*[^*]+\*|:[^:]+:)')
        result: list[str] = []
        for seg in segments:
            if not seg.strip():
                continue
            parts = SPLIT_RE.split(seg)
            for part in parts:
                stripped = part.strip()
                if stripped:
                    result.append(stripped)
        return result

    def _build_messages(self, segments: list[str]) -> list[dict]:
        """Etiqueta cada segmento como SAYS/DOES/THINKS según su contenido."""
        messages: list[dict] = []
        for seg in segments:
            if not seg.strip():
                continue
            tag, content = self._tag_segment(seg)
            messages.append({
                "role": "user",
                "tag": tag,
                "content": content,
            })
        return messages

    def _tag_segment(self, segment: str) -> tuple[str, str]:
        """Retorna (tag, content_limpio) para un segmento.
        *acción* → (DOES, *acción*)   preserva *
        :pensamiento: → (THINKS, pensamiento)  limpia :
        texto normal → (SAYS, texto)
        """
        has_action = bool(ACTION_PATTERN.search(segment))
        has_thought = bool(THOUGHT_PATTERN.search(segment))

        if has_action:
            return ("DOES", segment)

        if has_thought:
            content = THOUGHT_PATTERN.sub(r'\1', segment)
            return ("THINKS", content.strip())

        return ("SAYS", segment)

    def list_commands(self) -> dict[str, str]:
        return {k: v["desc"] for k, v in self._hash_commands.items()}


# ── Handlers de registracion ──────────────────────────────────────────

def _cmd_hash_mem(args: str, llm: VToolLlama) -> None:
    """Guarda memoria persistente."""
    if not args:
        return
    llm._character_manager.add_memory(
        content=args, always_include=True, priority=1.0,
    )
    llm._log_info(f"[#mem] Memoria guardada: {args}")


def _cmd_hash_time(args: str, llm: VToolLlama) -> None:
    """#time desc → ContextInjector.add('time', desc)"""
    if not args or not llm._chat_store or not llm._memory._conversation_id:
        return
    from ..orquestador import ContextInjector
    inj = ContextInjector(llm._chat_store, llm._memory._conversation_id, llm._memory._branch_id)
    inj.add("time", args)
    llm._log_debug("INLINE", f"[#time] {args}")


def _cmd_hash_scene(args: str, llm: VToolLlama) -> None:
    """#scene desc → ContextInjector.save_scene(desc)  [reemplaza]"""
    if not args or not llm._chat_store or not llm._memory._conversation_id:
        return
    from ..orquestador import ContextInjector
    inj = ContextInjector(llm._chat_store, llm._memory._conversation_id, llm._memory._branch_id)
    inj.save_scene(args)
    llm._log_debug("INLINE", f"[#scene] {args} [reemplaza]")


def _cmd_hash_world(args: str, llm: VToolLlama) -> None:
    """#world desc → ContextInjector.add('world', desc)"""
    if not args or not llm._chat_store or not llm._memory._conversation_id:
        return
    from ..orquestador import ContextInjector
    inj = ContextInjector(llm._chat_store, llm._memory._conversation_id, llm._memory._branch_id)
    inj.add("world", args)
    llm._log_debug("INLINE", f"[#world] {args}")


def _cmd_hash_goal(args: str, llm: VToolLlama) -> None:
    """#goal desc → ContextInjector.add('goals', desc)"""
    if not args or not llm._chat_store or not llm._memory._conversation_id:
        return
    from ..orquestador import ContextInjector
    inj = ContextInjector(llm._chat_store, llm._memory._conversation_id, llm._memory._branch_id)
    inj.add("goals", args)
    llm._log_debug("INLINE", f"[#goal] {args}")


def _cmd_hash_player(args: str, llm: VToolLlama) -> None:
    """#player desc → ContextInjector.add('player', desc)"""
    if not args or not llm._chat_store or not llm._memory._conversation_id:
        return
    from ..orquestador import ContextInjector
    inj = ContextInjector(llm._chat_store, llm._memory._conversation_id, llm._memory._branch_id)
    inj.add("player", args)
    llm._log_debug("INLINE", f"[#player] {args}")


def _cmd_hash_thought(args: str, llm: VToolLlama) -> None:
    """#thought content → ContextInjector.add('thoughts', content)"""
    if not args or not llm._chat_store or not llm._memory._conversation_id:
        return
    from ..orquestador import ContextInjector
    inj = ContextInjector(llm._chat_store, llm._memory._conversation_id, llm._memory._branch_id)
    inj.add("thoughts", args)
    llm._log_debug("INLINE", f"[#thought] {args}")


def _cmd_hash_char(args: str, llm: VToolLlama) -> None:
    """#char thought → buffer temporal, se inyecta en el turno actual como system message.
    Formato: [ASSISTANT=Name][THINKS] *...* — el modelo lo reconoce como pensamiento propio.
    """
    if not args:
        return
    name = (llm._character_manager.character_name or "ASSISTANT").capitalize()
    buffer = getattr(llm, "_char_thought_buffer", None)
    if buffer is not None:
        buffer.append((name, args))
    llm._log_debug("INLINE", f"[#char] buffer: [ASSISTANT={name}][THINKS] *{args}*")


def _cmd_hash_tag(args: str, llm: VToolLlama) -> None:
    """#tag NOMBRE → cambia el tag del usuario para la sesión.
    Ejemplo: #tag LIUNIK# → los mensajes se etiquetan [USER=LIUNIK][SAYS/DOES/THINKS]
    """
    tag = args.strip().upper()
    if not tag or not tag.isalpha():
        llm._log_warning(f"[#tag] Tag inválido: '{args}' — solo letras")
        return
    tag = tag[:8]
    llm._user_tag = tag
    if getattr(llm, "_chat_store", None) and getattr(llm._memory, "_conversation_id", None):
        try:
            llm._chat_store.set_state(llm._memory._conversation_id, "user_tag", tag)
        except Exception:
            pass
    llm._log_info(f"[#tag] Tag cambiado a [{tag}]")


def _cmd_hash_recall(args: str, llm: VToolLlama) -> None:
    """#recall topic → fuerza búsqueda en ChromaDB."""
    if not args:
        return
    chroma = getattr(llm, "_semantic_chroma", None)
    if not chroma or not chroma.is_available:
        llm._log_debug("INLINE", f"[#recall] ChromaDB no disponible")
        return
    try:
        results = chroma.search(args, n_results=5)
        if results:
            combined = " ".join(results)
            # Inyectar como contexto
            if llm._chat_store and llm._memory._conversation_id:
                from ..orquestador import ContextInjector
                inj = ContextInjector(
                    llm._chat_store, llm._memory._conversation_id, llm._memory._branch_id
                )
                inj.add("memory", f"[RECUPERADO: {args}] {combined}")
            llm._log_debug("INLINE", f"[#recall] {len(results)} resultados")
    except Exception as e:
        llm._log_debug("INLINE", f"[#recall] error: {e}")


# ── Registro por defecto ──────────────────────────────────────────────

def register_default_hash_commands(processor: InlineProcessor) -> None:
    processor.register("time", _cmd_hash_time, "#time desc — Avanza o describe el tiempo en escena")
    processor.register("scene", _cmd_hash_scene, "#scene desc — Reemplaza la escena completa")
    processor.register("char", _cmd_hash_char, "#char pensamiento — Inyecta pensamiento interno al personaje")
    processor.register("world", _cmd_hash_world, "#world desc — Agrega lore/evento del mundo")
    processor.register("goal", _cmd_hash_goal, "#goal desc — Fija objetivo activo del personaje")
    processor.register("player", _cmd_hash_player, "#player desc — Describe estado del jugador")
    processor.register("thought", _cmd_hash_thought, "#thought content — Inyecta pensamiento narrativo externo")
    processor.register("recall", _cmd_hash_recall, "#recall tema — Recupera memoria de ChromaDB")
    processor.register("mem", _cmd_hash_mem, "#mem texto — Guarda memoria persistente")
    processor.register("tag", _cmd_hash_tag, "#tag NOMBRE — Cambia el tag del usuario (ej: #tag LIUNIK#)")
