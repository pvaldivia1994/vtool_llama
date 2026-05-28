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

import copy
import json
from typing import Optional

from ..types import Message


class ChatMemory:
    """
    Memoria de conversación con límite configurable y auto-trim.

    Args:
        system_prompt: mensaje de sistema inicial
        history_limit: máximo de mensajes en el historial
                       (excluyendo el system prompt)
        auto_trim: si es True, recorta automáticamente cuando
                   el contexto se acerca al límite
    """

    def __init__(
        self,
        system_prompt: str = "Eres un asistente útil y natural.",
        history_limit: int = 40,
        auto_trim: bool = True,
    ):
        self._system_prompt = system_prompt
        self._history_limit = history_limit
        self._auto_trim = auto_trim

        # El historial interno siempre empieza con el system prompt
        self._messages: list[Message] = [
            Message(role="system", content=system_prompt)
        ]

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    @property
    def messages(self) -> list[Message]:
        """Lista completa de mensajes (solo lectura recomendada)."""
        return self._messages

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

    def add_user_message(self, content: str) -> None:
        """Agrega un mensaje del usuario al historial."""
        self._messages.append(Message(role="user", content=content))
        self._apply_history_limit()

    def add_assistant_message(self, content: Optional[str] = None, tool_calls: Optional[list[dict]] = None) -> None:
        """Agrega la respuesta del asistente al historial."""
        self._messages.append(Message(role="assistant", content=content, tool_calls=tool_calls))
        self._apply_history_limit()

    def add_tool_message(self, content: str, tool_call_id: str) -> None:
        """Agrega la respuesta de una herramienta al historial."""
        self._messages.append(Message(role="tool", content=content, tool_call_id=tool_call_id))
        self._apply_history_limit()

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
    # Límite del historial
    # ------------------------------------------------------------------

    def _apply_history_limit(self) -> None:
        """
        Si el historial (sin contar system prompt) excede el límite,
        elimina los mensajes más antiguos preservando el system
        prompt y los últimos mensajes importantes.
        """
        if self._history_limit <= 0:
            return

        # Contar mensajes que no sean system
        non_system = [m for m in self._messages if m.role != "system"]
        if len(non_system) <= self._history_limit:
            return

        # Cuántos eliminar
        excess = len(non_system) - self._history_limit

        # Preservar system prompt + mensajes recientes
        # Eliminar los 'excess' mensajes no-system más antiguos
        kept_non_system = non_system[excess:]  # elimina los primeros 'excess'
        self._messages = [
            m for m in self._messages if m.role == "system"
        ] + kept_non_system

    # ------------------------------------------------------------------
    # Auto-trim por contexto (tokens)
    # ------------------------------------------------------------------

    def trim_to_token_budget(
        self,
        max_context_tokens: int,
        reserve_tokens: int,
        count_fn: callable,
    ) -> int:
        """
        Recorta el historial hasta que quepa en el presupuesto de
        tokens. Usa el callable count_fn para estimar tokens.

        Args:
            max_context_tokens: límite duro (n_ctx)
            reserve_tokens: tokens a reservar para la respuesta
            count_fn: función que recibe texto y retorna cantidad
                      de tokens aproximada

        Returns:
            cantidad de mensajes eliminados
        """
        if not self._auto_trim:
            return 0

        budget = max_context_tokens - reserve_tokens
        if budget <= 0:
            return 0

        removed = 0
        # Calcular tokens totales del historial actual
        total_tokens = sum(
            count_fn(msg.content) for msg in self._messages
        )

        # Mientras excedamos el presupuesto, eliminar mensajes
        # antiguos (pero preservar system prompt)
        while total_tokens > budget and len(self._messages) > 2:
            # Buscar el mensaje no-system más antiguo
            for i, msg in enumerate(self._messages):
                if msg.role != "system":
                    removed_tokens = count_fn(self._messages[i].content)
                    del self._messages[i]
                    total_tokens -= removed_tokens
                    removed += 1
                    break

        return removed

    # ------------------------------------------------------------------
    # Reset y limpieza
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Limpia todo el historial excepto el system prompt."""
        self._messages = [
            Message(role="system", content=self._system_prompt)
        ]

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
