from vtool_llama import VToolLlama
import sys

def main():
    print("Iniciando test de memoria...")
    llm = VToolLlama(auto_load=True)
    llm.enable_debug()
    llm.load_character("default")
    
    prompt = "Recuerda que soy el creador de este sistema, mi nombre es Juan."
    print(f"\nUser: {prompt}")
    print("Bot: ", end="")
    
    # Probando con stream_chat
    for token in llm.stream_chat(prompt):
        if isinstance(token, str):
            print(token, end="")
            sys.stdout.flush()
    print("\n\nTest finalizado.")

if __name__ == "__main__":
    main()
