#!/bin/bash
# bin/run_kokoro.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "🔄 Switching Vani to Kokoro TTS Voice Mode..."

python3 -c '
import re
from pathlib import Path

env_file = Path(".env")
if env_file.exists():
    content = env_file.read_text(encoding="utf-8")
    
    # Set KOKORO_ENABLED=1
    if "KOKORO_ENABLED=" in content:
        content = re.sub(r"KOKORO_ENABLED=\d+", "KOKORO_ENABLED=1", content)
    else:
        content += "\nKOKORO_ENABLED=1\n"
        
    # Uncomment KOKORO_HTTP_URL if commented out
    if re.search(r"^#\s*KOKORO_HTTP_URL=", content, flags=re.MULTILINE):
        content = re.sub(r"^#\s*KOKORO_HTTP_URL=(.*)", r"KOKORO_HTTP_URL=\1", content, flags=re.MULTILINE)
    elif "KOKORO_HTTP_URL=" not in content:
        content += "\nKOKORO_HTTP_URL=http://localhost:8100\n"
        
    env_file.write_text(content, encoding="utf-8")
    print("✅ Configured .env: KOKORO_ENABLED=1 (Kokoro TTS Enabled)")
else:
    print("⚠️  .env file not found!")
'

# Run Vani
exec "$SCRIPT_DIR/run_vani.sh"
