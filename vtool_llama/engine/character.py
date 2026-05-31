"""character.py — Métodos de personaje, soul y personalidad de VToolLlama."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from .base import VToolLlama
from ..db import ChatStore
from ..tools import TOOL_USAGE_POLICY, get_active_internal_tools
from ..utils import TokenCounter
from ..orquestador import ContextInjectionStrategy, SceneContextStrategy
from .context_builder import ContextBuilder
from .retrieval import (
    RecentMessagesStrategy,
    SemanticRetrievalStrategy,
)


def list_characters(self: VToolLlama) -> list[dict]:
    return self._character_manager.list_characters()

VToolLlama.list_characters = list_characters


def load_character(
    self: VToolLlama,
    name: str,
    semantic_memory: bool = False,
    resume_conversation: bool = True,
) -> object:
    if self._loading:
        raise RuntimeError(
            f"Ya hay una carga de personaje en curso ('{self._character_manager.character_name}'). "
            "Esperá a que termine antes de cargar otro."
        )

    self._loading = True
    self._archive_retries = 0
    try:
        self._character_manager.cancel_load()
        result = self._character_manager.load_character(name)

        char_dir = self._character_manager._char_dir
        if char_dir:
            merged = self._config_manager.merge_character_config(char_dir)
            if merged.system_prompt != self._config.system_prompt:
                self._log_debug("CONFIG", f"system_prompt overrideado por '{name}/config.json'")
            self._config = merged
            self._model_manager._config = merged
            self._soul_generator._config = merged
            # El deque maxlen se define en ChatMemory.__init__ con history_limit

        old_store = getattr(self, "_chat_store", None)
        if old_store:
            try:
                old_store.close()
            except Exception:
                pass
        old_chroma = getattr(self, "_semantic_chroma", None)
        if old_chroma:
            try:
                old_chroma.close()
            except Exception:
                pass

        tpl_file = self._config.chat_template_file
        if tpl_file and self._model_manager.is_loaded:
            tpl_path = Path(tpl_file)
            if not tpl_path.is_absolute():
                tpl_path = Path(__file__).parent.parent / "config" / tpl_file
            if tpl_path.exists():
                try:
                    from llama_cpp.llama_chat_format import Jinja2ChatFormatter
                    template_str = tpl_path.read_text(encoding="utf-8")
                    eos = self._model_manager._model.tokenizer.eos_token if hasattr(self._model_manager._model, 'tokenizer') else ""
                    bos = self._model_manager._model.tokenizer.bos_token if hasattr(self._model_manager._model, 'tokenizer') else ""
                    self._model_manager._model.chat_handler = Jinja2ChatFormatter(
                        template=template_str,
                        eos_token=eos,
                        bos_token=bos,
                    )
                    self._log_debug("MODEL", f"Chat template aplicado: {tpl_path}")
                except Exception as e:
                    self._log_warning(f"No se pudo aplicar chat template: {e}")

        # Inicializar SQLite event store + ContextBuilder
        if char_dir:
            db_path = char_dir / "_memory" / "chat.db"
            self._chat_store = ChatStore(str(db_path), log_fn=lambda t, m: self._log_debug(t, m))

            tokenize_fn = None
            if self._model_manager.is_loaded:
                tokenize_fn = self._model_manager.count_tokens
            self._token_counter = TokenCounter(tokenize_fn=tokenize_fn)

            # Inicializar ChromaDB (v12: siempre, no solo si semantic_memory está activo)
            try:
                from ..db.chroma_store import ChromaStore, HAS_CHROMA
                if HAS_CHROMA:
                    # Colección para indexado semántico de conversación
                    self._semantic_chroma = ChromaStore(
                        char_dir / "_memory" / "semantic",
                        "conversation_chunks",
                        log_fn=lambda m: self._log_debug("SEMANTIC", m),
                    )
                    self._semantic_chroma.initialize()

                    # Colección para memoria archivada (v9+)
                    self._archived_chroma = ChromaStore(
                        char_dir / "_memory" / "semantic",
                        "archived_memory",
                        log_fn=lambda m: self._log_debug("ARCHIVE", m),
                    )
                    self._archived_chroma.initialize()
                else:
                    self._semantic_chroma = None
                    self._archived_chroma = None
            except Exception:
                self._semantic_chroma = None
                self._archived_chroma = None

            # Log diagnóstico de ChromaDB
            self._log_debug("CHROMA", f"semantic={'SI' if self._semantic_chroma and self._semantic_chroma.is_available else 'NO'}, "
                            f"archived={'SI' if self._archived_chroma and self._archived_chroma.is_available else 'NO'}")

            # Debug logger por personaje
            from .debug_logger import CharacterDebugLogger
            self._debug_logger = CharacterDebugLogger(char_dir=char_dir, config=self._config)

            # Archivar mensajes rotados del deque en ChromaDB (v12)
            self._memory.set_archive_callback(lambda msgs: self._archive_to_chroma(msgs))

            strategies = [
                ContextInjectionStrategy(),
                SceneContextStrategy(),
            ]
            if self._semantic_chroma and self._semantic_chroma.is_available:
                strategies.append(SemanticRetrievalStrategy(
                    chroma_store=self._semantic_chroma,
                    min_similarity=self._config.memory_rag_min_similarity,
                    rag_budget=self._config.memory_rag_budget,
                ))
            if getattr(self, "_archived_chroma", None) and self._archived_chroma.is_available:
                strategies.append(SemanticRetrievalStrategy(
                    chroma_store=self._archived_chroma,
                    min_similarity=self._config.memory_rag_min_similarity,
                    rag_budget=self._config.memory_rag_budget,
                    priority=25,
                ))
            strategies.append(RecentMessagesStrategy())

            self._context_builder = ContextBuilder(
                store=self._chat_store,
                token_counter=self._token_counter,
                strategies=strategies,
            )

            conv = (
                self._chat_store.get_or_create_conversation(name)
                if resume_conversation
                else self._chat_store.create_conversation(name)
            )

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
            self._semantic_chroma = None

        if char_dir and self._model_manager.is_loaded:
            prompt = self._character_manager.build_system_prompt(self._config.system_prompt, self._config)
            self._warmup_character_cache(prompt)

        self._memory.clear()
        self._inject_personality_into_system_prompt()

        # Reconstruir contexto desde SQLite
        if self._context_builder and self._chat_store:
            token_budget = self._config.n_ctx - self._config.context_reserve_tokens
            self._memory.load_context(token_budget)
            self._log_debug("CHAT", f"Contexto reconstruido desde SQLite (budget={token_budget})")

        if self._character_manager._soul_accessor and self._character_manager._soul_accessor.is_active:
            self._log_info(f"Soul System activo para '{name}'. Personalidad potenciada por vida simulada.")

        self._log_debug("CHAR", f"Personaje '{name}' cargado. Flag _loading=False.")
        return result

    except Exception:
        self._log_debug("CHAR", f"Error en load_character('{name}'), limpiando flag _loading.")
        raise
    finally:
        self._loading = False

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
        "You are an expert character designer. Create a rich character profile "
        "based on the user's request.\n\n"
        "PROCESS:\n"
        "1. First, THINK about the character deeply. Analyze the request, "
        "imagine their psychology, contradictions, fears, and desires.\n"
        "2. Then, output ONLY the final JSON with the structure below.\n\n"
        "RULES:\n"
        "- Use EXACTLY the key names shown. No extra fields.\n"
        "- Make it psychologically deep: inner conflicts, contradictions, "
        "mix of strengths and flaws.\n"
        "- speech.examples must use {{user}} and {{char}} placeholders.\n"
        "- Write examples in the same language as the user's request.\n\n"
        "JSON STRUCTURE:\n"
        "{\n"
        '  "identity": {\n'
        '    "name": "Public name",\n'
        '    "role": "Role or title",\n'
        '    "age": "Age as text",\n'
        '    "background": "Detailed backstory",\n'
        '    "scenario": "Current world or context"\n'
        "  },\n"
        '  "personality": {\n'
        '    "traits": ["3-5 core traits"],\n'
        '    "motivations": ["main", "secondary"],\n'
        '    "flaws": ["flaw or fear"],\n'
        '    "inner_conflict": "want vs fear in one sentence",\n'
        '    "emotional_triggers": ["trigger → reaction"]\n'
        "  },\n"
        '  "speech": {\n'
        '    "style": "Casual, Formal, Sarcastic, Poetic...",\n'
        '    "tone": "Warm, Cold, Playful...",\n'
        '    "verbosity": "Low, Medium or High",\n'
        '    "speech_patterns": ["stutters under pressure", "uses diminutives when scared"],\n'
        '    "examples": [\n'
        '      "{{user}}: hello\\n{{char}}: *action* response",\n'
        '      "{{user}}: help me\\n{{char}}: *sighs* fine."\n'
        "    ]\n"
        "  },\n"
        '  "rules": {\n'
        '    "core_rules": ["important rules"],\n'
        '    "never_do": ["what they never do"],\n'
        '    "response_style": ["use asterisks for actions"],\n'
        '    "roleplay_mode": true\n'
        "  },\n"
        '  "memories": ["initial memory 1", "memory 2"]\n'
        "}"
    )

    self._log_info(f"Generando personaje '{name}' con IA...")

    def _try_extract_json(text: str) -> dict:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No se encontró JSON en la respuesta.")
        return json.loads(text[start:end])

    def _try_generate(messages: list[dict], temp: float) -> tuple[dict, str]:
        result = self._model_manager.generate(
            messages=messages, stream=False,
            max_tokens=3072, temperature=temp,
        )
        msg = result["choices"][0]["message"]
        content_text = msg.get("content", "")

        # Capturar thinking si el modelo lo soporta (DeepSeek-R1, etc.)
        reasoning = msg.get("reasoning_content") or ""
        if reasoning:
            self._log_debug("DNA", f"Thinking: {reasoning[:200]}...")
            # Buscar JSON también en el thinking por si ahí está
            if not content_text.strip():
                content_text = reasoning

        data = _try_extract_json(content_text)
        return data, reasoning

    # Intento 1: temperatura 0.7 (balanceado, permite pensar)
    try:
        data, thinking = _try_generate([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ], 0.7)

        if thinking:
            self._log_info(f"Modelo usó razonamiento interno ({len(thinking)} chars)")

    # Intento 2 (fallback): temperatura 0.3 + pedir solo JSON
    except Exception as e:
        self._log_debug("DNA", f"Primer intento falló ({e}), reintentando con baja temperatura...")
        try:
            data, _ = _try_generate([
                {"role": "system", "content": "Responde SOLO con JSON."},
                {"role": "user", "content": f"{system_prompt}\n\n{prompt}"},
            ], 0.3)
        except Exception as e2:
            self._log_error(f"Fallo generando personaje. Prompt enviado:\n{system_prompt}\n\n{prompt}")
            raise RuntimeError(f"Error tras 2 intentos: {e2}")

    self.create_character(
        name=name,
        identity_data=data.get("identity", {}),
        personality_data=data.get("personality", {}),
        speech_data=data.get("speech", {}),
        rules_data=data.get("rules", {}),
        initial_memories=data.get("memories", []),
    )

    self._log_info(f"Personaje '{name}' generado con éxito.")

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

    base_kv_path = char_dir / "_memory" / "base.state"
    meta_path = char_dir / "_memory" / "base.state.meta.json"

    # 1. Compilar prompt runtime y mantener prompt full para auditoria
    full_prompt = self._character_manager.build_full_system_prompt(self._config.system_prompt, self._config)
    # Solo compilar compact_prompt si está activo (evita trabajo innecesario)
    compact_prompt = (
        self._character_manager.build_compact_system_prompt(self._config.system_prompt, self._config)
        if getattr(self._config, "compact_system_prompt", False)
        else ""
    )
    if prompt is None:
        prompt = self._character_manager.build_system_prompt(self._config.system_prompt, self._config)

    # 2. Guardar prompts como YAML (debug/auditoria)
    #    base_prompt.yaml = el que usa el modelo en runtime
    #    base_prompt_full.yaml = solo si es distinto (evita duplicados)
    #    base_prompt_compact.yaml = siempre (referencia)
    if char_dir:
        def _write_prompt_yaml(path: Path, text: str) -> None:
            lines = text.split('\n')
            yaml_lines = ["prompt: |"]
            for line in lines:
                yaml_lines.append(f"  {line}")
            path.write_text('\n'.join(yaml_lines) + '\n', encoding='utf-8')

        memory_dir = char_dir / "_memory"
        _write_prompt_yaml(memory_dir / "base_prompt.yaml", prompt)
        if full_prompt != prompt:
            _write_prompt_yaml(memory_dir / "base_prompt_full.yaml", full_prompt)
        # base_prompt_compact.yaml ya no se genera (era redundante)

    import hashlib
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    full_prompt_hash = hashlib.sha256(full_prompt.encode("utf-8")).hexdigest()
    compact_prompt_hash = hashlib.sha256(compact_prompt.encode("utf-8")).hexdigest()
    model_path = self._model_manager.model_info.model_path
    template_file = self._config.chat_template_file or ""
    template_hash = ""
    if template_file:
        tpl_path = Path(template_file)
        if not tpl_path.is_absolute():
            tpl_path = Path(__file__).parent.parent / "config" / template_file
        if tpl_path.exists():
            template_hash = hashlib.sha256(tpl_path.read_bytes()).hexdigest()

    expected_meta = {
        "prompt_hash": prompt_hash,
        "full_prompt_hash": full_prompt_hash,
        "compact_prompt_hash": compact_prompt_hash,
        "compact_system_prompt": bool(getattr(self._config, "compact_system_prompt", False)),
        "model_path": model_path,
        "chat_template_file": template_file,
        "chat_template_hash": template_hash,
        "n_ctx": self._config.n_ctx,
        "n_keep": 0,  # se actualiza después del warmup
    }
    current_meta = {}
    if meta_path.exists():
        try:
            current_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            current_meta = {}

    cache_valid = base_kv_path.exists() and all(
        current_meta.get(k) == v for k, v in expected_meta.items()
    )

    # 3. Warmup completo del prompt y guardar como base.state
    if not cache_valid:
        self._log_debug("STATE", "Generando KV Cache Base (prompt completo)...")
        self._model_manager.warmup_system_prompt(prompt)

        # Medir n_keep: el warmup genera 1 token extra, lo restamos
        raw_nt = getattr(self._model_manager._model, "n_tokens", None)
        if isinstance(raw_nt, (int, float)):
            n_keep = max(0, int(raw_nt) - 1)
        else:
            n_keep = 0
        self._model_manager._n_keep = n_keep if n_keep > 0 else None
        expected_meta["n_keep"] = n_keep

        # ── Expansión de n_ctx (v8) ──────────────────────────────────
        # Si expand_n_ctx_for_core está activo y el core aún no se expandió,
        # recargamos el modelo con n_ctx = user_n_ctx + n_keep para que el
        # core viva en posiciones [0..n_keep) y el usuario tenga user_n_ctx libres.
        expand = bool(getattr(self._config, "expand_n_ctx_for_core", False))
        if expand and not self._model_manager._core_expanded and n_keep > 0:
            user_n_ctx = self._model_manager._user_n_ctx
            if user_n_ctx == 0:
                user_n_ctx = self._config.n_ctx
            expanded_ctx = user_n_ctx + n_keep
            self._log_debug("STATE", f"Expandiendo n_ctx a {expanded_ctx} "
                            f"(core {n_keep} + user {user_n_ctx})")
            self._config.n_ctx = expanded_ctx
            self._model_manager.reload_model_with_expanded_ctx(expanded_ctx)
            # Re-ejecutar warmup con el n_ctx expandido y salir
            self._warmup_character_cache(prompt)
            return

        self._model_manager.save_kv_state(str(base_kv_path))
        meta_path.write_text(json.dumps(expected_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        self._model_manager.load_kv_state(str(base_kv_path))
        # Restaurar n_keep desde meta del state guardado
        n_keep = current_meta.get("n_keep", 0)
        self._model_manager._n_keep = n_keep if n_keep > 0 else None

    self._character_manager.mark_rebuild_done(prompt)

    # v11: indexar secciones del personaje en ChromaDB para refuerzo semántico
    self._index_character_core()

VToolLlama._warmup_character_cache = _warmup_character_cache


def _index_character_core(self: VToolLlama) -> None:
    """Indexa secciones clave del personaje en ChromaDB para refuerzo semántico (v11).

    Se ejecuta durante load_character() después del warmup.
    Los documentos usan tags [CHARACTER][*] que el modelo ya conoce.
    """
    archived = getattr(self, "_archived_chroma", None)
    if not archived or not archived.is_available:
        return

    try:
        # Limpiar índices previos del personaje
        existing = archived.get_all_documents()
        old_ids = [d["id"] for d in existing if d["id"] and str(d["id"]).startswith("charcore_")]
        if old_ids:
            archived.delete_ids(old_ids)

        manager = self._character_manager
        docs = []

        # [CHARACTER][IDENTITY]
        if manager.identity.name:
            docs.append({
                "id": "charcore_identity",
                "document": (
                    f"[CHARACTER][IDENTITY] Your name is {manager.identity.name}. "
                    f"Your role is {manager.identity.role}. "
                    f"Your age is {manager.identity.age}."
                ),
                "metadata": {"type": "charcore", "section": "identity"},
            })

        # [CHARACTER][BACKGROUND]
        if manager.identity.background:
            docs.append({
                "id": "charcore_background",
                "document": f"[CHARACTER][BACKGROUND] {manager.identity.background}",
                "metadata": {"type": "charcore", "section": "background"},
            })

        # [CHARACTER][SCENARIO]
        if manager.identity.scenario:
            docs.append({
                "id": "charcore_scenario",
                "document": f"[CHARACTER][SCENARIO] {manager.identity.scenario}",
                "metadata": {"type": "charcore", "section": "scenario"},
            })

        # [CHARACTER][TRAITS]
        if manager.personality_dna.traits:
            docs.append({
                "id": "charcore_traits",
                "document": f"[CHARACTER][TRAITS] {', '.join(manager.personality_dna.traits)}",
                "metadata": {"type": "charcore", "section": "traits"},
            })

        # [CHARACTER][RULES]
        if manager.rules.core_rules:
            rules_text = "\n".join(f"- {r}" for r in manager.rules.core_rules)
            docs.append({
                "id": "charcore_rules",
                "document": f"[CHARACTER][RULES]\n{rules_text}",
                "metadata": {"type": "charcore", "section": "rules"},
            })

        # [CHARACTER][SPEECH]
        if manager.speech.style or manager.speech.tone:
            style = manager.speech.style or "Not specified"
            tone = manager.speech.tone or "Not specified"
            verbosity = manager.speech.verbosity or "Not specified"
            docs.append({
                "id": "charcore_speech",
                "document": (
                    f"[CHARACTER][SPEECH] Style: {style}. Tone: {tone}. Verbosity: {verbosity}."
                ),
                "metadata": {"type": "charcore", "section": "speech"},
            })

        if docs:
            archived.add_documents_batch(docs)
            self._log_debug("CHAR", f"Indexadas {len(docs)} secciones del personaje en ChromaDB")

    except Exception as e:
        self._log_debug("CHAR", f"Error indexando secciones del personaje: {e}")


VToolLlama._index_character_core = _index_character_core


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
    """Construye y asigna el system prompt ESTABLE del personaje.

    NOTA: ya NO incluye TOOL_USAGE_POLICY — esa se inyecta como mensaje
    system dinámico antes del último user (ver _inject_tool_policy_if_needed).
    Esto mantiene el core del KV cache estable entre turnos (v6).
    """
    enriched_prompt = self._character_manager.build_system_prompt(
        self._config.system_prompt, self._config
    )

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


def get_character_dna(self: VToolLlama, name: Optional[str] = None) -> dict:
    """Retorna el DNA de un personaje SIN cargarlo (lee directo de disco).

    Args:
        name: nombre del personaje. Si es None, usa el personaje cargado actualmente.
    """
    from dataclasses import asdict

    if name is None:
        if not self._character_manager.is_loaded:
            raise RuntimeError("No hay personaje cargado y no se especificó name.")
        return {
            "identity": asdict(self._character_manager.identity),
            "personality": asdict(self._character_manager.personality_dna),
            "speech": asdict(self._character_manager.speech),
            "rules": asdict(self._character_manager.rules),
        }

    # Leer directo de disco sin cargar el personaje
    base = self._character_manager._base_dir
    char_dir = base / name
    if not char_dir.exists() or not (char_dir / "dna").exists():
        raise ValueError(f"Personaje '{name}' no encontrado.")

    import json
    result = {}
    for dna_file in ("identity.json", "personality.json", "speech.json", "rules.json"):
        path = char_dir / "dna" / dna_file
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                result[dna_file.replace(".json", "")] = json.load(f)
        else:
            result[dna_file.replace(".json", "")] = {}

    return {
        "identity": result.get("identity", {}),
        "personality": result.get("personality", {}),
        "speech": result.get("speech", {}),
        "rules": result.get("rules", {}),
    }

VToolLlama.get_character_dna = get_character_dna


def get_character_prompt(self: VToolLlama, name: str) -> str:
    """Retorna el system prompt compilado de un personaje SIN cargarlo.

    Si existe base_prompt.yaml del último warmup lo retorna.
    Si no, construye el prompt desde los archivos DNA en disco.
    """
    base = self._character_manager._base_dir
    char_dir = base / name
    if not char_dir.exists() or not (char_dir / "dna").exists():
        raise ValueError(f"Personaje '{name}' no encontrado.")

    # 1. Intentar leer el YAML del último rebuild
    yaml_path = char_dir / "_memory" / "base_prompt.yaml"
    if yaml_path.exists():
        lines = yaml_path.read_text(encoding="utf-8").split("\n")
        # Saltar la primera línea "prompt: |" y el indentado "  "
        prompt_lines = []
        for line in lines[1:]:
            if line.startswith("  "):
                prompt_lines.append(line[2:])
            else:
                prompt_lines.append(line)
        prompt = "\n".join(prompt_lines).strip()
        if prompt:
            return prompt

    # 2. Fallback: construir desde DNA
    dna = self.get_character_dna(name)
    parts = [f"[SYSTEM CORE]\nEres {dna['identity'].get('name', name)}."]
    if dna['identity'].get('role'):
        parts.append(f"Tu rol es {dna['identity']['role']}.")
    if dna['personality'].get('traits'):
        parts.append(f"[PERSONALIDAD]\n{', '.join(dna['personality']['traits'])}")
    if dna['speech'].get('style'):
        parts.append(f"[ESTILO]\n{dna['speech']['style']}")
    if dna['rules'].get('core_rules'):
        for r in dna['rules']['core_rules']:
            parts.append(f"- {r}")

    return "\n".join(parts)

VToolLlama.get_character_prompt = get_character_prompt


def update_character_dna(self: VToolLlama, dna_type: str, data: dict,
                         character_name: Optional[str] = None) -> None:
    """Actualiza el DNA de un personaje SIN interrumpir el chat activo.

    Si se pasa character_name, escribe directo a disco sin cargar el
    personaje. Si no, actualiza el personaje actualmente cargado.

    Args:
        dna_type: "identity", "personality", "speech" o "rules"
        data: dict con campos a actualizar (merge sobre el actual)
        character_name: si se pasa, escribe directo a disco sin cargar
    """
    import json

    # Determinar directorio del personaje
    if character_name:
        base = self._character_manager._base_dir
        char_dir = base / character_name
        if not char_dir.exists() or not (char_dir / "dna").exists():
            raise ValueError(f"Personaje '{character_name}' no encontrado.")
    else:
        if not self._character_manager.is_loaded:
            raise RuntimeError("No hay personaje cargado y no se especificó character_name.")
        char_dir = self._character_manager._char_dir

    if not char_dir:
        raise RuntimeError("No hay directorio de personaje.")

    filename = f"{dna_type}.json"
    path = char_dir / "dna" / filename

    # Leer estado actual del disco
    current = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            current = json.load(f)

    # Mergear y escribir
    merged = {**current, **data}
    self._character_manager._write_json(path, merged)
    self._character_manager._log("DNA", f"{filename} actualizado en disco sin carga.")

    # Si estamos editando el personaje cargado, actualizar también en memoria
    if not character_name or (self._character_manager.is_loaded
                              and self._character_manager._char_dir == char_dir):
        from ..types import IdentityDNA, PersonalityDNA, SpeechDNA, RulesDNA
        mapping = {
            "identity": (IdentityDNA, self._character_manager.identity),
            "personality": (PersonalityDNA, self._character_manager.personality_dna),
            "speech": (SpeechDNA, self._character_manager.speech),
            "rules": (RulesDNA, self._character_manager.rules),
        }
        if dna_type in mapping:
            dc_type, current_obj = mapping[dna_type]
            updated = dc_type(**merged)
            setattr(self._character_manager, {
                "identity": "identity",
                "personality": "personality_dna",
                "speech": "speech",
                "rules": "rules",
            }[dna_type], updated)
            self._character_manager._prompt_dirty = True
            self._character_manager._needs_rebuild = True
            self._character_manager._log("DNA", f"{dna_type} actualizado en memoria.")

VToolLlama.update_character_dna = update_character_dna


def get_states(self: VToolLlama) -> dict:
    """Retorna los estados runtime del personaje."""
    if not self._character_manager.is_loaded:
        raise RuntimeError("No hay personaje cargado.")
    from dataclasses import asdict
    return {
        "runtime": asdict(self._character_manager.runtime_state),
        "personality": asdict(self._character_manager.personality_state),
        "relationship": asdict(self._character_manager.relationship_state),
    }

VToolLlama.get_states = get_states


def update_state(self: VToolLlama, state_type: str, data: dict) -> None:
    """Actualiza un estado runtime y persiste.

    Args:
        state_type: "runtime", "personality" o "relationship"
        data: dict con campos a actualizar (merge sobre el estado actual)
    """
    if not self._character_manager.is_loaded:
        raise RuntimeError("No hay personaje cargado.")

    from ..types import RuntimeState, PersonalityState, RelationshipState
    from dataclasses import asdict

    mapping = {
        "runtime": (RuntimeState, self._character_manager.runtime_state),
        "personality": (PersonalityState, self._character_manager.personality_state),
        "relationship": (RelationshipState, self._character_manager.relationship_state),
    }
    if state_type not in mapping:
        raise ValueError(f"Tipo inválido: {state_type}. Usá: runtime, personality, relationship")

    dc_type, current = mapping[state_type]
    merged = {**asdict(current), **data}
    updated = dc_type(**merged)

    if state_type == "runtime":
        self._character_manager.runtime_state = updated
    elif state_type == "personality":
        self._character_manager.personality_state = updated
    elif state_type == "relationship":
        self._character_manager.relationship_state = updated

    self._character_manager.save_state()
    self._character_manager._log("STATE", f"{state_type} actualizado.")

VToolLlama.update_state = update_state


def get_mods(self: VToolLlama) -> list[dict]:
    """Retorna la lista de mods activos del personaje."""
    if not self._character_manager.is_loaded:
        return []
    from dataclasses import asdict
    return [asdict(m) for m in self._character_manager.active_mods.values()]

VToolLlama.get_mods = get_mods


def set_mod(self: VToolLlama, mod_id: str, target_layer: str = "speech",
            override_value: str = "", intensity: float = 1.0) -> None:
    """Aplica un mod temporal al personaje."""
    from ..types import CharacterMod
    mod = CharacterMod(id=mod_id, target_layer=target_layer,
                       override_value=override_value, intensity=intensity)
    self._character_manager.set_mod(mod)
    self._character_manager._log("MOD", f"Mod '{mod_id}' aplicado en {target_layer}.")

VToolLlama.set_mod = set_mod


def remove_mod(self: VToolLlama, mod_id: str) -> None:
    """Elimina un mod activo."""
    self._character_manager.remove_mod(mod_id)
    self._character_manager._log("MOD", f"Mod '{mod_id}' eliminado.")

VToolLlama.remove_mod = remove_mod


def get_system_layer(self: VToolLlama, layer: str, character_name: Optional[str] = None) -> str:
    """Retorna el contenido de un YAML del personaje SIN cargarlo.

    Args:
        layer: "system_core", "anti_assistant", "roleplay_mode"
        character_name: nombre del personaje. Si es None, usa el cargado.
    """
    base = self._character_manager._base_dir
    filename = f"{layer}.yaml" if layer.endswith(".yaml") else f"{layer}.yaml"

    if character_name:
        base = self._character_manager._base_dir
        char_dir = base / character_name
        if not char_dir.exists() or not (char_dir / "dna").exists():
            raise ValueError(f"Personaje '{character_name}' no encontrado.")
    elif self._character_manager.is_loaded:
        char_dir = self._character_manager._char_dir
    else:
        raise RuntimeError("No hay personaje cargado y no se especificó character_name.")

    paths = [char_dir / filename, base / "default" / filename]
    for path in paths:
        try:
            if path and path.exists():
                text = path.read_text(encoding="utf-8")
                lines = text.split("\n")
                prompt_lines = []
                in_prompt = False
                for line in lines:
                    if line.startswith("prompt: |"):
                        in_prompt = True
                    elif in_prompt:
                        if line.startswith("  "):
                            prompt_lines.append(line[2:])
                        elif line == "":
                            prompt_lines.append("")
                        else:
                            break
                if prompt_lines:
                    return "\n".join(prompt_lines)
        except Exception:
            continue
    return ""

VToolLlama.get_system_layer = get_system_layer


def update_system_layer(self: VToolLlama, layer: str, content: str,
                        character_name: Optional[str] = None) -> None:
    """Actualiza un YAML del personaje (system_core, anti_assistant, roleplay_mode).

    Args:
        layer: "system_core", "anti_assistant", "roleplay_mode"
        content: texto completo del prompt
        character_name: si se pasa, escribe directo a disco sin cargar
    """

    if character_name:
        base = self._character_manager._base_dir
        char_dir = base / character_name
        if not char_dir.exists() or not (char_dir / "dna").exists():
            raise ValueError(f"Personaje '{character_name}' no encontrado.")
    else:
        if not self._character_manager.is_loaded:
            raise RuntimeError("No hay personaje cargado y no se especificó character_name.")
        char_dir = self._character_manager._char_dir

    filename = f"{layer}.yaml"
    lines = content.split("\n")
    yaml_lines = ["prompt: |"]
    for line in lines:
        yaml_lines.append(f"  {line}")
    yaml_lines.append("")

    path = char_dir / filename
    path.write_text("\n".join(yaml_lines), encoding="utf-8")
    self._character_manager._log("YAML", f"{filename} actualizado.")

    # Si es el personaje cargado, marcar dirty
    if not character_name or (self._character_manager.is_loaded
                              and self._character_manager._char_dir == char_dir):
        self._character_manager._prompt_dirty = True
        self._character_manager._needs_rebuild = True
        self._character_manager._log("YAML", f"{filename} marcado para rebuild.")

VToolLlama.update_system_layer = update_system_layer
