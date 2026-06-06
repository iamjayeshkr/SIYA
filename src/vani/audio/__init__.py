"""Audio and avatar helpers."""

from .indic_tts_adapter import (
    synthesize_and_play,
    synthesize_and_play_chunked,
    stop_playback,
    is_short_reply,
    INDIC_TTS_ENABLED,
)
