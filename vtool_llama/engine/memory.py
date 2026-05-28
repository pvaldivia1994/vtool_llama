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

        removed = self._memory.trim_to_token_budget(
            max_context_tokens=self._config.n_ctx,
            reserve_tokens=self._config.context_reserve_tokens,
            count_fn=self._model_manager.count_tokens,
        )

        if removed > 0:
            self._log_debug("MEMORY", f"Contexto recortado: {removed} mensaje(s) eliminado(s)")

        return removed

VToolLlama.trim_memory = trim_memory


def _auto_trim_if_needed(self: VToolLlama) -> None:
    if not self._config.auto_trim_context:
        return
    if not self._model_manager.is_loaded:
        return

    context_text = " ".join(
        m.content for m in self._memory.messages if m.content
    )
    current_tokens = self._model_manager.count_tokens(context_text)

    from .tokenizer_utils import is_context_near_limit

    if is_context_near_limit(
        current_tokens=current_tokens,
        max_tokens=self._config.n_ctx,
        reserve_tokens=self._config.context_reserve_tokens,
    ):
        removed = self.trim_memory()
        if removed > 0:
            self._log_debug("MEMORY", f"Auto-trim: {removed} mensaje(s) eliminado(s)")

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
    return self._character_manager.list_episodes()

VToolLlama.list_episodes = list_episodes


def load_episode(self: VToolLlama, episode_id: int) -> None:
    self._character_manager.load_episode(episode_id)
    self._inject_personality_into_system_prompt()

VToolLlama.load_episode = load_episode


def delete_episode(self: VToolLlama, episode_id: int) -> bool:
    return self._character_manager.delete_episode(episode_id)

VToolLlama.delete_episode = delete_episode
