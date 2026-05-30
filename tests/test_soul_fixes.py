"""
Tests para bugs de arquitectura y consistencia en el subpackage Soul.
"""

from __future__ import annotations

import os
import tempfile
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from vtool_llama import VToolLlama
from vtool_llama.soul import RuntimeSoulAccessor, SoulGenerator


def _make_test_character_dir_for_soul(tmp, name="test_soul_char"):
    char_dir = os.path.join(tmp, "characters", name)
    os.makedirs(os.path.join(char_dir, "dna"), exist_ok=True)
    os.makedirs(os.path.join(char_dir, "memory"), exist_ok=True)
    
    with open(os.path.join(char_dir, "dna", "identity.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "age": "25", "role": "Friend", "background": "Test background"}, f)
        
    with open(os.path.join(char_dir, "dna", "personality.json"), "w", encoding="utf-8") as f:
        json.dump({"traits": ["friendly"], "flaws": ["fear of heights"], "motivations": ["helping others"]}, f)
        
    with open(os.path.join(char_dir, "dna", "speech.json"), "w", encoding="utf-8") as f:
        json.dump({"style": "casual", "quirks": ["talks fast"]}, f)
        
    with open(os.path.join(char_dir, "dna", "rules.json"), "w", encoding="utf-8") as f:
        json.dump({"rules": []}, f)
        
    return char_dir


class TestSoulBugs:

    def test_soul_accessor_retrieve_context_keys(self):
        """Verifica que RuntimeSoulAccessor.retrieve_context use la clave 'document' en lugar de 'description'."""
        with tempfile.TemporaryDirectory() as tmp:
            char_dir = Path(_make_test_character_dir_for_soul(tmp))
            
            # Crear soul.json de mentira
            soul_data = {
                "core_identity": {
                    "summary": "Robot de pruebas",
                    "archetype": "Test",
                },
                "life_philosophy": "Aprender",
                "memory_loss_start_age": 0,
                "life_months": 300,
            }
            with open(char_dir / "soul.json", "w", encoding="utf-8") as f:
                json.dump(soul_data, f)

            cm = MagicMock()
            cm._base_dir = Path(tmp) / "characters"
            
            dummy_gen = MagicMock()
            
            accessor = RuntimeSoulAccessor(char_dir, dummy_gen)
            
            # Mock de ChromaStore
            with patch('vtool_llama.soul.accessor.ChromaStore') as mock_chroma_class:
                mock_chroma = MagicMock()
                mock_chroma.is_available = True
                
                # Simular resultado de ChromaDB.
                # Nota: ChromaStore.search() retorna diccionarios con la clave 'document'
                mock_chroma.search.return_value = [
                    {
                        "id": "event_1",
                        "document": "Estuve colgado en un árbol y casi me caigo.",
                        "metadata": {
                            "importance": 0.8,
                            "emotion": "fear",
                            "age": 10,
                            "month": 120,
                            "emotional_weight": 0.8
                        },
                        "similarity": 0.9
                    }
                ]
                mock_chroma_class.return_value = mock_chroma
                
                initialized = accessor.initialize()
                assert initialized is True
                
                context = accessor.retrieve_context("miedo a las alturas", top_k=1)
                
                # Si el bug está arreglado, el texto debe contener el contenido del evento
                assert "Estuve colgado en un árbol" in context
                assert "[RECUERDOS VIVIDOS" in context

    def test_soul_generation_micro_event_document_call(self):
        """Verifica que generate_soul use add_document y el mismo ID para Chroma y el historial de eventos."""
        with tempfile.TemporaryDirectory() as tmp:
            char_dir = Path(_make_test_character_dir_for_soul(tmp))
            
            # Crear VToolLlama mockeado
            config_path = os.path.join(tmp, "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "debug": False, "n_ctx": 512, "n_batch": 1,
                    "gpu_layers": 0, "temperature": 0.7, "top_p": 0.9,
                    "top_k": 40, "repeat_penalty": 1.1, "max_tokens": 100,
                    "system_prompt": "test", "enable_logging": False,
                    "history_limit": 50, "auto_trim_context": True,
                    "context_reserve_tokens": 50,
                    "characters_directory": str(char_dir.parent),
                    "models_directory": tmp, "default_model": "none.gguf",
                }, f)

            llm = VToolLlama(config_path=config_path, auto_load=False)
            
            # Instanciar SoulGenerator
            generator = SoulGenerator(
                character_manager=llm._character_manager,
                model_manager=None,
                config=llm._config
            )
            
            # Mockear ChromaStore
            with patch('vtool_llama.soul.soul_generator.ChromaStore') as mock_chroma_class:
                mock_chroma = MagicMock()
                mock_chroma.initialize.return_value = True
                mock_chroma_class.return_value = mock_chroma
                
                # Mockear métodos internos que llaman a LLM/Reflection para que sea offline y rápido
                generator._pre_generate_stage_events = MagicMock(return_value=[])
                generator._compress_soul = MagicMock(return_value={})
                generator._roll_random_chaos_event = MagicMock(return_value=None)
                
                # Forzar generación de un micro_event simulando que no hay eventos de etapa
                # Y que se decida gatillar un micro_event
                random_vals = [0.01]
                with patch('random.random', side_effect=lambda: random_vals.pop(0) if random_vals else 0.5):
                    generator._generate_micro_event = MagicMock(return_value={
                        "month": 12,
                        "type": "social",
                        "description": "Fui a caminar al parque.",
                        "importance": 0.2,
                        "emotion": "happy",
                        "people_involved": [],
                        "location": "park"
                    })
                    
                    history_events = []
                    def mock_add_to_history(ev_id, month, micro, impact):
                        history_events.append((ev_id, micro))
                    generator._add_event_to_history = mock_add_to_history
                    
                    # Ejecutar simulación corta (13 meses)
                    generator.generate_soul("test_soul_char", max_age_years=1, force_regenerate=True)
                    
                    # Verificar que add_document se llamó con el ID correcto
                    assert mock_chroma.add_document.called
                    call_args = mock_chroma.add_document.call_args[1]
                    chroma_doc_id = call_args["doc_id"]
                    chroma_document = call_args["document"]
                    
                    assert chroma_document == "Fui a caminar al parque."
                    
                    # Verificar que el ID enviado al historial es el mismo que en Chroma
                    assert len(history_events) == 1
                    history_event_id, history_event_data = history_events[0]
                    assert history_event_id == chroma_doc_id
                    assert history_event_data["description"] == "Fui a caminar al parque."
