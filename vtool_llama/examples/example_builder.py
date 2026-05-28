import sys
import os

# Asegurarse de que se pueda importar vtool_llama desde el directorio padre
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from vtool_llama import VToolLlama

def main():
    print("==========================================")
    print("   CREADOR DE PERSONAJES (Character OS)   ")
    print("==========================================")
    
    name = input("\nNombre interno de la carpeta del personaje (ej. 'vendedor', 'mago'): ").strip().lower()
    if not name:
        print("El nombre no puede estar vacío.")
        return
        
    print("\n--- 1. IDENTIDAD ---")
    char_name = input("Nombre público del personaje: ").strip()
    role = input("Rol (ej. 'Mago Errante', 'Asistente de Ventas'): ").strip()
    age = input("Edad: ").strip()
    background = input("Historia de fondo / Background: ").strip()
    scenario = input("Mundo / Escenario actual (opcional): ").strip()
    
    identity_data = {
        "name": char_name,
        "role": role,
        "age": age or "Desconocida",
        "background": background,
        "scenario": scenario
    }
    
    print("\n--- 2. PERSONALIDAD ---")
    traits_input = input("Rasgos de personalidad (separados por coma, ej. 'Alegre, sarcástico, inteligente'): ").strip()
    traits = [t.strip() for t in traits_input.split(",")] if traits_input else []
    
    motivations_input = input("Motivaciones (separadas por coma): ").strip()
    motivations = [m.strip() for m in motivations_input.split(",")] if motivations_input else []
    
    flaws_input = input("Defectos o miedos (separados por coma): ").strip()
    flaws = [f.strip() for f in flaws_input.split(",")] if flaws_input else []
    
    personality_data = {
        "traits": traits,
        "motivations": motivations,
        "flaws": flaws
    }
    
    print("\n--- 3. ESTILO DE HABLA ---")
    style = input("Estilo general (ej. 'Formal', 'Casual', 'Poético'): ").strip()
    tone = input("Tono (ej. 'Amable', 'Condescendiente'): ").strip()
    verbosity = input("Verbosidad (ej. 'Bajo', 'Medio', 'Alto'): ").strip()
    
    print("\nEjemplos de diálogo (Few-shot). Escribe pares de mensajes.")
    print("Presiona Enter en blanco para terminar los ejemplos.")
    examples = []
    while True:
        u_msg = input("User: ").strip()
        if not u_msg: break
        c_msg = input("Char: ").strip()
        examples.append(f"{{{{user}}}}: {u_msg}\n{{{{char}}}}: {c_msg}")
    
    speech_data = {
        "style": style,
        "tone": tone,
        "verbosity": verbosity,
        "examples": examples
    }
    
    print("\n--- 4. REGLAS CORE ---")
    core_rules = []
    print("Escribe las reglas principales (presiona Enter en blanco para terminar):")
    while True:
        rule = input("- ").strip()
        if not rule:
            break
        core_rules.append(rule)
        
    never_do = []
    print("\nEscribe lo que NUNCA debe hacer (presiona Enter en blanco para terminar):")
    while True:
        rule = input("- ").strip()
        if not rule:
            break
        never_do.append(rule)
        
    response_style = []
    print("\nEstilo de Respuesta (ej. 'Usa asteriscos para acciones') (presiona Enter en blanco para terminar):")
    while True:
        style_rule = input("- ").strip()
        if not style_rule:
            break
        response_style.append(style_rule)
        
    rp_mode = input("\n¿Activar 'Roleplay Mode' (forzar acciones con asteriscos si no hay herramientas)? (s/n): ").strip().lower() == 's'
        
    rules_data = {
        "core_rules": core_rules,
        "never_do": never_do,
        "response_style": response_style,
        "roleplay_mode": rp_mode
    }
    
    print("\n--- 5. MEMORIA INICIAL (Opcional) ---")
    memories = []
    print("Agrega memorias iniciales sobre el usuario o el mundo (presiona Enter en blanco para terminar):")
    while True:
        mem = input("- ").strip()
        if not mem:
            break
        memories.append(mem)
        
    print("\nGenerando personaje...")
    try:
        # Instanciamos sin cargar un personaje automáticamente
        llm = VToolLlama(auto_load=False)
        
        llm.create_character(
            name=name,
            identity_data=identity_data,
            personality_data=personality_data,
            speech_data=speech_data,
            rules_data=rules_data,
            initial_memories=memories
        )
        print(f"\n¡Éxito! El personaje '{char_name}' ha sido creado en la carpeta 'personajes/{name}'.")
        print(f"Para interactuar con él, usa: llm.load_character('{name}')")
        
    except Exception as e:
        print(f"\nError al crear el personaje: {e}")

if __name__ == "__main__":
    main()
