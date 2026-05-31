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
        manager = MagicMock()
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

    def test_compiler_reports_tokens_by_prompt_layer(self):
        """Mide cada capa para diagnosticar que parte infla el system prompt."""
        manager = MagicMock()
        manager.is_loaded = True
        compiler = CharacterCompiler(manager)

        layer_values = {
            "_resolve_system_core": "CORE",
            "_resolve_definitions": "DEFINITIONS",
            "_resolve_anti_assistant": "ANTI",
            "_resolve_identity": "IDENTITY",
            "_resolve_traits": "TRAITS",
            "_resolve_motivations": "",
            "_resolve_flaws": "",
            "_resolve_inner_conflict": "",
            "_resolve_emotional_triggers": "",
            "_resolve_speech": "SPEECH",
            "_resolve_speech_patterns": "",
            "_resolve_scenario": "SCENARIO",
            "_resolve_core_rules": "RULES",
            "_resolve_never_do": "NEVER",
            "_resolve_response_style": "",
            "_resolve_roleplay_mode": "",
            "_resolve_orquestador_context": "CTX",
            "_resolve_few_shot_examples": "EXAMPLES",
            "_resolve_soul": "SOUL",
            "_resolve_beliefs_contradictions": "",
            "_resolve_relationship": "REL",
            "_resolve_state": "STATE",
            "_resolve_active_mods_description": "",
            "_resolve_memory": "MEMORY",
            "_resolve_psychology": "",
            "_resolve_persona": "",
        }
        for name, value in layer_values.items():
            setattr(compiler, name, MagicMock(return_value=value))

        breakdown = compiler.get_layer_token_breakdown(
            "BASE",
            count_fn=lambda text: len(text),
        )

        layers = {layer["name"]: layer for layer in breakdown["layers"]}
        assert layers["base_system_prompt"]["tokens"] == 4
        assert layers["identity"]["required"] is True
        assert layers["soul"]["movable"] is True
        assert layers["soul"]["compact"] is False
        assert layers["identity"]["compact"] is True
        assert layers["few_shot_examples"]["movable"] is True
        assert layers["state"]["phase"] == "dynamic"
        assert breakdown["static_tokens"] > breakdown["dynamic_tokens"]
        assert breakdown["total_tokens"] == breakdown["static_tokens"] + breakdown["dynamic_tokens"]

    def test_compiler_builds_compact_prompt_without_heavy_layers(self):
        """El prompt compact usa capsula y excluye capas movibles pesadas."""
        manager = MagicMock()
        manager.is_loaded = True
        manager.identity.name = "Luna"
        manager.identity.role = "compañera narrativa"
        manager.identity.background = "Tiene una historia larga." * 20
        manager.identity.scenario = "Un escenario amplio." * 20
        manager.personality_dna.traits = ["curiosa", "cauta"]
        manager.personality_dna.motivations = ["proteger su identidad"]
        manager.personality_dna.flaws = ["desconfia al principio"]
        manager.speech.style = "roleplay"
        manager.speech.tone = "suave"
        manager.speech.verbosity = "media"
        manager.speech.speech_patterns = ["usa acciones entre asteriscos"]
        manager.rules.never_do = ["romper personaje", "hablar como asistente"]
        manager.rules.response_style = ["responder en español"]

        compiler = CharacterCompiler(manager)
        compiler._resolve_definitions = MagicMock(return_value="DEFINITIONS" * 100)
        compiler._resolve_soul = MagicMock(return_value="SOUL" * 100)
        prompt = compiler.compile_compact_prompt("BASE")

        assert "[CHARACTER CAPSULE]" in prompt
        assert "Luna" in prompt
        assert "Always reply in Spanish" in prompt
        assert "DEFINITIONS" not in prompt
        assert "SOUL" not in prompt

    def test_character_manager_uses_compact_prompt_when_enabled(self):
        real_manager = CharacterManager()
        real_manager._character_name = "test"
        real_manager._compiler = MagicMock()
        real_manager._compiler.compile_compact_prompt.return_value = "COMPACT"
        real_manager._compiler.compile_static_prompt.return_value = "FULL"
        config = MagicMock()
        config.compact_system_prompt = True

        assert real_manager.build_system_prompt("BASE", config) == "COMPACT"

    def test_engine_reports_prompt_layer_budget(self):
        """Expone el diagnostico con presupuesto efectivo del contexto."""
        engine = MagicMock(spec=VToolLlama)
        engine._config = MagicMock()
        engine._config.system_prompt = "BASE"
        engine._config.n_ctx = 1000
        engine._config.context_reserve_tokens = 100
        engine._model_manager = MagicMock()
        engine._model_manager.is_loaded = False
        engine._character_manager = MagicMock()
        engine._character_manager.get_prompt_layer_breakdown.return_value = {
            "total_tokens": 350,
            "static_tokens": 300,
            "dynamic_tokens": 50,
            "layers": [],
        }

        result = VToolLlama.get_prompt_layer_usage(engine)

        assert result["effective_context_limit"] == 900
        assert result["conversation_budget_after_static"] == 600
        assert result["static_usage_pct"] == 30.0
        assert result["static_effective_usage_pct"] == 33.3

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
