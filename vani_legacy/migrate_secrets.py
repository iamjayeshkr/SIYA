"""
vani/migrate_secrets.py
───────────────────────
One-time migration: reads secrets from .env and stores them in the OS keychain.
Run once, then you can (optionally) delete your .env file.

Usage:
    python -m vani.migrate_secrets
    python -m vani.migrate_secrets --env-file /path/to/.env
    python -m vani.migrate_secrets --dry-run   # preview without writing
"""

import argparse
import os
import sys
from pathlib import Path


# Keys to migrate from .env → keychain
KEYS_TO_MIGRATE = [
    "GEMINI_API_KEY",
    "LIVEKIT_URL",
    "LIVEKIT_TOKEN",
    "OLLAMA_HOST",
    "OPENAI_API_KEY",
]


def _load_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Skips comments and blank lines."""
    secrets = {}
    if not path.exists():
        print(f"[!] .env file not found at {path}")
        return secrets

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            # Strip surrounding quotes from value
            value = value.strip().strip('"').strip("'")
            secrets[key] = value

    return secrets


def migrate(env_path: Path, dry_run: bool = False) -> None:
    from vani.secrets import store_secret

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Vani OS — Secret Migration")
    print(f"Reading from: {env_path}\n")

    env_secrets = _load_env_file(env_path)
    migrated = 0
    skipped = 0

    for key in KEYS_TO_MIGRATE:
        value = env_secrets.get(key) or os.getenv(key)
        if not value:
            print(f"  ⚠  {key:<25} — not found in .env or environment, skipping")
            skipped += 1
            continue

        # Mask value for display
        masked = value[:4] + "*" * (len(value) - 4) if len(value) > 4 else "****"
        print(f"  {'(dry run) ' if dry_run else ''}✓  {key:<25} → keychain  [{masked}]")

        if not dry_run:
            store_secret(key, value)
        migrated += 1

    print(f"\n{'Would migrate' if dry_run else 'Migrated'} {migrated} secret(s), skipped {skipped}.")

    if not dry_run and migrated > 0:
        print("\nNext steps:")
        print("  1. Test that Vani starts correctly: python app.py")
        print("  2. If everything works, delete .env (or add it to .gitignore)")
        print("  3. Never commit API keys to git again 🎉")


def main():
    parser = argparse.ArgumentParser(description="Migrate Vani secrets from .env to OS keychain")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to .env file (default: .env in current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be migrated without writing to keychain",
    )
    args = parser.parse_args()

    try:
        migrate(args.env_file, dry_run=args.dry_run)
    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
