import sys
import os

# Asegurarse de que se pueda importar vtool_llama desde el directorio padre (root del repo)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from vtool_llama import VToolLlama

def main():
    print("Iniciando el Character OS...")
    # Usamos "with" para que al salir (por exit o Ctrl+C) se guarde automáticamente el episodio
    with VToolLlama(auto_load=True) as llm:
        # Cargamos el personaje de rol: Elara
        try:
            llm.load_character("luna")
            print("\n--- ¡Elara, la Maga Errante, ha entrado en la sesión! ---")
            
            # Mostrar resumen del episodio anterior si existe
            current_ep = llm.state_manager.current_episode
            if current_ep:
                print(f"\n[Último Episodio #{current_ep.episode_id}] {current_ep.summary}")

            print("\nTip: Usa /rel <trust> <familiarity> para alterar la relación (ej: /rel 0.9 0.8)")
            print("Tip: Usa /mood <layer> <value> para forzar un estado temporal (ej: /mood speech asustado)")
            print("Escribe 'salir' para terminar.\n")
        except ValueError as e:
            print(f"Error cargando personaje: {e}")
            sys.exit(1)

        while True:
            try:
                prompt = input("\nTú: ")
                if prompt.strip().lower() in ["salir", "exit", "quit"]:
                    print("\nGuardando episodio y cerrando sesión...")
                    break
                    
                if not prompt.strip():
                    continue

                print("\nElara:", end=" ", flush=True)
                for chunk in llm.stream_chat(prompt):
                    if isinstance(chunk, str):
                        print(chunk, end="", flush=True)
                print() # Salto de línea final

            except KeyboardInterrupt:
                print("\nGuardando episodio y cerrando sesión...")
                break
            except Exception as e:
                print(f"\nError: {e}")

if __name__ == "__main__":
    main()
