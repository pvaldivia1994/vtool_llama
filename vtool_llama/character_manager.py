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

        # Flag de rebuild forzado — se pone True al agregar memoria,
        # obliga a regenerar personality_plus_memory.state en la
        # próxima oportunidad (load o chat)
        self._needs_rebuild: bool = True

        # Compilador de Prompts
        self._compiler = CharacterCompiler(self)

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
            
            self._log("CHAR", f"Estructura del personaje '{name}' creada exitosamente.")

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

    def add_memory(self, content: str, priority: float = 0.5, always_include: bool = False, tags: Optional[list[str]] = None) -> MemoryEntry:
        with self._lock:
            entry = MemoryEntry(content=content, priority=priority, always_include=always_include, tags=tags or [])
            self.memories.append(entry)
            self._needs_rebuild = True
            self.save_state()
            self._log("CHAR", f"Memoria añadida: '{content[:50]}...'")
            return entry

    def set_mod(self, mod: CharacterMod) -> None:
        with self._lock:
            self.active_mods[mod.id] = mod
            self.save_state()
            self._log("CHAR", f"Mod aplicado: {mod.id}")

    def remove_mod(self, mod_id: str) -> None:
        with self._lock:
            if mod_id in self.active_mods:
                del self.active_mods[mod_id]
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
            next_id = len(existing) + 1
            
            episode = EpisodeSnapshot(
                episode_id=next_id,
                summary=summary,
                messages=messages,
            )
            
            filename = f"episode_{next_id:03d}.json"
            from dataclasses import asdict
            self._write_json(episodes_dir / filename, asdict(episode))
            
            self.current_episode = episode
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
        self._log("EPISODE", f"Episodio #{episode_id} restaurado (rollback).")

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

    def build_system_prompt(self, base_system_prompt: str) -> str:
        """
        Ensambla el system prompt combinando DNA, State, Memory y Mods
        a través del CharacterCompiler v2.
        """
        return self._compiler.compile_prompt(base_system_prompt)

    def build_base_system_prompt(self, base_system_prompt: str) -> str:
        """
        Ensambla solo la parte inmutable del prompt (DNA puro) para el KV Cache Base.
        """
        return self._compiler.compile_base_prompt(base_system_prompt)

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
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _log(self, tag: str, message: str) -> None:
        self._logger_fn(tag, message)
