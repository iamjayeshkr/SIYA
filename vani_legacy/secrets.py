"""
vani/secrets.py
───────────────
Secure secret storage using the OS keychain (macOS Keychain, etc.)
via the `keyring` library.

Priority:
  1. OS keychain  (production — secure)
  2. Environment variable  (fallback for CI / dev)
  3. None  (logs a warning so you know something is missing)

First-time setup:
    python -m vani.migrate_secrets   # reads .env, stores in keychain

In app.py, replace:
    api_key = os.getenv("GEMINI_API_KEY")
With:
    from vani.secrets import get_gemini_key
    api_key = get_gemini_key()
"""

import os
from typing import Optional

import keyring

from vani.logging_config import get_logger

log = get_logger("secrets")

SERVICE_NAME = "vani-os"


# ── Low-level API ─────────────────────────────────────────────────────────────

def store_secret(key: str, value: str) -> None:
    """Store a secret in the OS keychain."""
    keyring.set_password(SERVICE_NAME, key, value)
    log.info("secret_stored", key=key)


def get_secret(key: str, env_fallback: Optional[str] = None) -> Optional[str]:
    """
    Retrieve a secret.

    1. Tries OS keychain first.
    2. Falls back to env_fallback env var (if provided).
    3. Returns None and logs a warning if neither has the value.
    """
    value = keyring.get_password(SERVICE_NAME, key)

    if value is not None:
        return value

    # Keychain miss — try environment variable fallback
    if env_fallback:
        env_value = os.getenv(env_fallback)
        if env_value:
            log.warning(
                "secret_from_env_fallback",
                key=key,
                env_var=env_fallback,
                message="Secret not in keychain; using env var. Run migrate_secrets.py to fix.",
            )
            return env_value

    log.warning("secret_missing", key=key, env_fallback=env_fallback)
    return None


def delete_secret(key: str) -> None:
    """Remove a secret from the keychain."""
    try:
        keyring.delete_password(SERVICE_NAME, key)
        log.info("secret_deleted", key=key)
    except keyring.errors.PasswordDeleteError:
        log.warning("secret_delete_not_found", key=key)


# ── Convenience wrappers ──────────────────────────────────────────────────────

def get_gemini_key() -> Optional[str]:
    return get_secret("GEMINI_API_KEY", env_fallback="GEMINI_API_KEY")

def get_livekit_url() -> Optional[str]:
    return get_secret("LIVEKIT_URL", env_fallback="LIVEKIT_URL")

def get_livekit_token() -> Optional[str]:
    return get_secret("LIVEKIT_TOKEN", env_fallback="LIVEKIT_TOKEN")

def get_ollama_host() -> str:
    """Ollama host — not a secret but kept here for consistency. Defaults to localhost."""
    return get_secret("OLLAMA_HOST", env_fallback="OLLAMA_HOST") or "http://localhost:11434"

def get_openai_key() -> Optional[str]:
    """Optional — only needed if using OpenAI as a fallback model."""
    return get_secret("OPENAI_API_KEY", env_fallback="OPENAI_API_KEY")
