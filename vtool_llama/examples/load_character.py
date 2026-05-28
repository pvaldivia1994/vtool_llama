"""
Ejemplo: seleccionar un personaje y conversar con él.

Muestra los personajes disponibles, permite elegir uno,
y luego inicia una conversación en tiempo real.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from vtool_llama import VToolLlama


def select_character(llm: VToolLlama) -> str:
    chars = llm.list_characters()
    if not chars:
        print("No hay personajes disponibles.")
        sys.exit(1)

    print("\nPersonajes disponibles:")
    for i, name in enumerate(chars, 1):
        dna_dir = os.path.join(
            os.path.dirname(__file__), '..', 'personajes', name, 'dna'
        )
        identity_path = os.path.join(dna_dir, 'identity.json')
        if os.path.exists(identity_path):
            import json
            with open(identity_path, encoding='utf-8') as f:
                ident = json.load(f)
            rol = ident.get('role', '')
            fondo = ident.get('background', '')
            desc = f" — {rol}" if rol else ""
            if fondo:
                desc += f" ({fondo})"
        else:
            desc = ""

        print(f"  {i}. {name}{desc}")

    while True:
        try:
            choice = input("\nSeleccioná un personaje (número o nombre): ").strip()
            if not choice:
                continue
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(chars):
                    return chars[idx]
            else:
                if choice in chars:
                    return choice
            print(f"Opción inválida. Elegí entre 1-{len(chars)} o un nombre.")
        except (ValueError, IndexError):
            print(f"Opción inválida. Elegí entre 1-{len(chars)}.")


def main():
    print("=== Character Chat ===")

    with VToolLlama(auto_load=True) as llm:
        name = select_character(llm)

        try:
            llm.load_character(name)
            print(f"\n--- {name} cargado. Escribí 'salir' para terminar. ---")
            print("Tip: Ctrl+C para salir en cualquier momento.\n")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

        while True:
            try:
                prompt = input("Tú: ")
                if prompt.strip().lower() in ("salir", "exit", "quit"):
                    print("\nCerrando sesión...")
                    break

                if not prompt.strip():
                    continue

                print(f"{name}:", end=" ", flush=True)
                for chunk in llm.stream_chat(prompt):
                    if isinstance(chunk, str):
                        print(chunk, end="", flush=True)
                print()

            except KeyboardInterrupt:
                print("\n\nCerrando sesión...")
                break
            except Exception as e:
                print(f"\nError: {e}")


if __name__ == "__main__":
    main()
