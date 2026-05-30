"""
Tests para memoria semántica (ChromaDB) y estrategias de recuperación.
"""

from __future__ import annotations

import os
import tempfile
import json
import pytest
from unittest.mock import MagicMock, patch

from vtool_llama import VToolLlama
from vtool_llama.db import ChatStore
from vtool_llama.engine.retrieval import SemanticRetrievalStrategy


def _make_test_character_dir(tmp, name="test_char"):
    char_dir = os.path.join(tmp, "characters", name)
    os.makedirs(os.path.join(char_dir, "dna"), exist_ok=True)
    with open(os.path.join(char_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": name,
            "system_prompt": "Eres un robot asistente.",
            "semantic_memory_enabled": True,
            "n_ctx": 512,
            "context_reserve_tokens": 50,
        }, f)
    return char_dir


class TestSemanticMemory:

    def test_semantic_strategy_registration(self):
        """Verifica que SemanticRetrievalStrategy y SceneContextStrategy se registren en el ContextBuilder."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "debug": False, "n_ctx": 512, "n_batch": 1,
                    "gpu_layers": 0, "temperature": 0.7, "top_p": 0.9,
                    "top_k": 40, "repeat_penalty": 1.1, "max_tokens": 100,
                    "system_prompt": "test", "enable_logging": False,
                    "history_limit": 50, "auto_trim_context": True,
                    "context_reserve_tokens": 50,
                    "characters_directory": os.path.join(tmp, "characters"),
                    "models_directory": tmp, "default_model": "none.gguf",
                }, f)

            _make_test_character_dir(tmp, "test_char")

            llm = VToolLlama(config_path=config_path, auto_load=False)
            
            mock_model = MagicMock()
            mock_model.tokenize.return_value = [0] * 5
            mock_model.save_state.return_value = {"mock": "state"}
            mock_model.load_state.return_value = None
            llm._model_manager._model = mock_model
            llm._model_manager._tokenize_fn = mock_model.tokenize

            with patch('vtool_llama.db.chroma_store.ChromaStore') as mock_chroma_class:
                mock_chroma_instance = MagicMock()
                mock_chroma_instance.is_available = True
                mock_chroma_class.return_value = mock_chroma_instance

                llm.load_character("test_char", semantic_memory=True)

                assert llm._semantic_chroma is not None
                assert llm._semantic_chroma.is_available

            strategies = llm._context_builder._strategies
            strategy_types = [type(s) for s in strategies]
            
            from vtool_llama.orquestador import ContextInjectionStrategy, SceneContextStrategy
            from vtool_llama.engine.retrieval import RecentMessagesStrategy, SemanticRetrievalStrategy

            assert ContextInjectionStrategy in strategy_types
            assert SceneContextStrategy in strategy_types
            assert SemanticRetrievalStrategy in strategy_types
            assert RecentMessagesStrategy in strategy_types

            # Verificar prioridades
            priorities = [s.priority for s in strategies]
            assert priorities == sorted(priorities)

            llm.chat_store.close()

    def test_semantic_similarity_filtering(self):
        """Verifica que SemanticRetrievalStrategy filtre documentos con baja similaridad."""
        mock_chroma = MagicMock()
        mock_chroma.is_available = True
        
        mock_chroma.search.return_value = [
            {"document": "Este es un documento muy relevante", "similarity": 0.8},
            {"document": "Este documento es irrelevante", "similarity": 0.1},
        ]

        strategy = SemanticRetrievalStrategy(chroma_store=mock_chroma, min_similarity=0.3)
        
        mock_store = MagicMock()
        mock_store.get_active_branch_messages.return_value = [
            MagicMock(content="Hola mundo")
        ]
        
        mock_counter = MagicMock()
        mock_counter.count_text.side_effect = lambda t: len(t) // 4

        section = strategy.retrieve(
            store=mock_store,
            token_counter=mock_counter,
            conversation_id="conv_1",
            branch_id="main",
            leaf_message_id=1,
            budget=100
        )

        assert section.messages
        content = section.messages[0]["content"]
        assert "muy relevante" in content
        assert "irrelevante" not in content

    def test_auto_indexing_trigger(self):
        """Verifica que el auto-indexado se gatille tras 10 mensajes nuevos o si está sucio."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "debug": False, "n_ctx": 512, "n_batch": 1,
                    "gpu_layers": 0, "temperature": 0.7, "top_p": 0.9,
                    "top_k": 40, "repeat_penalty": 1.1, "max_tokens": 100,
                    "system_prompt": "test", "enable_logging": False,
                    "history_limit": 50, "auto_trim_context": True,
                    "context_reserve_tokens": 50,
                    "characters_directory": os.path.join(tmp, "characters"),
                    "models_directory": tmp, "default_model": "none.gguf",
                }, f)

            _make_test_character_dir(tmp, "test_char")

            llm = VToolLlama(config_path=config_path, auto_load=False)
            
            mock_model = MagicMock()
            mock_model.tokenize.side_effect = lambda text, *a, **kw: [0] * max(1, len(text) // 4)
            mock_model.save_state.return_value = {"mock": "state"}
            mock_model.load_state.return_value = None
            llm._model_manager._model = mock_model
            llm._model_manager._tokenize_fn = mock_model.tokenize

            with patch('vtool_llama.db.chroma_store.ChromaStore') as mock_chroma_class:
                mock_chroma_instance = MagicMock()
                mock_chroma_instance.is_available = True
                mock_chroma_class.return_value = mock_chroma_instance

                llm.load_character("test_char", semantic_memory=True)

            llm.index_conversation = MagicMock(return_value=0)

            # Inicializar con dirty=0
            llm.chat_store.get_semantic_sync(llm._memory._conversation_id)
            llm.chat_store.update_semantic_sync(
                llm._memory._conversation_id,
                last_message_id=0,
                branch_id="main"
            )
            with llm.chat_store._tx() as conn:
                conn.execute("UPDATE semantic_sync SET dirty = 0 WHERE conversation_id = ?", (llm._memory._conversation_id,))

            # Agregar 5 mensajes
            for i in range(5):
                llm._memory.add_user_message(f"Msg {i}")
            
            llm._auto_index_if_needed()
            llm.index_conversation.assert_not_called()

            # Agregar 5 mensajes más (total 10 nuevos)
            for i in range(5, 10):
                llm._memory.add_user_message(f"Msg {i}")

            llm._auto_index_if_needed()
            llm.index_conversation.assert_called_once_with(incremental=True)

            # Si está sucio, rebuild completo incluso con 1 mensaje nuevo
            llm.index_conversation.reset_mock()
            llm.mark_semantic_dirty()
            llm._auto_index_if_needed()
            llm.index_conversation.assert_called_once_with(incremental=False)

            llm.chat_store.close()
