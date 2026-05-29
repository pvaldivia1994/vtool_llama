"""
Ejemplo de consola interactiva para vtool_llama.

NO es el núcleo de la librería.

Es SOLO un ejemplo de cómo integrar VToolLlama en una
aplicación de consola. La librería está diseñada para
ser importada desde otros proyectos, no para ejecutarse
como script principal.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Agregar el directorio padre al path para poder importar
# la librería en desarrollo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vtool_llama import VToolLlama


def main():
    """
    Ejemplo interactivo de uso de VToolLlama en consola.
    Muestra tanto chat normal como streaming.
    """

    print("=" * 60)
    print("  vtool_llama — Consola de ejemplo interactiva")
    print("=" * 60)
    print()
    print("Comandos: /exit /clear /stream /think /info /debug /prompt /help")

    # Inicializar la librería
    llm = VToolLlama(auto_load=False)

    print("--- Configuración de Rendimiento ---")
    # 1. Selección de Modo de Rendimiento
    print("Selecciona el modo de rendimiento:")
    print("  [1] Modo Rápido (Recomendado: Flash Attention habilitado, hilos optimizados)")
    print("  [2] Modo Lento / Estándar (Flash Attention deshabilitado, hilos por defecto)")
    modo_sel = input("Opción [1-2, Enter = Rápido]: ").strip()
    
    config = llm.get_config()
    
    if modo_sel == "2":
        config.flash_attn = False
        config.threads = 8
        print("-> Modo Lento / Estándar configurado.\n")
    else:
        config.flash_attn = True
        config.threads = 4  # Ajustar a núcleos físicos típicos
        print("-> Modo Rápido configurado (Flash Attention activo, 4 hilos).\n")

    # 2. Selección de Ventana de Contexto (3 ventanas disponibles)
    print("Selecciona el tamaño de la ventana de contexto:")
    print("  [1] Corta (2048 tokens) — Inferencia más veloz")
    print("  [2] Media (4096 tokens) — Balanceado")
    print("  [3] Larga (8192 tokens) — Mayor memoria histórica")
    context_sel = input("Opción [1-3, Enter = Media]: ").strip()
    
    if context_sel == "1":
        config.n_ctx = 2048
        print("-> Ventana de contexto establecida en 2048 tokens.\n")
    elif context_sel == "3":
        config.n_ctx = 8192
        print("-> Ventana de contexto establecida en 8192 tokens.\n")
    else:
        config.n_ctx = 4096
        print("-> Ventana de contexto establecida en 4096 tokens.\n")

    # 3. Selección de Mostrar Pensamiento (Thinking)
    print("¿Deseas mostrar el razonamiento interno (Thinking) del modelo?")
    print("  [1] Sí (Habilitado por defecto si el modelo lo soporta)")
    print("  [2] No (Ocultar razonamiento y mostrar solo respuesta final)")
    think_sel = input("Opción [1-2, Enter = Sí]: ").strip()
    use_thinking = False if think_sel == "2" else True
    print(f"-> Mostrar razonamiento (Thinking): {'HABILITADO' if use_thinking else 'DESHABILITADO'}.\n")

    # Intentar cargar modelo desde config
    try:
        print("Cargando modelo...")
        print("  Estado: cargando =", llm.model_loading)
        llm.load_model()
        print("  Estado: cargando =", llm.model_loading, "(finalizado)")
    except Exception as e:
        print(f"  No se pudo cargar el modelo automáticamente: {e}")
        # Mostrar modelos disponibles
        disponibles = llm.list_available_models()
        if disponibles:
            print("  Modelos disponibles:")
            for i, m in enumerate(disponibles, 1):
                print(f"    [{i}] {m['filename']} ({m['size_gb']} GB)")
            sel = input("  Selecciona un número o ingresa ruta: ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(disponibles):
                ruta = disponibles[int(sel) - 1]["path"]
            else:
                ruta = sel
        else:
            ruta = input("  Ingresa la ruta al modelo GGUF: ").strip()

        if ruta:
            try:
                print("  Estado: cargando =", llm.model_loading)
                llm.load_model(ruta)
                print("  Estado: cargando =", llm.model_loading, "(finalizado)")
            except Exception as e2:
                print(f"  Error: {e2}")
                return
        else:
            print("  Saliendo...")
            return

    info = llm.get_model_info()
    print(f"  Modelo: {info['model_name']}")
    print(f"  Contexto: {info['context_size']} tokens")
    print(f"  VRAM estimada: {info['estimated_vram']}")
    print()

    # Modo streaming por defecto
    use_stream = True

    # Bucle principal de chat
    while True:
        try:
            user_input = input("\n\033[34mTú:\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSaliendo...")
            break

        if not user_input:
            continue

        # Procesar comandos especiales
        if user_input.startswith("/"):
            command = user_input.lower()

            if command == "/exit":
                print("Saliendo...")
                break

            elif command == "/clear":
                llm.clear_memory()
                print("\033[33m[Historial limpiado]\033[0m")

            elif command == "/stream":
                use_stream = not use_stream
                print(f"\033[33m[Streaming: {'ON' if use_stream else 'OFF'}]\033[0m")

            elif command == "/think":
                use_thinking = not use_thinking
                print(f"\033[33m[Mostrar Pensamiento: {'ON' if use_thinking else 'OFF'}]\033[0m")

            elif command == "/info":
                info = llm.get_model_info()
                print("\033[33m--- INFORMACIÓN DEL MODELO ---")
                print(f"Modelo: {info['model_name']}")
                print(f"Ruta: {info['model_path']}")
                print(f"Contexto: {info['context_size']} tokens")
                print(f"Capas en GPU: {info['gpu_layers']}")
                print(f"Cargado en memoria: {'SÍ' if info['loaded'] else 'NO'}")
                print(f"VRAM Estimada del Modelo: {info['estimated_vram']}")
                print("\n--- INFORMACIÓN DE HARDWARE (GPU) ---")
                print(f"Aceleración CUDA Activa: {'SÍ' if info.get('cuda_available') else 'NO'}")
                print(f"GPU Detectada: {info.get('gpu_name')}")
                print(f"VRAM Total de la Tarjeta: {info.get('vram_total')}")
                print(f"VRAM Usada en el Sistema: {info.get('vram_used')}")
                print(f"VRAM Libre en la Tarjeta: {info.get('vram_free')}")
                
                tools_support = info.get('supports_tools', False)
                if tools_support:
                    print("\n--- CAPACIDADES DEL MODELO ---")
                    print(f"Tool Calling Nativo: \033[32mSÍ\033[0m (usa tools= en chat())")
                else:
                    print("\n--- CAPACIDADES DEL MODELO ---")
                    print(f"Tool Calling Nativo: \033[33mNO\033[0m (usa el fallback {{tool_name{{...}})")

                disponibles = llm.list_available_models()
                if disponibles:
                    print(f"\nModelos disponibles ({len(disponibles)}):")
                    for m in disponibles:
                        print(f"  - {m['filename']} ({m['size_gb']} GB)")
                print("\033[0m")

            elif command == "/debug":
                # Alternar debug (usa enable_debug/disable_debug públicos)
                if llm.get_config().enable_console_debug:
                    llm.disable_debug()
                    print("\033[33m[Debug desactivado]\033[0m")
                else:
                    llm.enable_debug()
                    print("\033[33m[Debug activado]\033[0m")

            elif command.startswith("/prompt"):
                nuevo_prompt = user_input[8:].strip()
                if nuevo_prompt:
                    llm.set_system_prompt(nuevo_prompt)
                    print(f"\033[33m[System prompt actualizado]\033[0m")
                else:
                    print("\033[33mUso: /prompt <nuevo system prompt>\033[0m")

            elif command == "/help":
                print("\033[33m--- COMANDOS DE CONSOLA ---")
                print("  /exit              Salir")
                print("  /clear             Limpiar historial")
                print("  /stream            Alternar modo streaming")
                print("  /think             Alternar mostrar pensamiento")
                print("  /info              Información del modelo")
                print("  /debug             Alternar debug")
                print("  /prompt <texto>    Cambiar system prompt")
                print("  /help              Esta ayuda")
                print()
                print("--- COMANDOS DE PERSONAJE ---")
                print(llm.slash_commands.get_help_text())
                print("\033[0m")

            else:
                print(f"\033[33mComando desconocido: {command}. Usá /help para ver los disponibles.\033[0m")

            continue

        # Enviar mensaje al modelo
        try:
            print(f"\033[32mAsistente:\033[0m ", end="", flush=True)

            if use_stream:
                current_mode = None
                for tipo, token in llm.stream_chat_with_thinking(user_input):
                    if tipo == "thinking" and not use_thinking:
                        continue
                    
                    if tipo != current_mode:
                        current_mode = tipo
                        if tipo == "thinking":
                            print("\n\033[90m[Pensando...] ", end="", flush=True)
                        elif tipo == "content":
                            color_prefix = "\033[0m\n\n\033[32m[Respuesta] " if use_thinking else ""
                            print(color_prefix, end="", flush=True)
                    
                    print(token, end="", flush=True)
                print("\033[0m")
            else:
                thinking, content = llm.chat_with_thinking(user_input)
                if use_thinking and thinking:
                    print(f"\n\033[90m[Pensamiento]\n{thinking}\033[0m\n")
                    print(f"\033[32m[Respuesta]\n\033[0m{content}")
                else:
                    print(content)

        except Exception as e:
            print(f"\n\033[31mError: {e}\033[0m")

    # Descargar modelo al salir
    print("\nDescargando modelo...")
    llm.unload_model()
    print("¡Hasta luego!")


if __name__ == "__main__":
    main()
