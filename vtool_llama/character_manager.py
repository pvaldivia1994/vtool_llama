"""
Gestor del Character System para vtool_llama.

Maneja la arquitectura completa de personajes:
  - DNA (inmutable): identity.json, personality.json, speech.json, rules.json
  - Memory (mutable): long_term.json
  - State (runtime cache): runtime_state.json, personality_state.json
  - Mods (dinámicas temporales): mods.json
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Optional, Callable

from .types import (
    ConfigSchema,
    IdentityDNA,
    PersonalityDNA,
    SpeechDNA,
    RulesDNA,
    MemoryEntry,
    EpisodeSnapshot,
    RuntimeState,
    RelationshipState,
    PersonalityState,
    CharacterMod,
    Genome,
)
from .character_compiler import CharacterCompiler


class CharacterManager:
    """
    Orquesta la carga, guardado y ensamblado de las capas del Character System.
    """

    def __init__(
        self,
        base_dir: Optional[str] = None,
        logger_fn: Optional[Callable[[str, str], None]] = None,
    ):
        self._lock = threading.RLock()
        self._logger_fn = logger_fn or (lambda t, m: None)

        if base_dir is None:
            self._base_dir = Path(__file__).parent / "personajes"
        else:
            self._base_dir = Path(base_dir)
            
        self._ensure_dir(self._base_dir)

        self._character_name: Optional[str] = None
        self._char_dir: Optional[Path] = None

        # DNA (Inmutable en tiempo de ejecución)
        self.identity: IdentityDNA = IdentityDNA()
        self.personality_dna: PersonalityDNA = PersonalityDNA()
        self.speech: SpeechDNA = SpeechDNA()
        self.rules: RulesDNA = RulesDNA()

        # Memory
        self.memories: list[MemoryEntry] = []

        # State
        self.runtime_state: RuntimeState = RuntimeState()
        self.personality_state: PersonalityState = PersonalityState()
        self.relationship_state: RelationshipState = RelationshipState()
        
        # Mods
        self.active_mods: dict[str, CharacterMod] = {}

        # Episodic Memory (Short-term versionada)
        self.current_episode: Optional[EpisodeSnapshot] = None

        # Hash del System Prompt (para invalidación de KV Cache)
        self._cached_prompt_hash: str = ""

        # Prompt cache — evita recompilar en cada chat()
        self._prompt_dirty: bool = True
        self._compiled_prompt_cache: str = ""

        # Flag de rebuild forzado — se pone True al agregar memoria,
        # obliga a regenerar personality_plus_memory.state en la
        # próxima oportunidad (load o chat)
        self._needs_rebuild: bool = True

        # Soul System (opcional)
        self._soul_accessor = None
        # Psychology Engine v2 (runtime)
        self._psychology_manager = None
        self._genome: Optional[Genome] = None

        # Compilador de Prompts
        self._compiler = CharacterCompiler(self)

        # ChromaDB para historial de chat
        self._chat_chroma = None

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._character_name is not None

    @property
    def character_name(self) -> Optional[str]:
        return self._character_name

    def check_needs_rebuild(self, prompt: str) -> bool:
        import hashlib
        if self._needs_rebuild:
            return True
        current_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return current_hash != self._cached_prompt_hash

    # ------------------------------------------------------------------
    # Carga de Personajes
    # ------------------------------------------------------------------

    def list_characters(self) -> list[str]:
        """Devuelve los nombres de los personajes disponibles."""
        if not self._base_dir.exists():
            return []
        
        chars = []
        for d in self._base_dir.iterdir():
            if d.is_dir() and (d / "dna").exists():
                chars.append(d.name)
        return sorted(chars)

    def load_character(self, name: str) -> None:
        """
        Carga un personaje por nombre. Si no existe, lanza error.
        """
        with self._lock:
            char_dir = self._base_dir / name
            if not char_dir.exists() or not (char_dir / "dna").exists():
                raise ValueError(f"Personaje '{name}' no encontrado en {self._base_dir}")

            self._character_name = name
            self._char_dir = char_dir
            self._prompt_dirty = True
            
            # Crear estructura si falta algo
            self._ensure_dir(self._char_dir / "memory")
            self._ensure_dir(self._char_dir / "memory" / "episodes")
            self._ensure_dir(self._char_dir / "state")
            self._ensure_dir(self._char_dir / "mods")

            self._load_dna()
            self._load_memory()
            self._load_latest_episode()
            self._load_state()
            self._load_mods()
            
            # Inicializar Soul Accessor (opcional) si existe soul.json
            self._init_soul_accessor()
            
            # Inicializar Chat Memory ChromaDB
            self._init_chat_chroma()
            
            self._log("CHAR", f"Personaje '{name}' cargado exitosamente.")

    def create_character(self, name: str, identity_data: dict, personality_data: dict, speech_data: dict, rules_data: dict, initial_memories: list = None) -> None:
        """
        Crea la estructura de directorios y los archivos JSON para un nuevo personaje.
        
        Args:
            name: Nombre de la carpeta del personaje
            identity_data: Diccionario con los datos de IdentityDNA
            personality_data: Diccionario con los datos de PersonalityDNA
            speech_data: Diccionario con los datos de SpeechDNA
            rules_data: Diccionario con los datos de RulesDNA
            initial_memories: Lista opcional de textos para agregar como memoria inicial
        """
        with self._lock:
            char_dir = self._base_dir / name
            if char_dir.exists():
                raise ValueError(f"El personaje '{name}' ya existe en {self._base_dir}")
                
            # Crear estructura de directorios
            self._ensure_dir(char_dir / "dna")
            self._ensure_dir(char_dir / "memory")
            self._ensure_dir(char_dir / "memory" / "episodes")
            self._ensure_dir(char_dir / "state")
            self._ensure_dir(char_dir / "mods")
            
            # Escribir DNA
            from dataclasses import asdict
            self._write_json(char_dir / "dna" / "identity.json", asdict(IdentityDNA(**identity_data)))
            self._write_json(char_dir / "dna" / "personality.json", asdict(PersonalityDNA(**personality_data)))
            self._write_json(char_dir / "dna" / "speech.json", asdict(SpeechDNA(**speech_data)))
            self._write_json(char_dir / "dna" / "rules.json", asdict(RulesDNA(**rules_data)))
            
            # Escribir Memoria
            mems = []
            if initial_memories:
                import uuid
                for mem in initial_memories:
                    mems.append({
                        "id": str(uuid.uuid4())[:8],
                        "content": mem,
                        "priority": 1.0,
                        "always_include": True,
                        "tags": []
                    })
            self._write_json(char_dir / "memory" / "long_term.json", {"memories": mems})
            
            # Escribir Estados y Mods
            self._write_json(char_dir / "state" / "state_meta.json", {"prompt_hash": ""})
            self._write_json(char_dir / "state" / "runtime_state.json", asdict(RuntimeState()))
            self._write_json(char_dir / "state" / "personality_state.json", asdict(PersonalityState()))
            self._write_json(char_dir / "state" / "relationship_state.json", asdict(RelationshipState()))
            
            self._write_json(char_dir / "mods" / "active_mods.json", {})
            
            # Config.json del personaje (hereda de default para empezar configurable)
            import shutil
            default_config_path = self._base_dir / "default" / "config.json"
            if default_config_path.exists():
                shutil.copy2(str(default_config_path), str(char_dir / "config.json"))
            else:
                self._write_json(char_dir / "config.json", {})

            # YAML prompts del personaje (hereda de default)
            for yaml_file in ("system_core.yaml", "anti_assistant_layer.yaml"):
                src = self._base_dir / "default" / yaml_file
                if src.exists():
                    shutil.copy2(str(src), str(char_dir / yaml_file))
            
            self._log("CHAR", f"Estructura del personaje '{name}' creada exitosamente.")

    def _init_soul_accessor(self) -> None:
        """Inicializa el Soul Accessor + Psychology Engine v2."""
        if not self._char_dir:
            self._soul_accessor = None
            return

        from .soul_generator import RuntimeSoulAccessor, SoulGenerator
        dummy_gen = SoulGenerator(
            character_manager=self,
            model_manager=None,
            config=None,
            log_debug_fn=self._logger_fn,
        )
        accessor = RuntimeSoulAccessor(
            char_dir=self._char_dir,
            soul_generator=dummy_gen,
            log_debug_fn=self._logger_fn,
        )
        soul_active = accessor.initialize()
        if soul_active:
            self._soul_accessor = accessor
            self._log("SOUL", "Soul System activado para este personaje.")
        else:
            self._soul_accessor = None

        # Inicializar Psychology Engine v2
        self._init_psychology_engine()

    def _init_psychology_engine(self) -> None:
        """Carga Genome e inicializa RuntimeSoulManager."""
        if not self._char_dir:
            return

        # Cargar Genome
        genome_path = self._char_dir / "genome.json"
        if genome_path.exists():
            try:
                with open(genome_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._genome = Genome(**data)
                self._log("SOUL", "Genome cargado desde genome.json")
            except Exception as e:
                self._log("SOUL", f"Error cargando genome.json: {e}")
                self._genome = None

        # Si no hay genome, derivar desde PersonalityDNA (backward compat)
        if self._genome is None:
            from .psychology_engine import dna_traits_to_genome
            self._genome = dna_traits_to_genome(self.personality_dna)
            self._log("SOUL", "Genome derivado desde PersonalityDNA (backward compat)")

        # Cargar CoreIdentity (capa de interpretación)
        self._load_core_identity()

        # Inicializar RuntimeSoulManager
        if self._genome:
            from .psychology_engine import PsychologySynthesizer, RuntimeSoulManager
            synthesizer = PsychologySynthesizer(
                log_debug_fn=lambda t, m: self._logger_fn(t, m) if self._logger_fn else None,
                log_info_fn=lambda m: self._logger_fn("PSY", m) if self._logger_fn else None,
            )
            try:
                self._psychology_manager = RuntimeSoulManager(
                    char_dir=self._char_dir,
                    genome=self._genome,
                    synthesizer=synthesizer,
                    log_debug_fn=lambda t, m: self._logger_fn(t, m) if self._logger_fn else None,
                    log_info_fn=lambda m: self._logger_fn("PSY", m) if self._logger_fn else None,
                )
                # Pasar CoreIdentity al manager
                self._psychology_manager._core_identity = self._core_identity
                self._psychology_manager.load()
                self._psychology_manager.synthesize_psychology()
                self._psychology_manager.synthesize_persona()
                self._log("PSY", "Psychology Engine v2 inicializado")
            except Exception as e:
                self._log("PSY", f"Error inicializando Psychology Engine: {e}")
                self._psychology_manager = None

    def _load_core_identity(self) -> None:
        """Carga o inicializa CoreIdentity desde disco."""
        if not self._char_dir:
            return
        from .types import CoreIdentity
        ci_path = self._char_dir / "psychology" / "core_identity.json"
        if ci_path.exists():
            try:
                with open(ci_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._core_identity = CoreIdentity(**data)
                self._log("PSY", "CoreIdentity cargado desde disco")
                return
            except Exception as e:
                self._log("PSY", f"Error cargando CoreIdentity: {e}")

        # Inicializar desde genome + soul si existe
        self._core_identity = self._derive_core_identity_from_genome()

    def _derive_core_identity_from_genome(self) -> Any:
        """Deriva CoreIdentity inicial desde Genome cuando no hay archivo."""
        from .types import CoreIdentity
        ci = CoreIdentity()

        if not self._genome:
            return ci

        # Miedos desde genome
        if self._genome.risk_aversion > 0.6:
            ci.core_fears.append("uncertainty")
        if self._genome.emotional_sensitivity > 0.7:
            ci.core_fears.append("being overwhelmed")
        if self._genome.security_need > 0.7:
            ci.core_fears.append("instability")

        # Deseos desde genome
        if self._genome.sociability > 0.6:
            ci.core_desires.append("connection")
        if self._genome.curiosity > 0.6:
            ci.core_desires.append("understanding")
        if self._genome.independence > 0.6:
            ci.core_desires.append("freedom")
        if self._genome.creativity > 0.6:
            ci.core_desires.append("expression")

        # Sesgos de interpretación desde genome
        if self._genome.emotional_sensitivity > 0.7:
            ci.interpretation_biases["catastrophize"] = min(1.0, 0.5 + self._genome.emotional_sensitivity * 0.3)
        if self._genome.aggression > 0.6:
            ci.interpretation_biases["externalize_blame"] = min(1.0, 0.5 + self._genome.aggression * 0.3)
        if self._genome.emotional_sensitivity > 0.6 and self._genome.independence < 0.4:
            ci.interpretation_biases["internalize_blame"] = min(1.0, 0.5 + (1 - self._genome.independence) * 0.3)

        return ci

    # ------------------------------------------------------------------
    # Carga de Capas Internas
    # ------------------------------------------------------------------

    def _load_dna(self) -> None:
        if not self._char_dir: return
        dna_dir = self._char_dir / "dna"
        
        self.identity = IdentityDNA(**self._read_json(dna_dir / "identity.json", IdentityDNA))
        self.personality_dna = PersonalityDNA(**self._read_json(dna_dir / "personality.json", PersonalityDNA))
        self.speech = SpeechDNA(**self._read_json(dna_dir / "speech.json", SpeechDNA))
        self.rules = RulesDNA(**self._read_json(dna_dir / "rules.json", RulesDNA))

    def _load_memory(self) -> None:
        if not self._char_dir: return
        mem_file = self._char_dir / "memory" / "long_term.json"
        data = self._read_json_dict(mem_file)
        
        # Leer flag de rebuild from long_term.json
        # Si no existe (migración desde formato anterior), asumir True
        self._needs_rebuild = data.get("rebuild", True)
        
        raw_mems = data.get("memories", [])
        self.memories = [
            MemoryEntry(**{k: v for k, v in m.items() if k in MemoryEntry.__dataclass_fields__})
            for m in raw_mems
        ]

    def _load_state(self) -> None:
        if not self._char_dir: return
        state_dir = self._char_dir / "state"
        
        # Meta (hash del prompt)
        meta = self._read_json_dict(state_dir / "state_meta.json")
        self._cached_prompt_hash = meta.get("prompt_hash", "")
        
        # Runtime State
        rs = self._read_json(state_dir / "runtime_state.json", RuntimeState)
        self.runtime_state = RuntimeState(**rs)
        
        # Personality State
        ps = self._read_json(state_dir / "personality_state.json", PersonalityState)
        self.personality_state = PersonalityState(**ps)

        # Relationship State
        rels = self._read_json(state_dir / "relationship_state.json", RelationshipState)
        self.relationship_state = RelationshipState(**rels)

    def _load_mods(self) -> None:
        if not self._char_dir: return
        mods_file = self._char_dir / "mods" / "active_mods.json"
        data = self._read_json_dict(mods_file)
        
        self.active_mods = {}
        for k, v in data.items():
            self.active_mods[k] = CharacterMod(**{key: val for key, val in v.items() if key in CharacterMod.__dataclass_fields__})

    # ------------------------------------------------------------------
    # Guardado
    # ------------------------------------------------------------------

    def save_state(self) -> None:
        """Guarda Memory, State y Mods (el DNA es inmutable)."""
        if not self._char_dir: return
        with self._lock:
            # Save Memory — incluye flag rebuild para forzar
            # regeneración del KV Cache en la próxima carga
            mem_data = {
                "rebuild": self._needs_rebuild,
                "memories": [asdict(m) for m in self.memories]
            }
            self._write_json(self._char_dir / "memory" / "long_term.json", mem_data)
            
            # Save Meta
            meta_data = {"prompt_hash": self._cached_prompt_hash}
            self._write_json(self._char_dir / "state" / "state_meta.json", meta_data)
            
            # Save States
            self._write_json(self._char_dir / "state" / "runtime_state.json", asdict(self.runtime_state))
            self._write_json(self._char_dir / "state" / "personality_state.json", asdict(self.personality_state))
            self._write_json(self._char_dir / "state" / "relationship_state.json", asdict(self.relationship_state))
            
            # Save Mods
            mods_data = {k: asdict(v) for k, v in self.active_mods.items()}
            self._write_json(self._char_dir / "mods" / "active_mods.json", mods_data)

    def save_psychology_state(self) -> None:
        """Persiste el estado de la Psychology Engine v2 + CoreIdentity."""
        if self._psychology_manager:
            try:
                self._psychology_manager.save()
            except Exception as e:
                self._log("PSY", f"Error guardando psychology state: {e}")

        # Guardar CoreIdentity
        if self._core_identity and self._char_dir:
            from .types import CoreIdentity
            if isinstance(self._core_identity, CoreIdentity):
                try:
                    (self._char_dir / "psychology").mkdir(parents=True, exist_ok=True)
                    with open(self._char_dir / "psychology" / "core_identity.json", "w", encoding="utf-8") as f:
                        import json
                        json.dump(self._core_identity.__dict__, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    self._log("PSY", f"Error guardando CoreIdentity: {e}")

    def mark_rebuild_done(self, prompt: str) -> None:
        with self._lock:
            import hashlib
            self._cached_prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            self._needs_rebuild = False
            self.save_state()
            self._log("CHAR", f"KV Cache sincronizado. Hash: {self._cached_prompt_hash[:8]}")

    # ------------------------------------------------------------------
    # Operaciones de Memoria y Mods
    # ------------------------------------------------------------------

    def _init_chat_chroma(self) -> None:
        """Inicializa ChromaStore para historial de chat."""
        if not self._char_dir:
            return
        from .chroma_store import ChromaStore, HAS_CHROMA
        if not HAS_CHROMA:
            self._log("CHAR", "ChromaDB no disponible para memoria de chat.")
            return
        self._chat_chroma = ChromaStore(
            db_path=self._char_dir / "memory" / "chat_history",
            collection_name="chat_history",
            log_fn=lambda m: self._log("CHAR", m)
        )
        if self._chat_chroma.initialize():
            self._log("CHAR", "Chat Memory ChromaDB inicializado.")
        else:
            self._chat_chroma = None

    def save_chat_turn(self, user_prompt: str, assistant_response: str) -> None:
        """Guarda un turno de conversación completo en ChromaDB."""
        if not self._chat_chroma or not self._chat_chroma.is_available:
            return
        
        turn_text = f"Usuario: {user_prompt}\nPersonaje: {assistant_response}"
        import uuid
        from datetime import datetime
        doc_id = uuid.uuid4().hex[:12]
        metadata = {
            "timestamp": datetime.now().isoformat(),
            "type": "chat_turn"
        }
        self._chat_chroma.add_document(doc_id, turn_text, metadata)

    def retrieve_relevant_chat(self, query: str, top_k: int = 3) -> list[dict]:
        """Recupera turnos pasados relevantes al query actual."""
        if not self._chat_chroma or not self._chat_chroma.is_available:
            return []
        return self._chat_chroma.search(query, top_k=top_k)

    def add_memory(self, content: str, priority: float = 0.5, always_include: bool = False, tags: Optional[list[str]] = None) -> MemoryEntry:
        with self._lock:
            entry = MemoryEntry(content=content, priority=priority, always_include=always_include, tags=tags or [])
            self.memories.append(entry)
            self._needs_rebuild = True
            self._prompt_dirty = True
            self.save_state()
            self._log("CHAR", f"Memoria añadida: '{content[:50]}...'")
            return entry

    def set_mod(self, mod: CharacterMod) -> None:
        with self._lock:
            self.active_mods[mod.id] = mod
            self._prompt_dirty = True
            self.save_state()
            self._log("CHAR", f"Mod aplicado: {mod.id}")

    def remove_mod(self, mod_id: str) -> None:
        with self._lock:
            if mod_id in self.active_mods:
                del self.active_mods[mod_id]
                self._prompt_dirty = True
                self.save_state()

    # ------------------------------------------------------------------
    # Episodic Memory (Short-Term Versionada)
    # ------------------------------------------------------------------

    def _load_latest_episode(self) -> None:
        """Carga el episodio más reciente del directorio de episodios."""
        if not self._char_dir:
            return
        episodes_dir = self._char_dir / "memory" / "episodes"
        if not episodes_dir.exists():
            self.current_episode = None
            return
        
        episode_files = sorted(episodes_dir.glob("episode_*.json"))
        if not episode_files:
            self.current_episode = None
            return
        
        latest = episode_files[-1]
        data = self._read_json_dict(latest)
        self.current_episode = EpisodeSnapshot(
            episode_id=data.get("episode_id", 0),
            timestamp=data.get("timestamp", ""),
            summary=data.get("summary", ""),
            messages=data.get("messages", []),
        )
        self._log("EPISODE", f"Episodio #{self.current_episode.episode_id} cargado ({latest.name})")

    def save_episode(self, messages: list[dict], summary: str) -> EpisodeSnapshot:
        """
        Guarda un nuevo snapshot episódico. Nunca sobreescribe;
        crea episode_001.json, episode_002.json, etc.
        
        Args:
            messages: los últimos N mensajes del chat
            summary: resumen generado por el LLM
            
        Returns:
            EpisodeSnapshot creado
        """
        if not self._char_dir:
            raise RuntimeError("No hay personaje cargado.")
        with self._lock:
            episodes_dir = self._char_dir / "memory" / "episodes"
            self._ensure_dir(episodes_dir)
            
            # Determinar el siguiente número
            existing = sorted(episodes_dir.glob("episode_*.json"))
            next_id = 1
            if existing:
                try:
                    # Extraer el ID del último archivo (ej: episode_002.json -> 2)
                    last_id = int(existing[-1].stem.split("_")[-1])
                    next_id = last_id + 1
                except ValueError:
                    next_id = len(existing) + 1

            filename = f"episode_{next_id:03d}.json"

            episode = EpisodeSnapshot(
                episode_id=next_id,
                summary=summary,
                messages=messages,
            )
            from dataclasses import asdict
            self._write_json(episodes_dir / filename, asdict(episode))
            self.current_episode = episode
            self._prompt_dirty = True
            self._log("EPISODE", f"Episodio #{next_id} guardado ({filename})")
            return episode

    def list_episodes(self) -> list[dict]:
        """Lista todos los episodios disponibles con su metadata."""
        if not self._char_dir:
            return []
        episodes_dir = self._char_dir / "memory" / "episodes"
        if not episodes_dir.exists():
            return []
        
        results = []
        for f in sorted(episodes_dir.glob("episode_*.json")):
            data = self._read_json_dict(f)
            results.append({
                "file": f.name,
                "episode_id": data.get("episode_id", 0),
                "timestamp": data.get("timestamp", ""),
                "summary": data.get("summary", "")[:80],
                "message_count": len(data.get("messages", [])),
            })
        return results

    def load_episode(self, episode_id: int) -> None:
        """Carga un episodio específico por su ID (para rollback)."""
        if not self._char_dir:
            raise RuntimeError("No hay personaje cargado.")
        
        filename = f"episode_{episode_id:03d}.json"
        filepath = self._char_dir / "memory" / "episodes" / filename
        if not filepath.exists():
            raise ValueError(f"Episodio #{episode_id} no encontrado.")
        
        data = self._read_json_dict(filepath)
        self.current_episode = EpisodeSnapshot(
            episode_id=data.get("episode_id", episode_id),
            timestamp=data.get("timestamp", ""),
            summary=data.get("summary", ""),
            messages=data.get("messages", []),
        )
        self._prompt_dirty = True
        self._log("EPISODE", f"Episodio #{episode_id} restaurado (rollback).")

        # Rollback de ChromaDB: eliminar turnos de chat creados después de la fecha del episodio
        target_timestamp = self.current_episode.timestamp
        if target_timestamp and self._chat_chroma and self._chat_chroma.is_available:
            self._log("EPISODE", f"Ejecutando rollback de ChromaDB a partir del timestamp: {target_timestamp}")
            self._chat_chroma.delete_by_metadata(where={"timestamp": {"$gt": target_timestamp}})

    def delete_episode(self, episode_id: int) -> bool:
        """Elimina un episodio por su ID."""
        if not self._char_dir:
            return False
        filename = f"episode_{episode_id:03d}.json"
        filepath = self._char_dir / "memory" / "episodes" / filename
        if filepath.exists():
            filepath.unlink()
            self._log("EPISODE", f"Episodio #{episode_id} eliminado.")
            # Si era el actual, recargar el último
            if self.current_episode and self.current_episode.episode_id == episode_id:
                self._load_latest_episode()
            return True
        return False

    def get_relevant_memories(self) -> list[MemoryEntry]:
        with self._lock:
            mems = list(self.memories)
            mems.sort(key=lambda m: m.priority, reverse=True)
            return mems

    # ------------------------------------------------------------------
    # Generador de Prompt (El Ensamblador)
    # ------------------------------------------------------------------

    def build_system_prompt(self, base_system_prompt: str, config: Optional[ConfigSchema] = None) -> str:
        """
        Ensambla el system prompt combinando DNA, State, Memory y Mods
        a través del CharacterCompiler v2.

        Usa cache interno: solo recompila si _prompt_dirty=True.

        Args:
            base_system_prompt: prompt base del config.json
            config: ConfigSchema para system_core y anti_assistant_layer
        """
        if not self._prompt_dirty and self._compiled_prompt_cache:
            return self._compiled_prompt_cache

        self._compiled_prompt_cache = self._compiler.compile_prompt(base_system_prompt, config)
        self._prompt_dirty = False
        return self._compiled_prompt_cache

    def mark_prompt_dirty(self) -> None:
        """Marca el prompt cache como sucio para forzar recompilación."""
        self._prompt_dirty = True

    def build_base_system_prompt(self, base_system_prompt: str, config: Optional[ConfigSchema] = None) -> str:
        """
        Ensambla solo la parte inmutable del prompt (DNA puro) para el KV Cache Base.
        """
        return self._compiler.compile_base_prompt(base_system_prompt, config)

    def compile_base_soul_prompt(self, base_system_prompt: str, config: Optional[ConfigSchema] = None) -> str:
        """
        Ensambla el prompt base incluyendo DNA y Soul para el KV Cache Base Soul.
        """
        return self._compiler.compile_base_soul_prompt(base_system_prompt, config)

    # ------------------------------------------------------------------
    # Utils
    # ------------------------------------------------------------------

    def _ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def _read_json_dict(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _read_json(self, path: Path, dataclass_type: type) -> dict:
        data = self._read_json_dict(path)
        # Filtrar campos válidos
        valid = {}
        for f in dataclass_type.__dataclass_fields__:
            if f in data:
                valid[f] = data[f]
        return valid

    def _write_json(self, path: Path, data: dict) -> None:
        # Usar escritura atómica para evitar corrupción
        temp_path = path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, path)
        except Exception as e:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise e

    def _log(self, tag: str, message: str) -> None:
        self._logger_fn(tag, message)
