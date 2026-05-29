"""character.py — Métodos de personaje, soul y personalidad de VToolLlama."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from .base import VToolLlama
from ..db import ChatStore
from ..tools import TOOL_USAGE_POLICY
from ..utils import TokenCounter
from .context_builder import ContextBuilder
from .retrieval import RecentMessagesStrategy, SemanticRetrievalStrategy


def list_characters(self: VToolLlama) -> list[dict]:
    return self._character_manager.list_characters()

VToolLlama.list_characters = list_characters


def load_character(self: VToolLlama, name: str, semantic_memory: bool = False) -> object:
    self._character_manager.cancel_load()
    result = self._character_manager.load_character(name)

    char_dir = self._character_manager._char_dir
    if char_dir:
        merged = self._config_manager.merge_character_config(char_dir)
        if merged.system_prompt != self._config.system_prompt:
            self._log_debug("CONFIG", f"system_prompt overrideado por '{name}/config.json'")
        self._config = merged

    # Inicializar SQLite event store + ContextBuilder
    if char_dir:
        db_path = char_dir / "memory" / "chat.db"
        self._chat_store = ChatStore(str(db_path))

        tokenize_fn = None
        if self._model_manager.is_loaded:
            tokenize_fn = self._model_manager.count_tokens
        self._token_counter = TokenCounter(tokenize_fn=tokenize_fn)

        self._context_builder = ContextBuilder(
            store=self._chat_store,
            token_counter=self._token_counter,
            strategies=[
                RecentMessagesStrategy(),
            ],
        )

        conv = self._chat_store.get_or_create_conversation(name)

        self._memory.bind_store(
            store=self._chat_store,
            context_builder=self._context_builder,
            token_counter=self._token_counter,
            conversation_id=conv.id,
            branch_id=conv.active_branch_id,
            leaf_message_id=conv.active_leaf_message_id,
        )
    else:
        self._chat_store = None
        self._context_builder = None
        self._token_counter = None

    if char_dir and self._model_manager.is_loaded:
        prompt = self._character_manager.build_system_prompt(self._config.system_prompt, self._config)
        self._warmup_character_cache(prompt)

    self._memory.clear()
    self._inject_personality_into_system_prompt()

    # Inicializar ChromaDB semántico (opcional, por personaje)
    enable_semantic = semantic_memory or self._config.semantic_memory_enabled
    if char_dir and enable_semantic:
        try:
            from ..db.chroma_store import ChromaStore, HAS_CHROMA
            if HAS_CHROMA:
                self._semantic_chroma = ChromaStore(
                    char_dir / "memory" / "semantic",
                    "conversation_chunks",
                    log_fn=lambda m: self._log_debug("SEMANTIC", m),
                )
                self._semantic_chroma.initialize()
            else:
                self._semantic_chroma = None
        except Exception:
            self._semantic_chroma = None
    else:
        self._semantic_chroma = None

    # Reconstruir contexto desde SQLite
    if self._context_builder and self._chat_store:
        token_budget = self._config.n_ctx - self._config.context_reserve_tokens
        self._memory.load_context(token_budget)
        self._log_debug("CHAT", f"Contexto reconstruido desde SQLite (budget={token_budget})")

    if self._character_manager._soul_accessor and self._character_manager._soul_accessor.is_active:
        self._log_info(f"Soul System activo para '{name}'. Personalidad potenciada por vida simulada.")

    return result

VToolLlama.load_character = load_character


def create_character(
    self: VToolLlama,
    name: str,
    identity_data: dict,
    personality_data: dict,
    speech_data: dict,
    rules_data: dict,
    initial_memories: list = None,
) -> None:
    self._character_manager.create_character(
        name=name,
        identity_data=identity_data,
        personality_data=personality_data,
        speech_data=speech_data,
        rules_data=rules_data,
        initial_memories=initial_memories,
    )

VToolLlama.create_character = create_character


def generate_character_with_ai(self: VToolLlama, name: str, prompt: str) -> None:
    if not self._model_manager.is_loaded:
        raise RuntimeError(
            "El modelo debe estar cargado para usar generate_character_with_ai(). "
            "Instancia con auto_load=True o llama a load_model() primero."
        )

    system_prompt = (
        "You are an expert character designer and creative writer. "
        "Your task is to create a rich, detailed character profile based on the user's request.\n"
        "You MUST respond ONLY with valid JSON, no Markdown, no explanations, raw JSON only.\n"
        "Do NOT add extra fields or change existing field names. "
        "Use EXACTLY the key names shown in the structure below.\n\n"
        "The character will be used in a natural conversation + roleplay system. "
        "The system has:\n"
        "- [SYSTEM CORE]: identity foundation (human-like communication)\n"
        "- [INTERACTION MODE]: default behavior + roleplay gate (roleplay only when requested)\n"
        "- [BEHAVIOR PRIORITY]: personality colors answers but doesn't block them\n"
        "- [CONTEXT AWARENESS]: subtle personality for technical topics\n\n"
        "Your JSON creates the character's DNA layer. "
        "Make it psychologically deep: give the character inner conflicts, "
        "contradictions, and a mix of strengths and flaws.\n\n"
        "The JSON MUST have this exact structure (no extra fields):\n"
        "{\n"
        '  "identity": {\n'
        '    "name": "Public name",\n'
        '    "role": "Their role or title",\n'
        '    "age": "Character age",\n'
        '    "background": "Very detailed creative backstory",\n'
        '    "scenario": "Current world or context"\n'
        "  },\n"
        '  "personality": {\n'
        '    "traits": ["trait1", "trait2", "trait3"],\n'
        '    "motivations": ["main motivation", "secondary motivation"],\n'
        '    "flaws": ["character flaw", "main fear"],\n'
        '    "inner_conflict": "what they want vs what they fear — a sentence",\n'
        '    "emotional_triggers": ["loud voices → panic", "kindness → suspicion"]\n'
        "  },\n"
        '  "speech": {\n'
        '    "style": "e.g. Casual, Formal, Sarcastic, Poetic",\n'
        '    "tone": "e.g. Warm, Cold, Playful",\n'
        '    "verbosity": "Low, Medium or High",\n'
        '    "speech_patterns": ["stutters under pressure", "avoids pronouns", "uses diminutives when scared"],\n'
        '    "examples": [\n'
        '      "{{user}}: hello\\n{{char}}: *looks up* What do you want?",\n'
        '      "{{user}}: help me\\n{{char}}: *sighs* I guess there\'s no other way."\n'
        "    ]\n"
        "  },\n"
        '  "rules": {\n'
        '    "core_rules": ["important rule 1", "rule 2"],\n'
        '    "never_do": ["what they must never do"],\n'
        '    "response_style": ["e.g. use asterisks for actions", "e.g. short responses"],\n'
        '    "roleplay_mode": true\n'
        "  },\n"
        '  "memories": ["initial memory 1 about themselves or the user", "memory 2"]\n'
        "}"
    )

    self._log_info(f"Generando personaje '{name}' con IA...")

    result = self._model_manager.generate(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        stream=False,
        max_tokens=1024,
        temperature=0.8,
    )

    response_text = result["choices"][0]["message"].get("content", "")

    try:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx == -1 or end_idx == 0:
            raise ValueError("No se encontró JSON en la respuesta del modelo.")

        clean_json = response_text[start_idx:end_idx]
        data = json.loads(clean_json)

        self.create_character(
            name=name,
            identity_data=data.get("identity", {}),
            personality_data=data.get("personality", {}),
            speech_data=data.get("speech", {}),
            rules_data=data.get("rules", {}),
            initial_memories=data.get("memories", []),
        )

        self._log_info(f"¡Personaje '{name}' autogenerado con éxito!")

    except Exception as e:
        self._log_error(f"Fallo al generar personaje con IA. Respuesta raw: {response_text}")
        raise RuntimeError(f"Error parseando el personaje autogenerado: {e}")

VToolLlama.generate_character_with_ai = generate_character_with_ai


def generate_character_soul(
    self: VToolLlama,
    character_name: str,
    force_regenerate: bool = False,
    seed: Optional[int] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
    country: str = "US",
    birth_year: int = 2000,
    economy: str = "stable",
    family_income: str = "middle_class",
    world_description: str = "",
    start_age_years: int = 0,
    memory_loss_start_age: int = 0,
    interactive_mode: bool = False,
    interactive_callback: Optional[Callable[[int, list[dict]], str]] = None,
    world_type: str = "real",
    use_historical_context: bool = False,
    fictional_lore_reference: str = "",
    max_age_years: Optional[int] = None,
    save_events_history: bool = True,
) -> dict:
    if not self._model_manager.is_loaded:
        raise RuntimeError(
            "El modelo debe estar cargado para generate_character_soul(). "
            "Instancia con auto_load=True o llama a load_model() primero."
        )

    return self._soul_generator.generate_soul(
        character_name=character_name,
        force_regenerate=force_regenerate,
        seed=seed,
        progress_callback=progress_callback,
        stop_flag=stop_flag,
        country=country,
        birth_year=birth_year,
        economy=economy,
        family_income=family_income,
        world_description=world_description,
        start_age_years=start_age_years,
        memory_loss_start_age=memory_loss_start_age,
        interactive_mode=interactive_mode,
        interactive_callback=interactive_callback,
        world_type=world_type,
        use_historical_context=use_historical_context,
        fictional_lore_reference=fictional_lore_reference,
        max_age_years=max_age_years,
        save_events_history=save_events_history,
    )

VToolLlama.generate_character_soul = generate_character_soul


def has_character_soul(self: VToolLlama, character_name: str) -> bool:
    return self._soul_generator.has_soul(character_name)

VToolLlama.has_character_soul = has_character_soul


def get_character_soul(self: VToolLlama, character_name: str) -> Optional[dict]:
    return self._soul_generator.get_soul_data(character_name)

VToolLlama.get_character_soul = get_character_soul


def _warmup_character_cache(self: VToolLlama, prompt: Optional[str] = None) -> None:
    char_dir = self._character_manager._char_dir
    if not char_dir or not self._model_manager.is_loaded:
        return

    base_kv_path = char_dir / "memory" / "base.state"
    base_soul_kv_path = char_dir / "memory" / "base_soul.state"

    soul = getattr(self._character_manager, '_soul_accessor', None)
    soul_active = soul is not None and soul.is_active

    # 1. Base state (DNA) — se genera una vez
    base_prompt = self._character_manager.build_base_system_prompt(self._config.system_prompt, self._config)
    if not base_kv_path.exists():
        self._log_debug("STATE", "Generando KV Cache Base (DNA)...")
        self._model_manager.warmup_system_prompt(base_prompt)
        self._model_manager.save_kv_state(str(base_kv_path))

    # 2. Base Soul state (DNA + Soul) — se genera una vez si hay alma
    if soul_active and not base_soul_kv_path.exists():
        self._log_debug("STATE", "Generando KV Cache Base Soul (DNA + Soul)...")
        base_soul_prompt = self._character_manager.compile_base_soul_prompt(self._config.system_prompt, self._config)
        self._model_manager.warmup_system_prompt(base_soul_prompt)
        self._model_manager.save_kv_state(str(base_soul_kv_path))

    # 3. Cargar el base que corresponda
    if soul_active and base_soul_kv_path.exists():
        self._model_manager.load_kv_state(str(base_soul_kv_path))
    else:
        self._model_manager.load_kv_state(str(base_kv_path))

    # 4. Warmup diferencial con el prompt completo (no se persiste)
    if prompt is None:
        prompt = self._character_manager.build_system_prompt(self._config.system_prompt, self._config)

    self._log_debug("STATE", "Warmup diferencial del prompt completo sobre Base...")
    self._model_manager.warmup_system_prompt(prompt)
    self._character_manager.mark_rebuild_done(prompt)

    # Guardar prompt compilado como YAML (debug)
    if char_dir:
        yaml_path = char_dir / "memory" / "base_prompt.yaml"
        lines = prompt.split('\n')
        yaml_lines = ["prompt: |"]
        for line in lines:
            yaml_lines.append(f"  {line}")
        yaml_path.write_text('\n'.join(yaml_lines) + '\n', encoding='utf-8')

VToolLlama._warmup_character_cache = _warmup_character_cache


def rebuild_personality_state(self: VToolLlama) -> None:
    with self._lock:
        if not self._model_manager.is_loaded:
            self._log_warning("No hay modelo cargado para rebuild_personality_state")
            return

        memories_text = "\n".join(
            f"- {m.content}" for m in self._character_manager.memories
        )
        history_sample = ""
        non_system = [m for m in self._memory.messages if m.role != "system"]
        for m in non_system[-20:]:
            if m.content:
                history_sample += f"{m.role}: {m.content[:100]}\n"

        rebuild_prompt = (
            "Analiza la siguiente información del usuario y genera un resumen "
            "estructurado en formato JSON. NO incluyas explicaciones, SOLO el JSON.\n\n"
            f"Memorias guardadas:\n{memories_text}\n\n"
            f"Últimos mensajes:\n{history_sample}\n\n"
            "Genera un JSON con esta estructura exacta:\n"
            '{\n'
            '  "dynamics": ["observación 1", "observación 2"],\n'
            '  "trust_level": 0.5,\n'
            '  "familiarity": 0.2\n'
            '}'
        )

        try:
            result = self._model_manager.generate(
                messages=[
                    {"role": "system", "content": "Eres un analizador de patrones. Responde SOLO con JSON válido."},
                    {"role": "user", "content": rebuild_prompt},
                ],
                stream=False,
                max_tokens=256,
                temperature=0.3,
            )
            response_text = result["choices"][0]["message"].get("content", "")

            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(response_text[json_start:json_end])

                rel = self._character_manager.relationship_state
                if "dynamics" in parsed:
                    rel.dynamics = parsed["dynamics"]
                if "trust_level" in parsed:
                    rel.trust_level = float(parsed["trust_level"])
                if "familiarity" in parsed:
                    rel.familiarity = float(parsed["familiarity"])

                self._log_debug("STATE", f"Personality state reconstruido: {parsed}")
            else:
                self._log_warning("rebuild_personality_state: no se pudo extraer JSON válido")

        except Exception as e:
            self._log_warning(f"Error en rebuild_personality_state: {e}")

        self._character_manager.save_state()
        self._character_manager._prompt_dirty = True

        self._warmup_character_cache()

VToolLlama.rebuild_personality_state = rebuild_personality_state


def _inject_personality_into_system_prompt(self: VToolLlama) -> None:
    enriched_prompt = self._character_manager.build_system_prompt(
        self._config.system_prompt, self._config
    )

    if self._character_manager.is_loaded:
        enriched_prompt += "\n\n" + TOOL_USAGE_POLICY

    if self._memory.system_prompt != enriched_prompt:
        self._memory.system_prompt = enriched_prompt

VToolLlama._inject_personality_into_system_prompt = _inject_personality_into_system_prompt


def _check_and_rebuild_if_needed(self: VToolLlama) -> None:
    if not self._character_manager.is_loaded or not self._model_manager.is_loaded:
        return
    char_dir = self._character_manager._char_dir
    if not char_dir:
        return
    prompt = self._character_manager.build_system_prompt(self._config.system_prompt)
    if self._character_manager.check_needs_rebuild(prompt):
        self._log_debug("STATE", "Rebuild pendiente — regenerando KV Cache antes del chat...")
        self._warmup_character_cache(prompt)
        self._log_debug("STATE", "KV Cache regenerado.")

VToolLlama._check_and_rebuild_if_needed = _check_and_rebuild_if_needed


def add_memory(
    self: VToolLlama,
    content: str,
    priority: float = 0.5,
    always_include: bool = False,
    tags: Optional[list[str]] = None,
) -> dict:
    entry = self._character_manager.add_memory(
        content=content,
        priority=priority,
        always_include=always_include,
        tags=tags,
    )
    return {"id": entry.id, "content": entry.content}

VToolLlama.add_memory = add_memory


def get_state_info(self: VToolLlama) -> dict:
    state = {'name': self._character_manager.character_name}
    state["needs_rebuild"] = getattr(self._character_manager, '_needs_rebuild', True)

    soul = getattr(self._character_manager, '_soul_accessor', None)
    if soul and soul.is_active:
        state["soul_active"] = True
        state["soul_archetype"] = (
            soul._soul_data.get("core_identity", {}).get("archetype", "")
            if soul._soul_data else ""
        )
    else:
        state["soul_active"] = False

    return state

VToolLlama.get_state_info = get_state_info
