"""
Tests para optimizaciones de contexto y KV Cache.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from vtool_llama.model.manager import ModelManager
from vtool_llama.character.base import CharacterManager
from vtool_llama.compiler import CharacterCompiler
from vtool_llama.engine.base import VToolLlama
from vtool_llama.types import Message, RulesDNA


class TestOptimizations:

    def test_model_manager_count_messages_tokens_fallback(self):
        """Verifica que count_messages_tokens use la suma y el overhead como fallback si el modelo no está cargado."""
        model_mgr = ModelManager(config=MagicMock(), logger_fn=MagicMock(), error_fn=MagicMock())
        model_mgr._model = None
        model_mgr._tokenize_fn = None
        
        messages = [
            {"role": "system", "content": "hello system"},
            {"role": "user", "content": "hello user"}
        ]
        
        # Con tokenize_fn=None, count_tokens usa estimate_tokens (~1 token cada 4 caracteres)
        # hello system: 12 chars -> ~3 tokens
        # hello user: 10 chars -> ~2.5 (3) tokens
        # total estimated text tokens: 3 + 3 = 6
        # overhead: 2 mensajes * 8 = 16
        # total esperado: ~22
        tokens = model_mgr.count_messages_tokens(messages)
        assert tokens > 15
        assert tokens < 30

    def test_model_manager_count_messages_tokens_with_formatter(self):
        """Verifica que count_messages_tokens use el chat formatter cuando el modelo está cargado."""
        model_mgr = ModelManager(config=MagicMock(), logger_fn=MagicMock(), error_fn=MagicMock())
        class DummyModel:
            pass
        mock_model = DummyModel()
        mock_formatter = MagicMock(return_value="<formatted_prompt>")
        mock_model.chat_formatter = mock_formatter
        model_mgr._model = mock_model
        
        messages = [{"role": "user", "content": "hi"}]
        
        with patch.object(model_mgr, "count_tokens", return_value=12) as mock_count:
            tokens = model_mgr.count_messages_tokens(messages)
            assert tokens == 12
            mock_formatter.assert_called_once_with(messages=messages)
            mock_count.assert_called_once_with("<formatted_prompt>")

    def test_generate_resets_model_state_before_completion(self):
        """Evita que el KV cache de una respuesta anterior contamine el turno actual."""
        config = MagicMock()
        config.max_tokens = 128
        config.temperature = 0.7
        config.top_p = 0.9
        config.top_k = 40
        config.repeat_penalty = 1.1

        model_mgr = ModelManager(config=config, logger_fn=MagicMock(), error_fn=MagicMock())
        mock_model = MagicMock()
        mock_model.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }
        model_mgr._model = mock_model

        result = model_mgr.generate([{"role": "user", "content": "Mi nombre es LiuniK"}])

        mock_model.reset.assert_called_once()
        mock_model.create_chat_completion.assert_called_once()
        assert result["choices"][0]["message"]["content"] == "ok"

    def test_compiler_split_static_and_dynamic(self):
        """Verifica que compile_static_prompt y compile_dynamic_prompt dividan las secciones estáticas y dinámicas."""
        manager = MagicMock(spec=CharacterManager)
        manager.is_loaded = True
        
        # Mock de resolutores estáticos
        compiler = CharacterCompiler(manager)
        compiler._resolve_system_core = MagicMock(return_value="STATIC_CORE")
        compiler._resolve_anti_assistant = MagicMock(return_value="STATIC_ANTI")
        compiler._resolve_definitions = MagicMock(return_value="")
        
        # Mock de resolutores dinámicos
        compiler._resolve_state = MagicMock(return_value="DYNAMIC_STATE")
        compiler._resolve_relationship = MagicMock(return_value="DYNAMIC_RELATIONSHIP")
        
        # Mockear los métodos auxiliares para evitar que tiren KeyError de sus DNA
        compiler._resolve_identity = MagicMock(return_value="")
        compiler._resolve_traits = MagicMock(return_value="")
        compiler._resolve_motivations = MagicMock(return_value="")
        compiler._resolve_flaws = MagicMock(return_value="")
        compiler._resolve_inner_conflict = MagicMock(return_value="")
        compiler._resolve_emotional_triggers = MagicMock(return_value="")
        compiler._resolve_speech = MagicMock(return_value="")
        compiler._resolve_speech_patterns = MagicMock(return_value="")
        compiler._resolve_scenario = MagicMock(return_value="")
        compiler._resolve_core_rules = MagicMock(return_value="")
        compiler._resolve_never_do = MagicMock(return_value="")
        compiler._resolve_response_style = MagicMock(return_value="")
        compiler._resolve_roleplay_mode = MagicMock(return_value="")
        compiler._resolve_few_shot_examples = MagicMock(return_value="")
        compiler._resolve_soul = MagicMock(return_value="")
        compiler._resolve_beliefs_contradictions = MagicMock(return_value="")
        
        compiler._resolve_active_mods_description = MagicMock(return_value="")
        compiler._resolve_memory = MagicMock(return_value="")
        compiler._resolve_episode = MagicMock(return_value="")
        compiler._resolve_psychology = MagicMock(return_value="")
        compiler._resolve_persona = MagicMock(return_value="")

        static_prompt = compiler.compile_static_prompt("BASE")
        dynamic_prompt = compiler.compile_dynamic_prompt()

        assert "STATIC_CORE" in static_prompt
        assert "STATIC_ANTI" in static_prompt
        assert "DYNAMIC_STATE" not in static_prompt
        assert "DYNAMIC_RELATIONSHIP" not in static_prompt

        assert "DYNAMIC_STATE" in dynamic_prompt
        assert "DYNAMIC_RELATIONSHIP" in dynamic_prompt
        assert "STATIC_CORE" not in dynamic_prompt

    def test_inject_dynamic_state_into_messages(self):
        """Verifica que _inject_dynamic_state_into_messages inserte el estado dinámico antes del mensaje del usuario."""
        engine = MagicMock(spec=VToolLlama)
        engine._character_manager = MagicMock()
        engine._character_manager.is_loaded = True
        engine._character_manager.build_dynamic_prompt.return_value = "EMOTION: angry\nTRUST: low"

        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "assistant", "content": "hello user"},
            {"role": "user", "content": "how are you?"}
        ]

        # Vincular el método de VToolLlama manualmente
        from vtool_llama.engine.chat import _inject_dynamic_state_into_messages
        res_messages = _inject_dynamic_state_into_messages.__get__(engine)(messages)

        # Debería haber 4 mensajes ahora (se inserta en la posición 2, justo antes de user)
        assert len(res_messages) == 4
        assert res_messages[2]["role"] == "system"
        assert "[ESTADO DINÁMICO DEL PERSONAJE]" in res_messages[2]["content"]
        assert "EMOTION: angry" in res_messages[2]["content"]
        assert res_messages[3]["role"] == "user"
