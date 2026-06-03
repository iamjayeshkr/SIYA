import os
from functools import lru_cache
from pathlib import Path
from typing import List, Dict, Optional, Union

from vani.config import PROJECT_ROOT

PROMPT_PRESETS = {
    "normal": ["core"],
    "call": ["core", "call", "live", "tool"],
    "new_person": ["core", "call", "new_person"],
    "coding": ["core", "coding"],
    "social": ["core", "social"],
    "full": ["core", "call", "live", "tool", "pronunciation", "learned", "hinglish_speech", "teaching"],
    "realtime": ["core", "tool", "realtime"],
    "security": ["core", "security"],   # Lockdown mode — unverified speaker
    "cofounder": ["core", "cofounder"],  # Co-founder mode — startup strategy + daily standups
}

MODE_DEPENDENCIES = {
    "call": ["core"],
    "live": ["call"],
    "tool": ["core"],
    "coding": ["core"],
    "social": ["core"],
    "security": ["core"],
}

class PromptManager:
    def __init__(self, modes_dir: str | os.PathLike = PROJECT_ROOT / "modes"):
        self.modes_dir = Path(modes_dir)
        self.registered_modes: Dict[str, str] = {}
        self.active_modes: List[str] = []
        self.compiled_presets: Dict[str, str] = {}

    def register_mode(self, name: str, content: str):
        """Manually register or override a mode's content."""
        if self.registered_modes.get(name) == content:
            return
        self.registered_modes[name] = content
        # Selective invalidation
        self.load_mode.cache_clear()

    @lru_cache(maxsize=32)
    def load_mode(self, name: str) -> str:
        """Lazy load a mode from disk or registry."""
        if name in self.registered_modes:
            return self.registered_modes[name]
        
        file_path = self.modes_dir / f"{name}_mode.txt"
        if file_path.exists():
            try:
                with file_path.open("r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception as e:
                print(f"Error loading mode {name}: {e}")
                return ""
        return ""

    def activate_mode(self, name: str):
        """Add a mode to the active list if not already present."""
        if name not in self.active_modes:
            self.active_modes.append(name)

    def get_prompt(self, preset: Optional[str] = None, custom_modes: Optional[List[str]] = None) -> str:
        """Assemble the final prompt based on presets and custom modes."""
        if preset and not custom_modes and not self.active_modes:
            if preset in self.compiled_presets:
                return self.compiled_presets[preset]

        modes_to_load = []
        
        if preset and preset in PROMPT_PRESETS:
            modes_to_load.extend(PROMPT_PRESETS[preset])
        
        if custom_modes:
            modes_to_load.extend(custom_modes)
            
        # Add active modes
        modes_to_load.extend(self.active_modes)
        
        # Resolve dependencies
        final_list = []
        def resolve(m):
            if m in MODE_DEPENDENCIES:
                for dep in MODE_DEPENDENCIES[m]:
                    resolve(dep)
            if m not in final_list:
                final_list.append(m)

        for m in modes_to_load:
            resolve(m)
        
        prompt_parts = []
        for m in final_list:
            content = self.load_mode(m)
            if content:
                prompt_parts.append(content)
        
        return "\n\n".join(prompt_parts)

    def compile_presets(self):
        """Precompile all presets."""
        for preset in PROMPT_PRESETS:
            self.compiled_presets[preset] = self.get_prompt(preset=preset)

    def preload(self, modes: List[str]):
        """Preload specific modes."""
        for mode in modes:
            self.load_mode(mode)

# Singleton instance
manager = PromptManager()