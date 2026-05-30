"""
Extractor de chat_template desde archivos GGUF.

Lee un archivo GGUF y extrae el valor completo de la metadata
tokenizer.chat_template, guardándolo en un archivo .jinja.

Uso:
    python extract_gguf_template.py modelo.gguf
    python extract_gguf_template.py modelo.gguf salida.jinja
    python extract_gguf_template.py modelo.gguf --debug
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def extract_template(gguf_path: str, debug: bool = False) -> str | None:
    """
    Lee un archivo GGUF y busca tokenizer.chat_template en su metadata.

    Args:
        gguf_path: ruta al archivo .gguf
        debug: si es True, imprime todas las claves de metadata disponibles

    Returns:
        El contenido del template como string, o None si no se encuentra.

    La librería gguf expone GGUFReader que lee el archivo completo.
    Los metadatos KV están en reader.fields (OrderedDict[str, ReaderField]).
    Cada ReaderField tiene:
      - .name: str (nombre del campo, ej: "tokenizer.chat_template")
      - .types: list[GGUFValueType] (tipo del valor)
      - .parts: list[np.ndarray] (datos crudos)
      - .contents(): método que retorna el valor decodificado
    """
    try:
        import gguf
    except ImportError:
        print("Error: la librería 'gguf' no está instalada.")
        print("  pip install gguf")
        sys.exit(1)

    path = Path(gguf_path)
    if not path.exists():
        print(f"Error: archivo no encontrado: {path}")
        sys.exit(1)
    if not path.is_file():
        print(f"Error: no es un archivo: {path}")
        sys.exit(1)

    try:
        reader = gguf.GGUFReader(str(path))
    except ValueError as e:
        print(f"Error: el archivo no es un GGUF válido: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error al leer el GGUF: {e}")
        sys.exit(1)

    # reader.fields es un OrderedDict con todas las claves KV
    # Cada clave es accesible con get_field(key) o iterando sobre .fields
    all_keys = list(reader.fields.keys())

    if debug:
        print(f"\n--- Metadata disponible ({len(all_keys)} claves) ---")
        for k in all_keys:
            field = reader.get_field(k)
            if field and field.types:
                tipo = field.types[0].name if hasattr(field.types[0], 'name') else str(field.types[0])
                val_repr = str(field.contents())[:80] if field.contents() else "(vacio)"
                print(f"  {k}  [{tipo}]  {val_repr}...")
        print()

    # Buscar en orden de especificidad:
    # 1. tokenizer.chat_template (clave exacta)
    # 2. cualquier clave que contenga "chat_template"
    # 3. cualquier clave que contenga "template"

    candidates: list[str] = []

    for key in all_keys:
        if key == "tokenizer.chat_template":
            candidates.insert(0, key)  # prioridad máxima
        elif "chat_template" in key:
            candidates.append(key)

    if not candidates:
        for key in all_keys:
            if "template" in key and key not in candidates:
                candidates.append(key)

    if not candidates:
        if debug:
            print("No se encontró ninguna clave con 'template' en la metadata.")
        return None

    # Usar el primer candidato (tokenizer.chat_template si existe)
    target_key = candidates[0]
    if debug and len(candidates) > 1:
        print(f"Candidatos encontrados: {candidates}")
        print(f"Usando: {target_key}")

    field = reader.get_field(target_key)
    if field is None:
        return None

    # field.contents() retorna el valor decodificado
    # Para strings, llama a to_string sobre parts[-1]
    template = field.contents()
    if template is None:
        return None

    return str(template)


def save_template(template: str, output_path: str) -> None:
    """Guarda el template en UTF-8 preservando saltos de línea."""
    path = Path(output_path)
    path.write_text(template, encoding="utf-8")
    print(f"Guardado en: {path.resolve()}")
    print(f"Tamaño: {len(template)} caracteres")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrae tokenizer.chat_template de un archivo GGUF",
    )
    parser.add_argument("gguf", type=str, help="Ruta al archivo .gguf")
    parser.add_argument("output", type=str, nargs="?", default=None,
                        help="Archivo de salida .jinja (opcional, por defecto usa el nombre del .gguf)")
    parser.add_argument("--debug", action="store_true",
                        help="Muestra todas las claves de metadata disponibles")

    args = parser.parse_args()

    template = extract_template(args.gguf, debug=args.debug)

    if template is None:
        print("tokenizer.chat_template no encontrado")
        sys.exit(1)

    print("Template encontrado.")

    if args.output:
        output_path = args.output
    else:
        base = Path(args.gguf).stem
        output_path = f"{base}_chat_template.jinja"

    save_template(template, output_path)


if __name__ == "__main__":
    main()
