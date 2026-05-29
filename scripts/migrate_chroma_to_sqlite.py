"""
Migración one-shot: CHRomaDB → SQLite para cada personaje.

Lee memory/chat_history/ de ChromaDB, reconstruye el timeline
ordenado por timestamp, e inserta en chat.db (SQLite).

Uso:
    python scripts/migrate_chroma_to_sqlite.py
    python scripts/migrate_chroma_to_sqlite.py --characters/foo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Agregar directorio raíz al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vtool_llama.db import ChatStore, HAS_CHROMA
from vtool_llama.db.chroma_store import ChromaStore


def migrate_character(char_dir: Path) -> int:
    chroma_path = char_dir / "memory" / "chat_history"
    db_path = char_dir / "chat.db"

    if not chroma_path.exists():
        print(f"  [SKIP] No ChromaDB en {chroma_path}")
        return 0

    if db_path.exists():
        override = input(f"  {db_path} ya existe. ¿Sobrescribir? (s/N): ").strip().lower()
        if override != "s":
            print("  [SKIP] SQLite ya existe, omitiendo.")
            return 0

    print(f"  Migrando {char_dir.name}...")

    if not HAS_CHROMA:
        print("  [ERROR] ChromaDB no instalado. No se puede migrar.")
        return 0

    chroma = ChromaStore(
        db_path=chroma_path,
        collection_name="chat_history",
        log_fn=lambda m: print(f"    {m}"),
    )
    if not chroma.initialize():
        print("  [ERROR] No se pudo inicializar ChromaDB.")
        return 0

    all_docs = chroma.get_all_documents()
    if not all_docs:
        print("  Sin documentos en ChromaDB.")
        return 0

    # Ordenar por timestamp
    all_docs.sort(key=lambda d: d.get("metadata", {}).get("timestamp", ""))

    store = ChatStore(str(db_path))
    conv = store.get_or_create_conversation(char_dir.name)

    count = 0
    for doc in all_docs:
        text = doc.get("document", "")
        if not text:
            continue

        # Parsear "Usuario: ...\nPersonaje: ..."
        parts = text.split("\nPersonaje: ", 1)
        user_text = parts[0].replace("Usuario: ", "", 1) if parts else text
        assistant_text = parts[1] if len(parts) > 1 else ""

        if user_text.strip():
            user_id = store.add_message(
                conversation_id=conv.id,
                branch_id="main",
                role="user",
                content=user_text.strip(),
            )
            count += 1

        if assistant_text.strip():
            assistant_id = store.add_message(
                conversation_id=conv.id,
                branch_id="main",
                role="assistant",
                content=assistant_text.strip(),
                parent_id=user_id if user_text.strip() else None,
            )
            count += 1

    if count > 0:
        store.set_active_leaf(conv.id, "main", assistant_id if assistant_text.strip() else user_id)
        print(f"  Migrados {count} mensajes.")
    else:
        print("  Sin mensajes para migrar.")

    chroma.close()
    store.close()
    return count


def main():
    parser = argparse.ArgumentParser(description="Migrar ChromaDB → SQLite")
    parser.add_argument("--characters", type=str, default=None,
                        help="Ruta específica a un personaje o directorio de personajes")
    args = parser.parse_args()

    base = Path(__file__).resolve().parent.parent / "vtool_llama" / "characters"

    if args.characters:
        target = Path(args.characters)
        if target.is_dir() and (target / "dna").exists():
            dirs = [target]
        elif target.is_dir():
            dirs = [d for d in target.iterdir() if d.is_dir() and (d / "dna").exists()]
        else:
            print(f"No se encontró: {target}")
            return
    else:
        dirs = [d for d in base.iterdir() if d.is_dir() and (d / "dna").exists()]

    total = 0
    for d in dirs:
        total += migrate_character(d)

    print(f"\nTotal: {total} mensajes migrados.")


if __name__ == "__main__":
    main()
