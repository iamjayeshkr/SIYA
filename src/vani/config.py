import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parent
ASSETS_ROOT = PROJECT_ROOT / "assets"
BOOK_MEMORY_DIR = PROJECT_ROOT / "book_memory_store"

# ── Conversations / voiceprint ────────────────────────────────────────────────
CONVERSATIONS_DIR = PROJECT_ROOT / "conversations"
VOICEPRINT_PATH   = CONVERSATIONS_DIR / "voiceprint.npy"


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default
