"""
Ejemplo de razonamiento (Thinking) y herramientas (Tool Calling) en vtool_llama.

Este script ilustra:
1. Cómo procesar y mostrar en streaming el pensamiento interno de modelos como DeepSeek-R1.
2. Cómo definir herramientas, enviárselas al modelo, recibir una llamada a función
   y registrar el resultado para que el modelo complete la respuesta.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Añadir el directorio padre al path para importar vtool_llama en desarrollo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vtool_llama import VToolLlama

# -----------------------------------------------------------------------------
# 1. Definición de herramientas locales ficticias
# -----------------------------------------------------------------------------
def get_current_weather(location: str, unit: str = "celsius") -> str:
    """Obtiene el clima actual de una ubicación específica."""
    print(f"\n[SISTEMA] Ejecutando función local 'get_current_weather' para: {location}...")
    # Respuesta ficticia
    if "tokio" in location.lower():
        return json.dumps({"location": "Tokio", "temperature": "18", "unit": unit, "condition": "Lluvia ligera"})
    elif "madrid" in location.lower():
        return json.dumps({"location": "Madrid", "temperature": "25", "unit": unit, "condition": "Soleado"})
    else:
        return json.dumps({"location": location, "temperature": "22", "unit": unit, "condition": "Parcialmente nublado"})

# Esquema de herramientas en formato estándar OpenAI
TOOLS_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "Obtiene el clima actual de una ciudad o ubicación.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "El nombre de la ciudad o ubicación, por ejemplo: Madrid, Tokio, París."
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "Unidad de temperatura (por defecto celsius)."
                    }
                },
                "required": ["location"]
            }
        }
    }
]

# Diccionario de funciones disponibles para llamar por nombre
FUNCTIONS_MAP = {
    "get_current_weather": get_current_weather
}


def run_thinking_demo(llm: VToolLlama):
    """Demuestra cómo capturar y separar en streaming el pensamiento de DeepSeek-R1."""
    print("\n" + "=" * 60)
    print(" 1. Demostración de Razonamiento (Thinking/Thinking Mode)")
    print("=" * 60)
    
    prompt = "¿Por qué el cielo es azul? Responde de forma muy resumida en 2 frases."
    print(f"\nPregunta: {prompt}\n")
    
    current_mode = None
    
    # stream_chat_with_thinking yields (tipo, token)
    for tipo, token in llm.stream_chat_with_thinking(prompt):
        if tipo != current_mode:
            current_mode = tipo
            if tipo == "thinking":
                print("\n\033[90m[Pensamiento del Modelo...] ", end="", flush=True)
            elif tipo == "content":
                print("\033[0m\n\n\033[32m[Respuesta Final] ", end="", flush=True)
        
        print(token, end="", flush=True)
    
    print("\033[0m\n")


def run_tools_demo(llm: VToolLlama):
    """Demuestra la llamada a funciones locales usando Tool Calling."""
    print("\n" + "=" * 60)
    print(" 2. Demostración de Llamada a Herramientas (Tool Calling)")
    print("=" * 60)
    
    # Limpiamos chat previo
    llm.reset_chat()
    
    prompt = "¿Cómo está el clima en Tokio justo ahora?"
    print(f"\nPregunta: {prompt}\n")
    
    # 1. Enviar el prompt junto con las definiciones de herramientas
    print("[INFO] Enviando prompt y herramientas al modelo...")
    result = llm.chat(prompt, tools=TOOLS_DEFINITION)
    
    # 2. Comprobar si el modelo decidió llamar a una herramienta
    if isinstance(result, dict) and "tool_calls" in result:
        tool_calls = result["tool_calls"]
        print(f"\nEl modelo ha solicitado llamar a {len(tool_calls)} herramienta(s):")
        
        for tool_call in tool_calls:
            function_name = tool_call["function"]["name"]
            arguments_str = tool_call["function"]["arguments"]
            call_id = tool_call["id"]
            
            print(f"  - Herramienta: {function_name}")
            print(f"  - Argumentos: {arguments_str}")
            print(f"  - ID: {call_id}")
            
            # Ejecutar la función local mapeada
            if function_name in FUNCTIONS_MAP:
                args = json.loads(arguments_str)
                func = FUNCTIONS_MAP[function_name]
                
                # Ejecución de la función
                output = func(**args)
                print(f"  - Retorno de la función: {output}")
                
                # 3. Registrar la respuesta de la herramienta en el historial de memoria
                llm.add_tool_message(content=output, tool_call_id=call_id)
            else:
                print(f"  - Error: La función '{function_name}' no está registrada.")
        
        # 4. Volver a llamar al chat (con el historial actualizado de herramienta)
        # para que el modelo redacte la respuesta final basándose en el resultado
        print("\n[INFO] Enviando la respuesta de la herramienta de regreso al modelo...")
        respuesta_final = llm.chat("Por favor redacta la respuesta final basándote en la información obtenida.")
        print(f"\n\033[32m[Respuesta Final] {respuesta_final}\033[0m\n")
        
    else:
        # El modelo respondió directamente sin usar herramientas
        print(f"\n\033[32m[Respuesta Directa] {result}\033[0m\n")


def main():
    llm = VToolLlama(auto_load=False)
    
    # Configurar debug si se desea monitorear la comunicación
    llm.enable_debug()
    
    try:
        llm.load_model()
    except Exception as e:
        print(f"Error al cargar el modelo por defecto: {e}")
        disponibles = llm.list_available_models()
        if disponibles:
            print("\nModelos disponibles:")
            for idx, m in enumerate(disponibles, 1):
                print(f"  [{idx}] {m['filename']} ({m['size_gb']} GB)")
            sel = input("Selecciona un número: ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(disponibles):
                try:
                    llm.load_model(disponibles[int(sel)-1]["path"])
                except Exception as e2:
                    print(f"No se pudo cargar: {e2}")
                    return
            else:
                return
        else:
            print("No hay modelos GGUF disponibles. Asegúrate de configurar 'models_directory' en config.json.")
            return

    # Ejecutar demostraciones
    run_thinking_demo(llm)
    run_tools_demo(llm)
    
    # Descargar modelo
    llm.unload_model()


if __name__ == "__main__":
    main()
