"""
Run this in your project terminal:
cd /Users/rudra/Documents/Vanni---My-Personal-Assistant-main\ 5
python3 debug_whatsapp.py
"""
import subprocess, os, sys, asyncio

print("="*60)
print("WHATSAPP DEBUG — Rudra's Machine")
print("="*60)

# TEST 1: Can open -a find WhatsApp?
print("\n[TEST 1] open -a WhatsApp")
r = subprocess.run(["open", "-a", "WhatsApp"], capture_output=True, text=True)
print(f"  returncode: {r.returncode}")
print(f"  stdout: {r.stdout.strip()!r}")
print(f"  stderr: {r.stderr.strip()!r}")

import time; time.sleep(2)

# TEST 2: Is process running?
print("\n[TEST 2] pgrep -fi whatsapp")
r2 = subprocess.run(["pgrep", "-fi", "whatsapp"], capture_output=True, text=True)
print(f"  returncode: {r2.returncode}")
print(f"  pids: {r2.stdout.strip()!r}")

# TEST 3: osascript System Events
print("\n[TEST 3] osascript — list WhatsApp processes")
script = 'tell application "System Events" to get name of every process whose name contains "WhatsApp"'
r3 = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
print(f"  result: {r3.stdout.strip()!r}")
print(f"  stderr: {r3.stderr.strip()!r}")

# TEST 4: Does /Applications/WhatsApp.app exist?
path = "/Applications/WhatsApp.app"
print(f"\n[TEST 4] path exists: {path}")
print(f"  exists: {os.path.exists(path)}")

# TEST 5: mdfind
print("\n[TEST 5] mdfind WhatsApp")
r5 = subprocess.run(
    ["mdfind", "kMDItemKind == 'Application' && kMDItemDisplayName == 'WhatsApp'"],
    capture_output=True, text=True, timeout=6
)
print(f"  found: {r5.stdout.strip()!r}")

# TEST 6: Ollama alive?
print("\n[TEST 6] Ollama status")
try:
    import requests
    r6 = requests.get("http://localhost:11434/api/tags", timeout=3)
    models = [m["name"] for m in r6.json().get("models", [])]
    print(f"  ✅ Ollama running. Models: {models}")
except Exception as e:
    print(f"  ❌ Ollama NOT running: {e}")

# TEST 7: Qwen direct test
print("\n[TEST 7] Qwen direct — 'open WhatsApp'")
try:
    import requests, json
    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "qwen2.5:3b", "prompt": 'Return JSON only: {"tool": "open_app", "args": {"app_name": "WhatsApp"}}. User said: open WhatsApp', "stream": False},
        timeout=15
    )
    raw = resp.json().get("response", "").strip()
    print(f"  raw: {raw!r}")
except Exception as e:
    print(f"  ❌ Qwen error: {e}")

print("\n" + "="*60)
print("Copy paste this full output and share it.")
print("="*60)