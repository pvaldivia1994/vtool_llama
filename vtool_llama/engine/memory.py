"""memory.py — Métodos de memoria y episodios de VToolLlama."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import VToolLlama
from ..types import Message, ConfigSchema


SUMMARY_MARKER = "[RESUMEN DE CONVERSACION PREVIA]"
SUMMARY_MARKER_ACCENTED = "[RESUMEN DE CONVERSACIÓN PREVIA]"
HELPER_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "config" / "prompts" / "helpers"
CONTEXT_DIGEST_SYSTEM_FALLBACK = """[CONTEXT DIGEST HELPER]

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
- ..."""
CONTEXT_DIGEST_USER_FALLBACK = """CONVERSATION TO COMPRESS:
#SOURCE

Rules:
- If the user's name appears, preserve it.
- If the user changes topic, preserve the topic change.
- If a story, scene, or roleplay thread is ongoing, state whether it remains open or was interrupted.
- Keep at most 12 bullets total.
- Each bullet must be concrete and verifiable.
- Do not add information that is not present in the conversation.
- Return only the Spanish digest sections requested by the system message."""


def _load_helper_prompt(filename: str, fallback: str) -> str:
    path = HELPER_PROMPTS_DIR / filename
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return fallback
    return text or fallback


def clear_memory(self: VToolLlama) -> None:
    with self._lock:
        self._memory.clear()
    self._log_debug("MEMORY", "Historial de conversación limpiado")

VToolLlama.clear_memory = clear_memory


def reset_chat(self: VToolLlama) -> None:
    self.clear_memory()

VToolLlama.reset_chat = reset_chat


def get_memory(self: VToolLlama) -> list[dict[str, str]]:
    return self._memory.messages_dict

VToolLlama.get_memory = get_memory


def export_memory_json(self: VToolLlama, path: Optional[str] = None) -> str:
    return self._memory.export_json(path)

VToolLlama.export_memory_json = export_memory_json


def import_memory_json(self: VToolLlama, json_str_or_path: str) -> None:
    with self._lock:
        self._memory.import_json(json_str_or_path)
    self._log_debug("MEMORY", "Historial importado correctamente")

VToolLlama.import_memory_json = import_memory_json


def set_system_prompt(self: VToolLlama, prompt: str) -> None:
    with self._lock:
        self._memory.system_prompt = prompt
        self._config.system_prompt = prompt
        self._character_manager._prompt_dirty = True
    self._log_debug("CONFIG", f"System prompt actualizado: {prompt[:50]}...")

VToolLlama.set_system_prompt = set_system_prompt


def trim_memory(self: VToolLlama) -> int:
    with self._lock:
        if not self._model_manager.is_loaded:
            self._log_warning("No hay modelo cargado para contar tokens exactos.")
            self._memory.clear()
            return 0

        # El deque maneja el límite automáticamente por maxlen
        self._log_debug("MEMORY", "Trim no necesario: ChatMemory usa deque con maxlen.")
        return 0

VToolLlama.trim_memory = trim_memory


def _archive_to_chroma(self: VToolLlama, messages: list[Message]) -> bool:
    """Guarda mensajes crudos en archived_memory (v9).
    Síncrono — retorna True si TODOS se guardaron correctamente.
    Si falla, el trim NO debe continuar."""
    archived = getattr(self, "_archived_chroma", None)
    if not archived or not archived.is_available:
        return False
    try:
        for msg in messages:
            if not msg.content or not msg.content.strip():
                continue
            msg_id = getattr(msg, 'id', '0')
            doc_id = f"archived_{msg_id}"
            # v13: usar [SPEAK] como tag universal para mensajes archivados
            speaker_tag = "PLAYER" if msg.role == "user" else "AGENT"
            archived.add_document(
                doc_id=doc_id,
                document=f"[{speaker_tag}][SPEAK] {msg.content}",
                metadata={
                    "type": "archived",
                    "role": msg.role,
                    "speaker_tag": speaker_tag,
                    "conversation_id": self._memory._conversation_id or "",
                    "message_id": getattr(msg, 'id', 0),
                },
            )
        return True
    except Exception as e:
        self._log_debug("MEMORY", f"Error archivando en ChromaDB: {e}")
        return False

VToolLlama._archive_to_chroma = _archive_to_chroma


def _auto_trim_if_needed(self: VToolLlama) -> None:
    if not self._model_manager.is_loaded:
        return

    from .tokenizer_utils import is_context_near_limit

    def _is_digest_message(msg: Message) -> bool:
        content = msg.content or ""
        return SUMMARY_MARKER in content or SUMMARY_MARKER_ACCENTED in content

    def _count_current() -> int:
        messages = self._memory.get_context_messages()
        if hasattr(self._model_manager, "count_messages_tokens"):
            return self._model_manager.count_messages_tokens(messages)
        text = " ".join(m.get("content", "") for m in messages if m.get("content"))
        return self._model_manager.count_tokens(text)

    def _role_label(role: str) -> str:
        if role == "user":
            return "Usuario"
        if role == "assistant":
            return self._character_manager.character_name or "Personaje"
        if role == "tool":
            return "Tool"
        return role.capitalize()

    def _format_source(messages: list[Message], max_chars: int = 6000) -> str:
        lines = []
        used = 0
        for msg in messages:
            if not msg.content or not msg.content.strip():
                continue
            content = " ".join(msg.content.split())
            line = f"{_role_label(msg.role)}: {content[:500]}"
            if used + len(line) > max_chars and lines:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines)

    def _fallback_digest(messages: list[Message]) -> str:
        user_facts = []
        recent_user = []
        recent_assistant = []
        for msg in messages:
            content = " ".join((msg.content or "").split())
            if not content:
                continue
            lowered = content.lower()
            if msg.role == "user":
                if "mi nombre es" in lowered or "me llamo" in lowered:
                    user_facts.append(content[:180])
                recent_user.append(content[:180])
            elif msg.role == "assistant":
                recent_assistant.append(content[:180])

        lines = [
            "Hechos estables:",
            *[f"- {fact}" for fact in user_facts[-3:]],
            "Estado actual:",
            *[f"- Ultima respuesta relevante del personaje: {item}" for item in recent_assistant[-1:]],
            "Preferencias del usuario:",
            "- No inferidas automaticamente.",
            "Relacion y tono:",
            "- Mantener continuidad con el tono previo sin contradecir al ultimo mensaje del usuario.",
            "Hilos abiertos:",
            *[f"- Ultimo pedido relevante del usuario: {item}" for item in recent_user[-2:]],
            "Descartar:",
            "- Detalles repetidos o cerrados que no afecten la siguiente respuesta.",
        ]
        return "\n".join(line for line in lines if line.strip())

    def _digest_with_llm(messages: list[Message]) -> str:
        system_prompt = _load_helper_prompt(
            "context_digest_system.md",
            CONTEXT_DIGEST_SYSTEM_FALLBACK,
        )
        user_prompt_template = _load_helper_prompt(
            "context_digest_user.md",
            CONTEXT_DIGEST_USER_FALLBACK,
        )

        def digest_once(source: str, max_tokens: int = 250) -> str:
            user_prompt = user_prompt_template.replace("#SOURCE", source)
            result = self._model_manager.generate(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=False,
                max_tokens=max_tokens,
                temperature=0.1,
            )
            if not isinstance(result, dict):
                return ""
            choices = result.get("choices")
            if not isinstance(choices, list) or not choices:
                return ""
            first = choices[0]
            if not isinstance(first, dict):
                return ""
            message = first.get("message")
            if not isinstance(message, dict):
                return ""
            content = message.get("content", "")
            return content.strip() if isinstance(content, str) else ""

        try:
            partials = []
            for i in range(0, len(messages), 12):
                source = _format_source(messages[i:i + 12])
                if source:
                    digest = digest_once(source)
                    if digest:
                        partials.append(digest)
            if not partials:
                return _fallback_digest(messages)
            if len(partials) == 1:
                return partials[0]
            merged = "\n\n--- DIGEST PARCIAL ---\n\n".join(partials)
            return digest_once(merged, max_tokens=300) or partials[-1]
        except Exception as e:
            self._log_debug("MEMORY", f"No se pudo generar context digest con LLM: {e}")
            return _fallback_digest(messages)

    if not is_context_near_limit(
        current_tokens=_count_current(),
        max_tokens=self._config.n_ctx,
        reserve_tokens=self._config.context_reserve_tokens,
        threshold_percent=80.0,
    ):
        return

    last_user_index = None
    for i in range(len(self._memory._messages) - 1, -1, -1):
        if self._memory._messages[i].role == "user":
            last_user_index = i
            break

    digest_candidates = [
        msg for i, msg in enumerate(self._memory._messages)
        if msg.role != "system" and i != last_user_index and not _is_digest_message(msg)
    ]

    # ── v9: archivar mensajes crudos en ChromaDB (síncrono) ─────────
    archived_ok = False
    if len(digest_candidates) > 2:
        archived_ok = self._archive_to_chroma(digest_candidates)
        if not archived_ok:
            self._archive_retries += 1
            self._log_debug("MEMORY", f"ChromaDB no disponible para archivar "
                            f"(intento {self._archive_retries})")
        else:
            self._archive_retries = 0
            # Watermark en SQLite
            if self._chat_store and self._memory._conversation_id:
                archived_ids = [getattr(msg, 'id', None) for msg in digest_candidates if getattr(msg, 'id', None)]
                if archived_ids:
                    self._chat_store.update_archived_watermark(
                        self._memory._conversation_id, archived_ids
                    )

    # Forzar trim si se excedieron los reintentos
    max_retries = getattr(self._config, "memory_archive_max_retries", 3)
    if not archived_ok and self._archive_retries >= max_retries:
        self._log_warning("ChromaDB no responde tras varios intentos. Forzando trim sin archivar.")

    # ── Digest extractivo SOLO (sin LLM) ─────────────────────────────
    digest = _fallback_digest(digest_candidates) if digest_candidates else ""

    if digest:
        history = self.get_chat_history(limit=100, include_context=False)
        if history and self._chat_store and self._memory._conversation_id:
            conv = self._chat_store.get_conversation(self._memory._conversation_id)
            if conv:
                self._chat_store.add_summary(
                    conversation_id=conv.id,
                    branch_id=conv.active_branch_id,
                    start_message_id=history[0]["id"],
                    end_message_id=history[-1]["id"],
                    summary=digest,
                    reason="trim",
                )

        maxlen = self._memory._messages.maxlen
        messages = [m for m in self._memory._messages if not _is_digest_message(m)]
        if maxlen is not None:
            while len(messages) >= maxlen:
                for idx, msg in enumerate(messages):
                    if msg.role != "system" and idx != last_user_index:
                        del messages[idx]
                        if last_user_index is not None and idx < last_user_index:
                            last_user_index -= 1
                        break
                else:
                    break
        insert_at = 1 if messages and messages[0].role == "system" else 0
        messages.insert(insert_at, Message(role="system", content=f"{SUMMARY_MARKER_ACCENTED}\n{digest}"))
        self._memory._messages = type(self._memory._messages)(messages, maxlen=maxlen)

    last_user_index = None
    for i in range(len(self._memory._messages) - 1, -1, -1):
        if self._memory._messages[i].role == "user":
            last_user_index = i
            break

    while len(self._memory._messages) > 2:
        if not is_context_near_limit(
            current_tokens=_count_current(),
            max_tokens=self._config.n_ctx,
            reserve_tokens=self._config.context_reserve_tokens,
            threshold_percent=80.0,
        ):
            break

        for i, msg in enumerate(self._memory._messages):
            if msg.role != "system" and i != last_user_index:
                removed = self._memory._messages[i]
                # Archivar si no estaba en digest_candidates (v9)
                removed_id = getattr(removed, 'id', None)
                if removed_id is not None and not any(
                    getattr(m, 'id', None) == removed_id for m in digest_candidates
                ):
                    self._archive_to_chroma([removed])
                del self._memory._messages[i]
                if last_user_index is not None and i < last_user_index:
                    last_user_index -= 1
                self._log_debug("MEMORY", f"Auto-trim: eliminado mensaje #{i} ({removed.role}: {str(removed.content)[:50]}...)")
                break
        else:
            break

    if not self._memory._messages or self._memory._messages[0].role != "system" or not self._memory._messages[0].content:
        self._log_debug("MEMORY", "System prompt perdido durante trim, restaurando...")
        self._inject_personality_into_system_prompt()


VToolLlama._auto_trim_if_needed = _auto_trim_if_needed





def save_episode(self: VToolLlama) -> "EpisodeSnapshot":
    non_system = [m for m in self._memory.messages if m.role != "system"]
    last_messages = []
    for m in non_system[-5:]:
        msg = {"role": m.role, "content": m.content or ""}
        last_messages.append(msg)

    if not last_messages:
        raise RuntimeError("No hay mensajes para guardar como episodio.")

    summary = self._generate_episode_summary(last_messages)

    # Guardar en SQLite si hay store, sino en JSON files (fallback)
    if self._chat_store and self._memory._conversation_id:
        self._chat_store.add_summary(
            conversation_id=self._memory._conversation_id,
            branch_id=self._memory._branch_id,
            start_message_id=max(0, self._memory._active_leaf_id - len(last_messages)),
            end_message_id=self._memory._active_leaf_id,
            summary=summary,
            reason="manual",
        )
        self._log_debug("EPISODE", "Episodio guardado en SQLite.")
        from ..types import EpisodeSnapshot
        return EpisodeSnapshot(episode_id=self._memory._active_leaf_id, summary=summary, messages=last_messages)
    else:
        episode = self._character_manager.save_episode(
            messages=last_messages,
            summary=summary,
        )
        return episode

VToolLlama.save_episode = save_episode


def _generate_episode_summary(self: VToolLlama, messages: list[dict]) -> str:
    conversation_text = ""
    for m in messages:
        role_label = "Usuario" if m["role"] == "user" else "Personaje"
        conversation_text += f"{role_label}: {m.get('content', '')}\n"

    if not self._model_manager.is_loaded:
        return conversation_text[:200].strip()

    try:
        result = self._model_manager.generate(
            messages=[
                {"role": "system", "content": "Genera un resumen BREVE (máximo 2 oraciones) de esta conversación. Solo el resumen, sin explicaciones."},
                {"role": "user", "content": f"Conversación:\n{conversation_text}\n\nResumen:"},
            ],
            stream=False,
            max_tokens=100,
            temperature=0.3,
        )
        summary = result["choices"][0]["message"].get("content", "").strip()
        return summary or conversation_text[:200].strip()
    except Exception as e:
        self._log_warning(f"No se pudo generar resumen con LLM: {e}")
        return conversation_text[:200].strip()

VToolLlama._generate_episode_summary = _generate_episode_summary


def list_episodes(self: VToolLlama) -> list[dict]:
    if self._chat_store and self._memory._conversation_id:
        summaries = self._chat_store.get_summaries(
            self._memory._conversation_id,
            self._memory._branch_id,
            limit=100,
        )
        return [
            {
                "file": f"episode_{s.id:03d}",
                "episode_id": s.id,
                "timestamp": s.created_at,
                "summary": s.summary[:80],
                "message_count": s.end_message_id - s.start_message_id,
                "topic": s.semantic_topic,
            }
            for s in summaries
        ]
    return self._character_manager.list_episodes()

VToolLlama.list_episodes = list_episodes


def load_episode(self: VToolLlama, episode_id: int) -> None:
    if self._chat_store and self._memory._conversation_id:
        summary = self._chat_store.get_summary_by_id(episode_id)
        if not summary:
            raise ValueError(f"Episodio #{episode_id} no encontrado.")
        self._chat_store.checkout(
            self._memory._conversation_id,
            summary.branch_id,
            summary.end_message_id,
        )
        self._memory._branch_id = summary.branch_id
        self._memory._active_leaf_id = summary.end_message_id
        self._log_debug("EPISODE", f"Checkout a episodio #{episode_id} (no-destructivo).")
    else:
        self._character_manager.load_episode(episode_id)
    self._inject_personality_into_system_prompt()

VToolLlama.load_episode = load_episode


def delete_episode(self: VToolLlama, episode_id: int) -> bool:
    if self._chat_store:
        return self._chat_store.delete_summary(episode_id)
    return self._character_manager.delete_episode(episode_id)

VToolLlama.delete_episode = delete_episode
