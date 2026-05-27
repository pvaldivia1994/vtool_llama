"""
Sistema de Slash Commands para vtool_llama.

Permite registrar comandos con prefijo / que se ejecutan
directamente sin pasar por el LLM. Esto permite operaciones
de bajo nivel como agregar memorias, reconstruir estado,
exportar configuración, etc.

Ejemplo:
    /mem recuerda que uso CUDA
    /rebuild
    /state
    /mood energy 0.9

Regla fundamental:
    Si el texto empieza con '/', se ejecuta directamente
    y se bypasea el modelo.
"""

from __future__ import annotations

from typing import Callable, Optional


class SlashCommandRegistry:
    """
    Registro y ejecución de slash commands.

    Cada comando se registra con un nombre y un callable
    que recibe los argumentos como string y retorna un
    string de respuesta.

    Ejemplo de uso:
        registry = SlashCommandRegistry()

        @registry.command("mem")
        def handle_mem(args: str) -> str:
            # guardar memoria
            return "Memoria guardada."

        result = registry.handle("/mem recuerda que uso CUDA")
        # result = "Memoria guardada."
    """

    def __init__(self):
        self._commands: dict[str, Callable[[str], str]] = {}
        self._descriptions: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        handler: Callable[[str], str],
        description: str = "",
    ) -> None:
        """
        Registra un slash command.

        Args:
            name: nombre del comando (sin el /). Ej: "mem"
            handler: función que recibe args (str) y retorna respuesta (str)
            description: descripción del comando para ayuda
        """
        self._commands[name.lower()] = handler
        if description:
            self._descriptions[name.lower()] = description

    def command(
        self,
        name: str,
        description: str = "",
    ) -> Callable:
        """
        Decorador para registrar un slash command.

        Ejemplo:
            @registry.command("rebuild", description="Reconstruye el estado")
            def handle_rebuild(args: str) -> str:
                ...
        """
        def decorator(fn: Callable[[str], str]) -> Callable[[str], str]:
            self.register(name, fn, description)
            return fn
        return decorator

    # ------------------------------------------------------------------
    # Ejecución
    # ------------------------------------------------------------------

    def is_slash_command(self, text: str) -> bool:
        """Retorna True si el texto es un slash command registrado."""
        if not text or not text.startswith("/"):
            return False
        parts = text[1:].strip().split(None, 1)
        if not parts:
            return False
        cmd_name = parts[0].lower()
        return cmd_name in self._commands

    def handle(self, text: str) -> Optional[str]:
        """
        Parsea y ejecuta un slash command.

        Args:
            text: texto completo del usuario (ej: "/mem recuerda algo")

        Returns:
            Respuesta del comando como string, o None si no es
            un slash command válido.
        """
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

    # ------------------------------------------------------------------
    # Información
    # ------------------------------------------------------------------

    def list_commands(self) -> dict[str, str]:
        """
        Retorna un diccionario {nombre: descripción} de todos
        los comandos registrados.
        """
        result = {}
        for name in sorted(self._commands.keys()):
            result[name] = self._descriptions.get(name, "Sin descripción")
        return result

    def get_help_text(self) -> str:
        """Retorna un texto de ayuda formateado con todos los comandos."""
        commands = self.list_commands()
        if not commands:
            return "No hay comandos registrados."

        lines = ["Comandos disponibles:"]
        for name, desc in commands.items():
            lines.append(f"  /{name} — {desc}")
        return "\n".join(lines)
