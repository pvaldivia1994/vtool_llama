"""
Gestor del Character System para vtool_llama — Clase base.

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
from typing import Callable, Optional

from ..types import (
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
from ..compiler import CharacterCompiler


class CharacterManager:
    def __init__(
        self,
        base_dir: Optional[str] = None,
        logger_fn: Optional[Callable[[str, str], None]] = None,
    ):
        self._lock = threading.RLock()
        self._logger_fn = logger_fn or (lambda t, m: None)

        if base_dir is None:
            self._base_dir = Path(__file__).parent.parent / "characters"
        else:
            self._base_dir = Path(base_dir)

        self._ensure_dir(self._base_dir)

        self._character_name: Optional[str] = None
        self._char_dir: Optional[Path] = None

        self.identity: IdentityDNA = IdentityDNA()
        self.personality_dna: PersonalityDNA = PersonalityDNA()
        self.speech: SpeechDNA = SpeechDNA()
        self.rules: RulesDNA = RulesDNA()

        self.memories: list[MemoryEntry] = []
        self.runtime_state: RuntimeState = RuntimeState()
        self.personality_state: PersonalityState = PersonalityState()
        self.relationship_state: RelationshipState = RelationshipState()

        self.active_mods: dict[str, CharacterMod] = {}
        self.current_episode: Optional[EpisodeSnapshot] = None
        self._cached_prompt_hash: str = ""
        self._prompt_dirty: bool = True
        self._compiled_prompt_cache: str = ""
        self._needs_rebuild: bool = True

        self._soul_accessor = None
        self._psychology_manager = None
        self._genome: Optional[Genome] = None
        self._core_identity = None

        self._compiler = CharacterCompiler(self)
        self._chat_chroma = None

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

    def list_characters(self) -> list[str]:
        if not self._base_dir.exists():
            return []

        chars = []
        for d in self._base_dir.iterdir():
            if d.is_dir() and (d / "dna").exists():
                chars.append(d.name)
        return sorted(chars)

    def load_character(self, name: str) -> None:
        with self._lock:
            char_dir = self._base_dir / name
            if not char_dir.exists() or not (char_dir / "dna").exists():
                raise ValueError(f"Personaje '{name}' no encontrado en {self._base_dir}")

            self._character_name = name
            self._char_dir = char_dir
            self._prompt_dirty = True

            self._ensure_dir(self._char_dir / "memory")
            self._ensure_dir(self._char_dir / "memory" / "episodes")
            self._ensure_dir(self._char_dir / "state")
            self._ensure_dir(self._char_dir / "mods")

            self._load_dna()
            self._load_memory()
            self._load_latest_episode()
            self._load_state()
            self._load_mods()

            self._init_soul_accessor()
            self._init_chat_chroma()

            self._log("CHAR", f"Personaje '{name}' cargado exitosamente.")

    def create_character(
        self, name: str,
        identity_data: dict, personality_data: dict,
        speech_data: dict, rules_data: dict,
        initial_memories: list = None,
    ) -> None:
        with self._lock:
            char_dir = self._base_dir / name
            if char_dir.exists():
                raise ValueError(f"El personaje '{name}' ya existe en {self._base_dir}")

            self._ensure_dir(char_dir / "dna")
            self._ensure_dir(char_dir / "memory")
            self._ensure_dir(char_dir / "memory" / "episodes")
            self._ensure_dir(char_dir / "state")
            self._ensure_dir(char_dir / "mods")

            self._write_json(char_dir / "dna" / "identity.json", asdict(IdentityDNA(**identity_data)))
            self._write_json(char_dir / "dna" / "personality.json", asdict(PersonalityDNA(**personality_data)))
            self._write_json(char_dir / "dna" / "speech.json", asdict(SpeechDNA(**speech_data)))
            self._write_json(char_dir / "dna" / "rules.json", asdict(RulesDNA(**rules_data)))

            mems = []
            if initial_memories:
                import uuid
                for mem in initial_memories:
                    mems.append({
                        "id": str(uuid.uuid4())[:8],
                        "content": mem,
                        "priority": 1.0,
                        "always_include": True,
                        "tags": [],
                    })
            self._write_json(char_dir / "memory" / "long_term.json", {"memories": mems})

            self._write_json(char_dir / "state" / "state_meta.json", {"prompt_hash": ""})
            self._write_json(char_dir / "state" / "runtime_state.json", asdict(RuntimeState()))
            self._write_json(char_dir / "state" / "personality_state.json", asdict(PersonalityState()))
            self._write_json(char_dir / "state" / "relationship_state.json", asdict(RelationshipState()))
            self._write_json(char_dir / "mods" / "active_mods.json", {})

            import shutil
            default_config_path = self._base_dir / "default" / "config.json"
            if default_config_path.exists():
                shutil.copy2(str(default_config_path), str(char_dir / "config.json"))
            else:
                self._write_json(char_dir / "config.json", {})

            for yaml_file in ("system_core.yaml", "anti_assistant_layer.yaml"):
                src = self._base_dir / "default" / yaml_file
                if src.exists():
                    shutil.copy2(str(src), str(char_dir / yaml_file))

            self._log("CHAR", f"Estructura del personaje '{name}' creada exitosamente.")

    def build_system_prompt(self, base_system_prompt: str, config: Optional[ConfigSchema] = None) -> str:
        if not self._prompt_dirty and self._compiled_prompt_cache:
            return self._compiled_prompt_cache

        self._compiled_prompt_cache = self._compiler.compile_prompt(base_system_prompt, config)
        self._prompt_dirty = False
        return self._compiled_prompt_cache

    def mark_prompt_dirty(self) -> None:
        self._prompt_dirty = True

    def build_base_system_prompt(self, base_system_prompt: str, config: Optional[ConfigSchema] = None) -> str:
        return self._compiler.compile_base_prompt(base_system_prompt, config)

    def compile_base_soul_prompt(self, base_system_prompt: str, config: Optional[ConfigSchema] = None) -> str:
        return self._compiler.compile_base_soul_prompt(base_system_prompt, config)

    def get_relevant_memories(self) -> list[MemoryEntry]:
        with self._lock:
            mems = list(self.memories)
            mems.sort(key=lambda m: m.priority, reverse=True)
            return mems

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
        valid = {}
        for f in dataclass_type.__dataclass_fields__:
            if f in data:
                valid[f] = data[f]
        return valid

    def _write_json(self, path: Path, data: dict) -> None:
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
