import sys
import os

# Asegurarse de que se pueda importar vtool_llama desde el directorio padre
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from vtool_llama import VToolLlama

def main():
    print("==========================================")
    print("   AI CHARACTER GENERATOR (vtool_llama)   ")
    print("==========================================")
    
    name = input("\nNombre interno de la carpeta (ej. 'zara', 'mago'): ").strip().lower()
    if not name:
        print("El nombre no puede estar vacío.")
        return
        
    prompt = input("\nDescribe cómo quieres que sea este personaje detalladamente:\n> ").strip()
    if not prompt:
        print("El prompt no puede estar vacío.")
        return
        
    print("\nInicializando Llama (cargando modelo en memoria)...")
    try:
        # Instanciamos auto_load=True para que cargue los tensores de inferencia
        llm = VToolLlama(auto_load=True)
        
        print(f"\n[🧠] Generando personaje '{name}'... (Esto puede tomar unos segundos)")
        llm.generate_character_with_ai(name=name, prompt=prompt)
        
        print("\n¡Proceso finalizado!")
        print(f"Puedes probar tu nuevo personaje ejecutando el script de consola y cargando '{name}'.")
        
        cargar = input(f"\n¿Deseas iniciar una sesión de chat con {name} ahora mismo? (s/n): ").strip().lower()
        if cargar == 's':
            llm.load_character(name)
            print(f"\n--- ¡{name.capitalize()} se ha unido a la sesión! ---")
            print("Escribe 'salir' para terminar.\n")
            while True:
                try:
                    user_prompt = input("\nTú: ")
                    if user_prompt.strip().lower() in ["salir", "exit", "quit"]:
                        break
                    if not user_prompt.strip():
                        continue

                    print(f"\n{name.capitalize()}:", end=" ", flush=True)
                    for chunk in llm.stream_chat(user_prompt):
                        print(chunk, end="", flush=True)
                    print()
                except KeyboardInterrupt:
                    print("\nSaliendo...")
                    break

    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    main()
