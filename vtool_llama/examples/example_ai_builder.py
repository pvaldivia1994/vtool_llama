import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from vtool_llama import VToolLlama


def _non_empty_input(prompt: str) -> str:
    val = input(prompt).strip()
    while not val:
        val = input("  El campo no puede estar vacío: ").strip()
    return val


def _multi_line_input(header: str) -> list[str]:
    items: list[str] = []
    print(header)
    while True:
        r = input("- ").strip()
        if not r:
            break
        items.append(r)
    return items


def collect_context() -> tuple[str, str]:
    parts: list[str] = []

    print("\n--- 1. IDENTIDAD ---")
    char_name = _non_empty_input("Nombre público: ")
    role = _non_empty_input("Rol: ")
    age = input("Edad: ").strip()
    background = _non_empty_input("Historia de fondo: ")
    scenario = input("Escenario (opcional): ").strip()

    parts.append(f"Name: {char_name}")
    parts.append(f"Role: {role}")
    if age:
        parts.append(f"Age: {age}")
    parts.append(f"Background: {background}")
    if scenario:
        parts.append(f"Scenario: {scenario}")

    print("\n--- 2. PERSONALIDAD ---")
    traits = input("Rasgos (separados por coma): ").strip()
    motivations = _non_empty_input("Motivaciones: ")
    flaws = input("Defectos (separados por coma): ").strip()
    inner_conflict = input("Conflicto interno (opcional): ").strip()
    triggers = input("Triggers emocionales (ej. 'gritos → miedo'): ").strip()

    if traits:
        parts.append(f"Traits: {traits}")
    if motivations:
        parts.append(f"Motivations: {motivations}")
    if flaws:
        parts.append(f"Flaws: {flaws}")
    if inner_conflict:
        parts.append(f"Inner conflict: {inner_conflict}")
    if triggers:
        parts.append(f"Emotional triggers: {triggers}")

    print("\n--- 3. HABLA ---")
    style = input("Estilo (Casual, Formal, Poético): ").strip()
    tone = input("Tono (Amable, Sarcástico, etc.): ").strip()
    verbosity = input("Verbosidad (Bajo/Medio/Alto): ").strip()
    patterns = input("Patrones de habla (opcional): ").strip()

    if style:
        parts.append(f"Speech style: {style}")
    if tone:
        parts.append(f"Tone: {tone}")
    if verbosity:
        parts.append(f"Verbosity: {verbosity}")
    if patterns:
        parts.append(f"Speech patterns: {patterns}")

    print("\n--- 4. REGLAS ---")
    core_rules = _multi_line_input("Reglas principales (Enter vacío para terminar):")
    never_do = _multi_line_input("NUNCA hacer (Enter vacío para terminar):")
    if core_rules:
        parts.append("Rules: " + "; ".join(core_rules))
    if never_do:
        parts.append("Never: " + "; ".join(never_do))

    context = "\n".join(parts)
    return context, char_name


def main():
    print("=" * 50)
    print("  GENERADOR DE PERSONAJES")
    print("=" * 50)

    name = _non_empty_input("\nNombre interno (ej. 'luna'): ").lower()

    modo = input("\n¿Cómo generar?\n"
                 "  1. Todo con IA (solo una descripción)\n"
                 "  2. Responder preguntas (más control)\n"
                 "> ").strip()

    if modo == "2":
        context, char_name = collect_context()

        print("\n" + "=" * 50)
        print(f"RESUMEN: {char_name}")
        print("=" * 50)
        print(context)
        print("=" * 50)
        if input("\n¿Generar personaje? (s/n): ").strip().lower() not in ('s', 'y', 'si'):
            print("Cancelado.")
            return

        prompt = (
            "You are a character designer. Create a complete character profile in JSON "
            "based on this info. Respond ONLY with raw JSON:\n\n"
            f"{context}\n\n"
            "{\n"
            '  "identity": {"name": "...", "role": "...", "age": "...", "background": "...", "scenario": "..."},\n'
            '  "personality": {"traits": [...], "motivations": [...], "flaws": [...], "inner_conflict": "...", "emotional_triggers": [...]},\n'
            '  "speech": {"style": "...", "verbosity": "...", "tone": "...", "speech_patterns": [...], "examples": [...]},\n'
            '  "rules": {"core_rules": [...], "never_do": [...], "response_style": [...], "roleplay_mode": true},\n'
            '  "memories": ["..."]\n'
            "}"
        )
    else:
        prompt = input("\nDescribí tu personaje en detalle:\n> ").strip()
        if not prompt:
            print("El prompt no puede estar vacío.")
            return

    print("\nInicializando modelo...")
    llm = VToolLlama(auto_load=True)

    print(f"\nGenerando personaje '{name}'...")

    # Si el personaje ya existe, preguntar
    if name in [c["name"] if isinstance(c, dict) else c for c in llm.list_characters()]:
        if input(f"\n'{name}' ya existe. ¿Sobrescribir? (s/N): ").strip().lower() != 's':
            print("Cancelado.")
            return

    llm.generate_character_with_ai(name=name, prompt=prompt)
    print(f"  Personaje '{name}' creado en characters/{name}/")

    # Mostrar el DNA generado
    dna = llm.get_character_dna(name)
    print("\n--- DNA GENERADO ---")
    print(f"  Identidad: {dna['identity'].get('role', 'sin rol')}")
    print(f"  Personalidad: {', '.join(dna['personality'].get('traits', []))}")
    print(f"  Estilo: {dna['speech'].get('style', 'sin definir')}")

    if input(f"\n¿Iniciar chat con {name}? (s/n): ").strip().lower() in ('s', 'y'):
        llm.load_character(name)
        print(f"\n--- {name} ---")
        print("Comandos: /help /rebuild /autosave N /clean")
        while True:
            try:
                user_input = input(f"\nTú: ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ["salir", "exit", "quit"]:
                    break
                print(f"{name}: ", end="", flush=True)
                for chunk in llm.stream_chat(user_input):
                    print(chunk, end="", flush=True)
                print()
            except KeyboardInterrupt:
                print("\n\nSaliendo...")
                break


if __name__ == "__main__":
    main()
