"""
vani_launcher.py — Phase 3 (Fixed)

Launch order (critical):
  1. Start vani_app.py --worker — it registers itself as a Worker with LiveKit cloud
  2. Wait 3 seconds for registration
  3. Start vani_app.py with --no-agent flag
     → vani_app.py creates room, dispatches agent, opens UI
     → UI auto-joins room, agent starts conversation immediately

This ensures no double agent launch and correct dispatch timing.
"""

import sys
import os
import subprocess
import threading
import time
import signal
import argparse
from pathlib import Path

from vani.services.wake import STARTING_REPLY, WAKE_ACK_REPLY

ROOT       = Path(__file__).resolve().parents[2]
SRC_ROOT   = ROOT / "src"
PYTHON     = sys.executable

IS_MAC     = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

agent_proc = None
app_proc   = None
_LOCK_FILE_HANDLE = None
_LOG_HANDLES: list = []


# ── Process management ────────────────────────────────────────────────────────

def _open_log(name: str):
    path = Path.home() / "Library/Logs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a", buffering=1, encoding="utf-8")
    _LOG_HANDLES.append(handle)
    return handle

def _acquire_single_instance_lock() -> bool:
    """Prevent multiple launcher instances for this user session."""
    global _LOCK_FILE_HANDLE
    if not IS_MAC:
        return True
    try:
        import fcntl
        lock_path = Path("/tmp") / f"{LAUNCH_AGENT_LABEL}.lock"
        _LOCK_FILE_HANDLE = open(lock_path, "w", encoding="utf-8")
        fcntl.flock(_LOCK_FILE_HANDLE, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LOCK_FILE_HANDLE.write(str(os.getpid()))
        _LOCK_FILE_HANDLE.flush()
        return True
    except BlockingIOError:
        return False
    except Exception as e:
        print(f"⚠️  Single-instance lock unavailable: {e}")
        return True


def _existing_vani_pids() -> list[int]:
    """Return existing Vani app PIDs not owned by this launcher process."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "vani.app"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return []

    current_children = {
        proc.pid for proc in (agent_proc, app_proc)
        if proc is not None and proc.poll() is None
    }
    own_pid = os.getpid()
    pids = []
    for raw in result.stdout.split():
        try:
            pid = int(raw)
        except ValueError:
            continue
        if pid != own_pid and pid not in current_children:
            pids.append(pid)
    return pids


def _port_open(port: int) -> bool:
    try:
        import socket
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["lsof", f"-ti:{port}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def is_vani_running() -> bool:
    local_running = any(
        proc is not None and proc.poll() is None
        for proc in (agent_proc, app_proc)
    )
    return local_running or _port_open(5500) or bool(_existing_vani_pids())


def start_processes():
    global agent_proc, app_proc

    if is_vani_running():
        print("✅ Vani is already running. No new launch needed.")
        _bring_window_to_front()
        return

    # Step 1: Start agent Worker (non-blocking)
    print("🚀 Starting Vani agent Worker…")
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(SRC_ROOT),
        "VANI_VOICE_BACKEND": os.environ.get("VANI_VOICE_BACKEND", "livekit"),
    }
    agent_log = _open_log("vani_agent.log")
    agent_proc = subprocess.Popen(
        [PYTHON, "-m", "vani.app", "--worker"],
        cwd=str(ROOT),
        stdout=agent_log,
        stderr=agent_log,
        env=env,
    )

    # Step 2: Start UI immediately — no blocking wait
    # Agent registration (≈1-2s) happens in background; UI is ready first
    print("🖥️  Starting Vani UI…")
    app_log = _open_log("vani_app.log")
    app_proc = subprocess.Popen(
        [PYTHON, "-m", "vani.app", "--no-agent"],
        cwd=str(ROOT),
        stdout=app_log,
        stderr=app_log,
        env=env,
    )
    print("✅ Vani is running.")

    # Step 3: Background thread waits for agent then dispatches
    # vani_app.py handles dispatch via _setup_room; this is a safety log only
    def _wait_and_log():
        time.sleep(2)
        if agent_proc and agent_proc.poll() is None:
            print("✅ Agent Worker confirmed running.")
        else:
            print("⚠️  Agent Worker may have exited early — check logs.")

    threading.Thread(target=_wait_and_log, daemon=True).start()


def stop_processes():
    global agent_proc, app_proc
    for proc in [agent_proc, app_proc]:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    agent_proc = None
    app_proc   = None
    for handle in list(_LOG_HANDLES):
        try:
            handle.close()
        except Exception:
            pass
    _LOG_HANDLES.clear()
    print("🛑 Vani stopped.")


def restart_processes():
    stop_processes()
    time.sleep(1)
    start_processes()


def wake_vani() -> str:
    """Start or focus Vani and return the hotword acknowledgement."""
    try:
        from vani.audio.priority import vani_activated
        vani_activated()
    except Exception:
        pass
    if is_vani_running():
        _bring_window_to_front()
        return WAKE_ACK_REPLY
    start_processes()
    return STARTING_REPLY


# ── Global hotkey ─────────────────────────────────────────────────────────────

def _launch_hotkey_listener():
    try:
        from pynput import keyboard

        if IS_MAC:
            COMBO = {keyboard.Key.cmd, keyboard.Key.shift, keyboard.KeyCode.from_char('v')}
        else:
            COMBO = {keyboard.Key.ctrl, keyboard.Key.shift, keyboard.KeyCode.from_char('v')}

        pressed = set()

        def on_press(key):
            try:
                if hasattr(key, 'char') and key.char:
                    pressed.add(keyboard.KeyCode.from_char(key.char.lower()))
                else:
                    pressed.add(key)
                if COMBO.issubset(pressed):
                    _hotkey_action()
            except Exception:
                pass

        def on_release(key):
            pressed.discard(key)
            try:
                pressed.discard(keyboard.KeyCode.from_char(key.char.lower() if key.char else ''))
            except Exception:
                pass

        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()
    except Exception as e:
        print(f"[hotkey] Listener failed: {e}")


def _hotkey_action():
    global agent_proc, app_proc
    print("⌨️  Hotkey fired!")
    if not is_vani_running():
        threading.Thread(target=start_processes, daemon=True).start()
    else:
        _bring_window_to_front()


def _bring_window_to_front():
    try:
        if IS_MAC:
            # Direct focus to active Browser rendering the UI
            script = """
            tell application "System Events"
                if exists (process "Google Chrome") then
                    tell application "Google Chrome" to activate
                else if exists (process "Safari") then
                    tell application "Safari" to activate
                end if
            end tell
            """
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        elif IS_WINDOWS:
            try:
                import pygetwindow as gw
                wins = gw.getWindowsWithTitle("Vani")
                if wins:
                    wins[0].activate()
            except Exception:
                pass
    except Exception:
        pass


# ── System tray ───────────────────────────────────────────────────────────────

def _build_tray_icon():
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print("⚠️  pystray / Pillow not installed — tray icon disabled.")
        print("   Run: pip install pystray pillow")
        return None

    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, size - 2, size - 2], fill=(130, 60, 210, 255))
    cx  = size // 2
    pad = 14
    bot = size - 10
    draw.line([(pad, 14), (cx, bot)], fill=(255, 255, 255, 230), width=5)
    draw.line([(size - pad, 14), (cx, bot)], fill=(255, 255, 255, 230), width=5)

    def on_start(icon, item):
        if not is_vani_running():
            threading.Thread(target=start_processes, daemon=True).start()
        else:
            print("Vani is already running.")

    def on_stop(icon, item):
        stop_processes()

    def on_restart(icon, item):
        threading.Thread(target=restart_processes, daemon=True).start()

    def on_quit(icon, item):
        stop_processes()
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("▶  Start Vani",  on_start),
        pystray.MenuItem("⏹  Stop Vani",   on_stop),
        pystray.MenuItem("🔄  Restart",     on_restart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("✕  Quit",         on_quit, default=False),
    )
    return pystray.Icon("Vani", img, "Vani — AI Assistant", menu)


def _run_tray(icon):
    if icon:
        icon.run()


# ── Auto-start ────────────────────────────────────────────────────────────────

def install_autostart():
    if IS_MAC:   _mac_install_launchagent()
    elif IS_WINDOWS: _win_install_startup()
    else: print("❌ Auto-start not supported on this OS.")

def uninstall_autostart():
    if IS_MAC:   _mac_uninstall_launchagent()
    elif IS_WINDOWS: _win_uninstall_startup()

LAUNCH_AGENT_LABEL = "com.rudra.vani"
LAUNCH_AGENT_PATH  = Path.home() / "Library/LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"

def _mac_install_launchagent():
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>             <string>{LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON}</string>
        <string>-m</string>
        <string>vani.launcher</string>
        <string>--autostart</string>
    </array>
    <key>RunAtLoad</key>         <true/>
    <key>KeepAlive</key>         <false/>
    <key>StandardOutPath</key>   <string>{Path.home()}/Library/Logs/vani_launcher.log</string>
    <key>StandardErrorPath</key> <string>{Path.home()}/Library/Logs/vani_launcher_err.log</string>
    <key>WorkingDirectory</key>  <string>{ROOT}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}</string>
        <key>PYTHONPATH</key>
        <string>{SRC_ROOT}</string>
    </dict>
</dict>
</plist>
"""
    LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENT_PATH.write_text(plist)
    for log_name in ("vani_launcher.log", "vani_launcher_err.log"):
        try:
            (Path.home() / "Library/Logs" / log_name).unlink(missing_ok=True)
        except Exception:
            pass
    subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT_PATH)], capture_output=True)
    subprocess.run(["launchctl", "load", str(LAUNCH_AGENT_PATH)], capture_output=True)
    print(f"✅ LaunchAgent installed: {LAUNCH_AGENT_PATH}")

def _mac_uninstall_launchagent():
    subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT_PATH)], capture_output=True)
    if LAUNCH_AGENT_PATH.exists():
        LAUNCH_AGENT_PATH.unlink()
    print("✅ LaunchAgent removed.")

def _win_startup_shortcut_path():
    return Path(os.environ.get("APPDATA", "")) / \
           "Microsoft/Windows/Start Menu/Programs/Startup/Vani.bat"

def _win_install_startup():
    bat  = f'@echo off\nset PYTHONPATH={SRC_ROOT}\ncd /d "{ROOT}"\nstart "" "{PYTHON}" -m vani.launcher\n'
    path = _win_startup_shortcut_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bat)
    print(f"✅ Windows startup entry: {path}")

def _win_uninstall_startup():
    path = _win_startup_shortcut_path()
    if path.exists():
        path.unlink()
    print("✅ Windows startup entry removed.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Vani Launcher")
    parser.add_argument("--install",   action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--autostart", action="store_true")
    parser.add_argument("--wake",      action="store_true")
    args = parser.parse_args()

    if args.install:
        install_autostart(); return
    if args.uninstall:
        uninstall_autostart(); return
    if args.wake:
        print(wake_vani())
        return

    print("╔══════════════════════════════════╗")
    print("║       Vani — Phase 3 Launch      ║")
    print("╚══════════════════════════════════╝")
    print(f"  Hotkey : {'Cmd' if IS_MAC else 'Ctrl'}+Shift+V")
    print(f"  Root   : {ROOT}")
    print()

    if not _acquire_single_instance_lock():
        print("✅ Vani launcher is already running. No new launch needed.")
        return

    start_processes()

    hotkey_thread = threading.Thread(target=_launch_hotkey_listener, daemon=True)
    hotkey_thread.start()
    print(f"⌨️  Hotkey active: {'Cmd' if IS_MAC else 'Ctrl'}+Shift+V")

    icon = _build_tray_icon()

    def _sigint(sig, frame):
        print("\n🛑 Shutting down…")
        stop_processes()
        if icon: icon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    if icon:
        if IS_MAC:
            _run_tray(icon)   # blocks on Mac (must be main thread)
        else:
            tray_thread = threading.Thread(target=_run_tray, args=(icon,), daemon=True)
            tray_thread.start()
            while True: time.sleep(1)
    else:
        while True: time.sleep(1)


if __name__ == "__main__":
    main()
