#!/bin/bash
# bin/run_gemini.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "🔄 Switching Vani to Gemini Native Voice Mode..."

python3 -c '
import re
from pathlib import Path

env_file = Path(".env")
if env_file.exists():
    content = env_file.read_text(encoding="utf-8")
    
    # Set KOKORO_ENABLED=0
    if "KOKORO_ENABLED=" in content:
        content = re.sub(r"KOKORO_ENABLED=\d+", "KOKORO_ENABLED=0", content)
    else:
        content += "\nKOKORO_ENABLED=0\n"
        
    # Comment out KOKORO_HTTP_URL
    content = re.sub(r"^KOKORO_HTTP_URL=", "# KOKORO_HTTP_URL=", content, flags=re.MULTILINE)
    
    env_file.write_text(content, encoding="utf-8")
    print("✅ Configured .env: KOKORO_ENABLED=0 (Gemini Native Audio)")
else:
    print("⚠️  .env file not found!")
'

# Run Vani
exec "$SCRIPT_DIR/run_vani.sh"
