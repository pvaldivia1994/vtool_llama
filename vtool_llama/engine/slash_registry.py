"""
SlashCommandRegistry — Registro y ejecución de comandos con prefijo / .
"""

from __future__ import annotations

from typing import Callable, Optional


class SlashCommandRegistry:
    def __init__(self):
        self._commands: dict[str, Callable[[str], str]] = {}
        self._descriptions: dict[str, str] = {}
        self._sub_commands: dict[str, dict[str, str]] = {}

    def register(
        self,
        name: str,
        handler: Callable[[str], str],
        description: str = "",
        sub: Optional[dict[str, str]] = None,
    ) -> None:
        self._commands[name.lower()] = handler
        if description:
            self._descriptions[name.lower()] = description
        if sub:
            self._sub_commands[name.lower()] = sub

    def command(
        self,
        name: str,
        description: str = "",
        sub: Optional[dict[str, str]] = None,
    ) -> Callable:
        def decorator(fn: Callable[[str], str]) -> Callable[[str], str]:
            self.register(name, fn, description, sub)
            return fn
        return decorator

    def is_slash_command(self, text: str) -> bool:
        if not text or not text.startswith("/"):
            return False
        parts = text[1:].strip().split(None, 1)
        if not parts:
            return False
        cmd_name = parts[0].lower()
        return cmd_name in self._commands

    def handle(self, text: str) -> Optional[str]:
        if not text or not text.startswith("/"):
            return None
        parts = text[1:].strip().split(None, 1)
        if not parts:
            return None
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        handler = self._commands.get(cmd_name)
        if handler is None:
            return None
        try:
            return handler(args)
        except Exception as e:
            return f"Error ejecutando /{cmd_name}: {e}"

    def list_commands(self) -> dict:
        """Retorna estructura jerárquica de comandos.

        Returns:
            dict con:
              - name: descripción principal
              - sub: {sub_name: sub_desc} (siempre presente, puede ser vacío)
        """
        result = {}
        for name in sorted(self._commands.keys()):
            sub = self._sub_commands.get(name)
            result[name] = {
                "desc": self._descriptions.get(name, "Sin descripción"),
                "sub": dict(sub) if sub else {},
            }
        return result

    def get_help_text(self) -> str:
        commands = self.list_commands()
        if not commands:
            return "No hay comandos registrados."

        lines = ["Comandos disponibles:"]
        for name, entry in commands.items():
            desc = entry["desc"].split("\n")[0]
            lines.append(f"  /{name} — {desc}")
            for sname, sdesc in entry["sub"].items():
                lines.append(f"      /{name} {sname} — {sdesc}")
        return "\n".join(lines)
