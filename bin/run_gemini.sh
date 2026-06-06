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
    
    # Set INDIC_TTS_ENABLED=0
    if "INDIC_TTS_ENABLED=" in content:
        content = re.sub(r"INDIC_TTS_ENABLED=\d+", "INDIC_TTS_ENABLED=0", content)
    else:
        content += "\nINDIC_TTS_ENABLED=0\n"
    
    env_file.write_text(content, encoding="utf-8")
    print("✅ Configured .env: INDIC_TTS_ENABLED=0 (Gemini Native Audio)")
else:
    print("⚠️  .env file not found!")
'

# Run Vani
exec "$SCRIPT_DIR/run_vani.sh"
