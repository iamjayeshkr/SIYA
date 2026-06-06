import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=True)
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


# ── Indic-TTS Configurations ──────────────────────────────────────────────────
INDIC_TTS_ENABLED          = os.getenv("INDIC_TTS_ENABLED", "1") == "1"
VANI_TTS_SPEAKER           = os.getenv("VANI_TTS_SPEAKER", "female")
VANI_TTS_LANG              = os.getenv("VANI_TTS_LANG", "hi")
VANI_TTS_FILLER            = os.getenv("VANI_TTS_FILLER", "breath")  # breath | hmm | none
VANI_INDIC_TTS_CHECKPOINTS = os.getenv("VANI_INDIC_TTS_CHECKPOINTS", "Indic-TTS-master/checkpoints")
VANI_CACHE_DIR             = os.path.expanduser(os.getenv("VANI_CACHE_DIR", "~/.vani"))
INDIC_TTS_MAX_CHARS        = env_int("INDIC_TTS_MAX_CHARS", 120)
