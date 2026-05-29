import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from vtool_llama import VToolLlama


def _non_empty_input(prompt: str) -> str:
    val = input(prompt).strip()
    while not val:
        val = input("\u26a0 El campo no puede estar vac\u00edo: ").strip()
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
    """Recolecta contexto del personaje con secciones mejoradas."""
    parts: list[str] = []

    print("\n--- 1. IDENTIDAD ---")
    char_name = _non_empty_input("Nombre p\u00fablico del personaje: ")
    role = _non_empty_input("Rol (ej. 'Mago Errante', 'Esclava'): ")
    age = input("Edad: ").strip()
    background = _non_empty_input("Historia de fondo / Background: ")
    scenario = input("Mundo / Escenario actual (opcional): ").strip()

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
    flaws = input("Defectos o miedos (separados por coma): ").strip()
    inner_conflict = input("Conflicto interno (lo que quiere vs lo que teme, opcional): ").strip()

    if traits:
        parts.append(f"Traits: {traits}")
    if motivations:
        parts.append(f"Motivations: {motivations}")
    if flaws:
        parts.append(f"Flaws: {flaws}")
    if inner_conflict:
        parts.append(f"Inner conflict: {inner_conflict}")

    print("\n--- 3. TRIGGERS EMOCIONALES (opcional) ---")
    triggers = input("\u00bfQu\u00e9 les asusta, enfurece o motiva? (ej. 'El l\u00e1tigo \u2192 p\u00e1nico, amabilidad \u2192 desconfianza'): ").strip()
    if triggers:
        parts.append(f"Emotional triggers: {triggers}")

    print("\n--- 4. PATRONES DE HABLA (opcional) ---")
    speech_patterns = input("\u00bfC\u00f3mo hablan? (ej. 'Tartamudea bajo presi\u00f3n, usa diminutivos, evita contacto visual'): ").strip()
    if speech_patterns:
        parts.append(f"Speech patterns: {speech_patterns}")

    print("\n--- 5. ESTILO DE HABLA ---")
    style = input("Estilo (Casual, Formal, Po\u00e9tico, etc.): ").strip()
    tone = input("Tono (Amable, Sarc\u00e1stico, Miedoso, etc.): ").strip()
    verbosity = input("Verbosidad (Bajo / Medio / Alto): ").strip()

    if style:
        parts.append(f"Speech style: {style}")
    if tone:
        parts.append(f"Tone: {tone}")
    if verbosity:
        parts.append(f"Verbosity: {verbosity}")

    print("\n--- 6. REGLAS ---")
    core_rules = _multi_line_input("Reglas principales (Enter en blanco para terminar):")
    never_do = _multi_line_input("Cosas que NUNCA debe hacer (Enter en blanco para terminar):")

    if core_rules:
        parts.append("Rules: " + "; ".join(core_rules))
    if never_do:
        parts.append("Must never do: " + "; ".join(never_do))

    print("\n--- 7. MEMORY ANCHORS (Opcional) ---")
    anchors = _multi_line_input("\u00bfQu\u00e9 debe recordar SIEMPRE? (Enter en blanco para terminar):")
    if anchors:
        parts.append("Memory anchors: " + "; ".join(anchors))

    context = "\n".join(parts)
    return context, char_name


def build_generation_prompt(char_name: str, context: str) -> str:
    """Genera un prompt detallado y estructurado para la IA."""

    prompt = f"""You are a character development expert. Your task is to create a DETAILED and IMMERSIVE system prompt for an AI roleplay character.

CHARACTER INFORMATION:
{context}

OUTPUT REQUIREMENTS:
Generate a comprehensive system prompt that includes these sections (in this exact order):

1. [SYSTEM CORE]
   - Brief description of how the character communicates
   - Core communication principles

2. [IDENTIDAD]
   - Name, age, role, background
   - Current scenario/world context

3. [RASGOS]
   - 3-5 core personality traits (Spanish)
   - Inner conflicts or contradictions

4. [EMOTIONAL TRIGGERS]
   - What scares them \u2192 immediate reaction
   - What angers them \u2192 behavioral change
   - What motivates them \u2192 how they act
   - What confuses them \u2192 hesitation

5. [MOTIVACIONES]
   - Primary goal
   - Secondary motivations
   - Hidden desires

6. [CONFLICTO INTERNO]
   - What they want vs what they fear
   - How this contradiction shows in behavior

7. [ESTILO DE HABLA]
   - Speaking style (formal, casual, archaic, simple, etc.)
   - Tone (fearful, confident, sarcastic, kind, etc.)
   - Verbosity level

8. [PATRONES DE HABLA]
   - Speech patterns (stutters, pauses, diminutives, avoids eye contact, etc.)
   - Specific linguistic markers (accent, vocabulary, catchphrases)

9. [CORE RULES]
   - What the character ALWAYS does
   - How they respond to authority
   - Default behavior under pressure

10. [HARD RULES \u2014 NEVER]
    - 3-5 things they absolutely never do
    - Why they can't do these things

11. [MEMORY ANCHORS]
    - 5-7 critical facts they ALWAYS remember
    - Identity-defining information
    - Non-negotiable beliefs

12. [RE-CENTERING CLAUSE]
    - Instructions to recall identity before each response
    - How to maintain consistency
    - "Antes de responder, recuerda que eres {char_name}: [role]. Tu voz es [tone]. Responde en espa\u00f1ol."

13. [FEW-SHOT EXAMPLES]
    - 2-3 example interactions showing their voice
    - Different emotional contexts (calm, scared, conflicted)
    - Natural Spanish dialogue

QUALITY STANDARDS:
- Everything MUST be in Spanish (except technical section headers)
- Be SPECIFIC: No generic traits like "brave" \u2014 show what they actually do
- Include contradictions: Real characters are complex
- Make speech patterns tangible: Give exact examples
- Memory Anchors must be unforgettable facts about them
- Examples should sound like REAL dialogue, not robotic

Generate the complete system prompt now, ready to paste into an LLM:"""

    return prompt


def show_summary_and_confirm(char_name: str, context: str) -> bool:
    """Muestra resumen antes de generar."""
    print("\n" + "=" * 50)
    print(f"RESUMEN: {char_name}")
    print("=" * 50)
    print(context)
    print("=" * 50)

    confirm = input("\n\u00bfGeneramos el system prompt con esta info? (s/n): ").strip().lower()
    return confirm in ('s', 'y', 'si')


def main():
    print("==========================================")
    print("   GENERADOR DE PERSONAJES (vtool_llama)  ")
    print("==========================================")

    name = _non_empty_input("\nNombre interno de la carpeta (ej. 'luna', 'zara'): ").lower()

    modo = input("\n\u00bfC\u00f3mo quer\u00e9s generar el personaje?\n"
                 "  1. Todo con IA (una descripci\u00f3n)\n"
                 "  2. Responder preguntas (m\u00e1s control)\n"
                 "> ").strip()

    if modo == "2":
        context, char_name = collect_context()

        if not show_summary_and_confirm(char_name, context):
            print("Cancelado.")
            return

        prompt = build_generation_prompt(char_name, context)
    else:
        prompt = input("\nDescrib\u00ed tu personaje en detalle:\n> ").strip()
        if not prompt:
            print("El prompt no puede estar vac\u00edo.")
            return

    print("\nInicializando modelo...")
    try:
        llm = VToolLlama(auto_load=True)
        print(f"\n[Generando system prompt para '{name}'...]")
        llm.generate_character_with_ai(name=name, prompt=prompt)

        print("\n\u2705 \u00a1System prompt generado!")
        print(f"Archivos guardados en characters/{name}/")

        cargar = input(f"\n\u00bfIniciar sesi\u00f3n con {name}? (s/n): ").strip().lower()
        if cargar in ('s', 'y'):
            llm.load_character(name)
            print(f"\n--- {name.capitalize()} se ha unido ---")
            print("Escrib\u00ed 'salir' para terminar.\n")
            while True:
                try:
                    user_input = input(f"\nT\u00fa: ").strip()
                    if not user_input:
                        continue
                    if user_input.lower() in ["salir", "exit", "quit"]:
                        break

                    print(f"\n{name}:", end=" ", flush=True)
                    for chunk in llm.stream_chat(user_input):
                        print(chunk, end="", flush=True)
                    print()
                except KeyboardInterrupt:
                    print("\n\nSaliendo...")
                    break

    except Exception as e:
        print(f"\n\u274c Error: {e}")


if __name__ == "__main__":
    main()
