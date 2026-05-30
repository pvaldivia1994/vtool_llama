"""memory.py — Métodos de memoria y episodios de VToolLlama."""

from __future__ import annotations

from typing import Optional

from .base import VToolLlama


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


def _auto_trim_if_needed(self: VToolLlama) -> None:
    if not self._config.auto_trim_context:
        return
    if not self._model_manager.is_loaded:
        return

    from .tokenizer_utils import is_context_near_limit

    context_text = " ".join(
        m.content for m in self._memory._messages if m.content
    )
    current_tokens = self._model_manager.count_tokens(context_text)

    if not is_context_near_limit(
        current_tokens=current_tokens,
        max_tokens=self._config.n_ctx,
        reserve_tokens=self._config.context_reserve_tokens,
    ):
        return

    # 1. Generar resumen antes de empezar a recortar
    try:
        history = self.get_chat_history(limit=100, include_context=False)
        if history and len(history) > 4:
            lines = []
            for msg in history:
                if msg["role"] == "user":
                    lines.append(f"Usuario: {msg['content'][:200]}")
                elif msg["role"] == "assistant":
                    name = self._character_manager.character_name or "Personaje"
                    lines.append(f"{name}: {msg['content'][:200]}")
            conversation = "\n".join(lines)

            result = self._model_manager.generate(
                messages=[{"role": "system", "content": "Resumí la conversación en 2-3 oraciones. Solo los hechos clave, sin opiniones."},
                          {"role": "user", "content": f"CONVERSACIÓN:\n{conversation}"}],
                stream=False, max_tokens=150, temperature=0.3,
            )
            summary = result["choices"][0]["message"].get("content", "").strip()
            if summary and self._chat_store and self._memory._conversation_id:
                conv = self._chat_store.get_conversation(self._memory._conversation_id)
                if conv:
                    last_id = history[-1]["id"] if history else 0
                    self._chat_store.add_summary(
                        conversation_id=conv.id,
                        branch_id=conv.active_branch_id,
                        start_message_id=history[0]["id"] if history else 0,
                        end_message_id=last_id,
                        summary=summary,
                        reason="trim",
                    )
                    self._log_debug("EPISODE", "Resumen guardado antes de recortar contexto.")
    except Exception as e:
        self._log_debug("MEMORY", f"No se pudo generar resumen pre-trim: {e}")

    # 2. Recortar hasta que entre en el presupuesto
    while len(self._memory._messages) > 2:
        context_text = " ".join(
            m.content for m in self._memory._messages if m.content
        )
        current_tokens = self._model_manager.count_tokens(context_text)

        if not is_context_near_limit(
            current_tokens=current_tokens,
            max_tokens=self._config.n_ctx,
            reserve_tokens=self._config.context_reserve_tokens,
        ):
            break

        for i, m in enumerate(self._memory._messages):
            if m.role != "system":
                removed = self._memory._messages[i]
                del self._memory._messages[i]
                self._log_debug("MEMORY", f"Auto-trim: eliminado mensaje #{i} ({removed.role}: {str(removed.content)[:50]}...)")
                break
        else:
            break

    # 3. Asegurar que el system prompt no se haya perdido
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
