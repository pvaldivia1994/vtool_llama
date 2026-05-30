"""
Tests para bugs de arquitectura y consistencia identificados en la auditoría general.
"""

from __future__ import annotations

import os
import tempfile
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from vtool_llama.db import ChatStore
from vtool_llama.db.io import write_json
from vtool_llama.engine.chat_memory import ChatMemory
from vtool_llama.character.base import CharacterManager
from vtool_llama.compiler import CharacterCompiler
from vtool_llama.types import Message, RulesDNA, EpisodeSnapshot


class TestAuditFixes:

    def test_dna_layers_never_do_template_resolves(self):
        """Verifica que _resolve_never_do en CharacterCompiler intente usar templates primero."""
        manager = MagicMock(spec=CharacterManager)
        manager.is_loaded = True
        manager.rules = RulesDNA(never_do=["say bad words"])

        compiler = CharacterCompiler(manager)

        # Mock de _render_template
        with patch("vtool_llama.compiler.dna_layers._render_template") as mock_render:
            mock_render.return_value = "[RENDERED NEVER DO TEMPLATE]"
            res = compiler._resolve_never_do()
            assert res == "[RENDERED NEVER DO TEMPLATE]"
            mock_render.assert_called_once()

    def test_add_tool_message_persists_in_sqlite(self):
        """Verifica que ChatMemory.add_tool_message persista el mensaje en SQLite."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_chat.db")
            store = ChatStore(db_path)
            
            # Inicializar conversación
            conv = store.get_or_create_conversation("test_char")
            
            token_counter = MagicMock()
            token_counter.count_text.return_value = 5
            
            context_builder = MagicMock()
            
            memory = ChatMemory(history_limit=10)
            memory.bind_store(
                store=store,
                context_builder=context_builder,
                token_counter=token_counter,
                conversation_id=conv.id,
                branch_id=conv.active_branch_id,
                leaf_message_id=conv.active_leaf_message_id,
            )
            
            # Agregar mensaje de usuario y de herramienta
            memory.add_user_message("hello")
            msg_id = memory.add_tool_message(content="Result data", tool_call_id="call_abc")
            
            assert msg_id is not None
            
            # Leer desde SQLite
            messages = store.get_active_branch_messages(
                conversation_id=conv.id,
                branch_id=conv.active_branch_id,
                leaf_id=msg_id,
                limit=10
            )
            
            # Debería haber 2 mensajes (user y tool)
            assert len(messages) == 2
            assert messages[1].role == "tool"
            assert messages[1].content == "Result data"
            assert messages[1].tool_call_id == "call_abc"
            
            store.close()

    def test_load_episode_fallback_no_chat_chroma(self):
        """Verifica que load_episode no falle si _chat_chroma no está presente en CharacterManager."""
        with tempfile.TemporaryDirectory() as tmp:
            manager = CharacterManager(base_dir=tmp)
            char_name = "test_char"
            char_dir = Path(tmp) / char_name
            os.makedirs(char_dir / "_memory" / "episodes", exist_ok=True)
            
            episode_data = {
                "episode_id": 1,
                "timestamp": "2026-05-30T12:00:00Z",
                "summary": "Short episode summary",
                "messages": [{"role": "user", "content": "hi"}]
            }
            episode_path = char_dir / "_memory" / "episodes" / "episode_001.json"
            with open(episode_path, "w", encoding="utf-8") as f:
                json.dump(episode_data, f)
            
            manager._char_dir = char_dir
            
            # Al no tener el atributo _chat_chroma, no debería levantar AttributeError
            # dado el hasattr check que agregamos.
            manager.load_episode(1)
            
            assert manager.current_episode is not None
            assert manager.current_episode.episode_id == 1
            assert manager.current_episode.summary == "Short episode summary"

    def test_write_json_ensures_parent_directory_exists(self):
        """Verifica que write_json y CharacterManager._write_json creen directorios automáticamente."""
        with tempfile.TemporaryDirectory() as tmp:
            # 1. Probar write_json de db.io
            nested_dir = Path(tmp) / "nested" / "deeply" / "db_io.json"
            assert not nested_dir.parent.exists()
            
            write_json(nested_dir, {"hello": "world"}, atomic=True)
            assert nested_dir.exists()
            assert nested_dir.parent.exists()
            
            with open(nested_dir, "r", encoding="utf-8") as f:
                assert json.load(f) == {"hello": "world"}

            # 2. Probar CharacterManager._write_json
            manager = CharacterManager(base_dir=tmp)
            nested_manager_dir = Path(tmp) / "manager_nested" / "char.json"
            assert not nested_manager_dir.parent.exists()
            
            manager._write_json(nested_manager_dir, {"foo": "bar"})
            assert nested_manager_dir.exists()
            assert nested_manager_dir.parent.exists()
            
            with open(nested_manager_dir, "r", encoding="utf-8") as f:
                assert json.load(f) == {"foo": "bar"}
