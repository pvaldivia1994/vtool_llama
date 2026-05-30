"""
Gestor de memoria de conversación para vtool_llama.

Mantiene el historial de mensajes en formato OpenAI:
  [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."},
  ]

Responsabilidades:
- Agregar mensajes al historial
- Limitar el historial según history_limit
- Auto-trim de contexto cuando se acerca al límite de tokens
- Exportar/importar el historial como JSON
- Preservar el system prompt ante operaciones de limpieza
"""

from __future__ import annotations

import json
from collections import deque
from typing import TYPE_CHECKING, Optional

from ..types import Message

if TYPE_CHECKING:
    from ..db import ChatStore
    from .context_builder import ContextBuilder
    from ..utils import TokenCounter


class ChatMemory:
    """
    Memoria de conversación con límite configurable.

    Ring buffer en RAM con maxlen. Los mensajes se persisten en SQLite
    cuando hay un ChatStore vinculado.

    Args:
        system_prompt: mensaje de sistema inicial
        history_limit: máximo de mensajes en el ring buffer
                        (excluyendo system prompt, default 25)
    """

    def __init__(
        self,
        system_prompt: str = "Eres un asistente útil y natural.",
        history_limit: int = 25,
    ):
        self._system_prompt = system_prompt
        self._history_limit = history_limit

        self._store: Optional[ChatStore] = None
        self._context_builder: Optional[ContextBuilder] = None
        self._token_counter: Optional[TokenCounter] = None
        self._conversation_id: Optional[str] = None
        self._branch_id: str = "main"
        self._active_leaf_id: int = 0

        self._messages: deque[Message] = deque(
            [Message(role="system", content=system_prompt)],
            maxlen=history_limit + 2,
        )
        self._history_limit = history_limit

    # ------------------------------------------------------------------
    # Vinculación con SQLite event store
    # ------------------------------------------------------------------

    def bind_store(
        self,
        store: ChatStore,
        context_builder: ContextBuilder,
        token_counter: TokenCounter,
        conversation_id: str,
        branch_id: str = "main",
        leaf_message_id: int = 0,
    ) -> None:
        """Vincula esta ChatMemory al event store. A partir de ahora,
        add_user_message y add_assistant_message también escriben a SQLite."""
        self._store = store
        self._context_builder = context_builder
        self._token_counter = token_counter
        self._conversation_id = conversation_id
        self._branch_id = branch_id
        self._active_leaf_id = leaf_message_id

    def load_context(self, token_budget: int) -> None:
        """Reconstruye el ring buffer desde ContextBuilder,
        respetando el límite de mensajes."""
        if not self._context_builder or not self._conversation_id:
            return
        messages = self._context_builder.build_messages(
            self._conversation_id,
            self._branch_id,
            self._active_leaf_id,
            token_budget,
            self._system_prompt,
        )
        self._messages.clear()

        # Separar system prompt del resto
        system_msg = None
        history = []
        for m in messages:
            if isinstance(m, dict):
                if m.get("role") == "system" and system_msg is None:
                    system_msg = Message(**m)
                else:
                    history.append(Message(**m))
            else:
                if m.role == "system" and system_msg is None:
                    system_msg = m
                else:
                    history.append(m)

        # Limitar a history_limit mensajes (los más recientes)
        max_history = self._history_limit
        if len(history) > max_history:
            history = history[-max_history:]

        # Reconstruir
        self._messages.append(system_msg or Message(role="system", content=self._system_prompt))
        for m in history:
            self._messages.append(m)

        if self._messages and self._messages[0].role == "system":
            self._messages[0].content = self._system_prompt

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    @property
    def messages(self) -> list[Message]:
        """Lista completa de mensajes (solo lectura recomendada)."""
        return list(self._messages)

    def _message_to_dict(self, msg: Message) -> dict:
        d = {"role": msg.role, "content": msg.content}
        if msg.tool_calls is not None:
            d["tool_calls"] = msg.tool_calls
        if msg.tool_call_id is not None:
            d["tool_call_id"] = msg.tool_call_id
        return d

    @property
    def messages_dict(self) -> list[dict]:
        """
        Retorna los mensajes como lista de dicts (formato OpenAI).
        Útil para pasar directamente a llama-cpp-python.
        """
        return [self._message_to_dict(msg) for msg in self._messages]

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        """Cambia el system prompt. Actualiza el primer mensaje."""
        self._system_prompt = value
        if self._messages and self._messages[0].role == "system":
            self._messages[0].content = value
        else:
            self._messages.insert(0, Message(role="system", content=value))

    # ------------------------------------------------------------------
    # Operaciones del historial
    # ------------------------------------------------------------------

    def _ensure_system_prompt(self) -> None:
        """Reinserta el system prompt si fue descartado por el deque."""
        if not self._messages or self._messages[0].role != "system":
            self._messages.appendleft(Message(role="system", content=self._system_prompt))

    def add_user_message(self, content: str) -> Optional[int]:
        """Agrega un mensaje del usuario al historial.
        Si hay store vinculado, también persiste en SQLite.
        Retorna el message_id si se persistió, None si no."""
        self._messages.append(Message(role="user", content=content))
        self._ensure_system_prompt()
        if self._store and self._conversation_id:
            msg_id = self._store.add_message(
                conversation_id=self._conversation_id,
                branch_id=self._branch_id,
                role="user",
                content=content,
                parent_id=self._active_leaf_id or None,
            )
            self._active_leaf_id = msg_id
            self._store.set_active_leaf(self._conversation_id, self._branch_id, msg_id)
            return msg_id
        return None

    def add_assistant_message(self, content: Optional[str] = None, tool_calls: Optional[list[dict]] = None) -> Optional[int]:
        """Agrega la respuesta del asistente al historial.
        Si hay store vinculado, también persiste en SQLite.
        Retorna el message_id si se persistió, None si no."""
        self._messages.append(Message(role="assistant", content=content, tool_calls=tool_calls))
        self._ensure_system_prompt()
        if self._store and self._conversation_id:
            msg_id = self._store.add_message(
                conversation_id=self._conversation_id,
                branch_id=self._branch_id,
                role="assistant",
                content=content or "",
                tool_calls=tool_calls,
                parent_id=self._active_leaf_id,
                token_count=self._token_counter.count_text(content) if content and self._token_counter else 0,
            )
            self._active_leaf_id = msg_id
            self._store.set_active_leaf(self._conversation_id, self._branch_id, msg_id)
            return msg_id
        return None

    def add_tool_message(self, content: str, tool_call_id: str) -> Optional[int]:
        """Agrega la respuesta de una herramienta al historial.
        Si hay store vinculado, también persiste en SQLite.
        Retorna el message_id si se persistió, None si no."""
        self._messages.append(Message(role="tool", content=content, tool_call_id=tool_call_id))
        self._ensure_system_prompt()
        if self._store and self._conversation_id:
            msg_id = self._store.add_message(
                conversation_id=self._conversation_id,
                branch_id=self._branch_id,
                role="tool",
                content=content,
                tool_call_id=tool_call_id,
                parent_id=self._active_leaf_id,
            )
            self._active_leaf_id = msg_id
            self._store.set_active_leaf(self._conversation_id, self._branch_id, msg_id)
            return msg_id
        return None

    def get_context_messages(self) -> list[dict]:
        """
        Retorna los mensajes listos para pasar a la API de
        llama-cpp-python, excluyendo mensajes vacíos.
        """
        context_msgs = []
        for m in self._messages:
            # Si tiene tool_calls o content no está vacío
            if m.tool_calls is not None or (m.content and m.content.strip()):
                context_msgs.append(self._message_to_dict(m))
            elif m.role == "assistant" and not m.content and m.tool_calls:
                context_msgs.append(self._message_to_dict(m))
        return context_msgs

    # ------------------------------------------------------------------
    # Reset y limpieza
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Limpia todo el historial excepto el system prompt."""
        # Asegurar que el system prompt no esté vacío
        prompt = self._system_prompt
        if not prompt and self._messages:
            for m in self._messages:
                if m.role == "system" and m.content:
                    prompt = m.content
                    break
        self._messages.clear()
        self._messages.append(Message(role="system", content=prompt or self._system_prompt))

    def reset(self) -> None:
        """Alias de clear()."""
        self.clear()

    # ------------------------------------------------------------------
    # Exportación / Importación JSON
    # ------------------------------------------------------------------

    def export_json(self, path: Optional[str] = None) -> str:
        """
        Exporta el historial completo como JSON.

        Args:
            path: si se proporciona, escribe el archivo en esa ruta

        Returns:
            string JSON del historial
        """
        data = [
            {"role": msg.role, "content": msg.content}
            for msg in self._messages
        ]
        json_str = json.dumps(data, ensure_ascii=False, indent=2)

        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(json_str)

        return json_str

    def import_json(self, json_str_or_path: str) -> None:
        """
        Importa un historial desde un string JSON o un archivo.

        Args:
            json_str_or_path: string JSON o ruta a un archivo .json
        """
        # Detectar si es ruta de archivo
        try:
            with open(json_str_or_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, OSError):
            # No es un archivo, tratar como string JSON
            data = json.loads(json_str_or_path)

        # Validar estructura
        if not isinstance(data, list):
            raise ValueError("El JSON debe ser una lista de mensajes")

        for item in data:
            if not isinstance(item, dict) or "role" not in item or "content" not in item:
                raise ValueError("Cada mensaje debe tener 'role' y 'content'")

        self._messages = [Message(role=item["role"], content=item["content"]) for item in data]

        # Asegurar que el primer mensaje sea system
        if not self._messages or self._messages[0].role != "system":
            self._messages.insert(0, Message(role="system", content=self._system_prompt))
