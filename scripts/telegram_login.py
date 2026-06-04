import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add src to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

load_dotenv(PROJECT_ROOT / ".env")

try:
    from telethon import TelegramClient
except ImportError:
    print("Telethon is not installed. Installing it now...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "telethon"])
    from telethon import TelegramClient

async def main():
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE")

    if not api_id or not api_hash:
        print("Error: TELEGRAM_API_ID or TELEGRAM_API_HASH is missing in your .env file.")
        return

    session_path = str(PROJECT_ROOT / "vani_session")
    print(f"Connecting to Telegram with session file: {session_path}")
    
    # Delete the old session to ensure a clean login for the new number
    session_file = Path(session_path + ".session")
    if session_file.exists():
        print(f"Found old session file. Deleting it to start a fresh login for {phone}...")
        try:
            session_file.unlink()
        except Exception as e:
            print(f"Could not delete old session: {e}")

    client = TelegramClient(session_path, int(api_id), api_hash)
    
    print("Starting Telegram Client...")
    await client.start(phone=lambda: phone or input("Enter phone number (e.g. +91...): "))
    
    if await client.is_user_authorized():
        print("\nSUCCESS: Telegram is successfully authorized!")
        me = await client.get_me()
        print(f"Logged in as: {me.first_name} {me.last_name or ''} (@{me.username or 'NoUsername'})")
    else:
        print("\nFAILED: Authorization not completed.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
