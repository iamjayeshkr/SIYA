"""
vani_app.py — Fixed for livekit-agents 1.2.1

Bugs fixed vs original:
  1. AgentSession() — uses livekit-agents 1.2.x session kwargs directly
     instead of newer nested turn_handling config.
  2. RoomInputOptions import removed (unused, may not exist in 1.2.1)
  3. model="gemini-2.0-flash-live-001" → "gemini-2.0-flash-live-preview"
     (3.1 does not exist → would crash at runtime)
  4. Realtime audio fix: patched plugin + retry/fallback logic

Additional fixes applied in this version:
  5. FIX: Duplicate `except ImportError` block for AUDIO_PRIORITY removed.
     The second handler was silently clobbering the first and always setting
     AUDIO_PRIORITY = False, disabling audio priority even when import succeeded.
  6. FIX: RoomInputOptions used in room_input code path without a None-check.
     If the import failed (ImportError caught at entrypoint top), using it as
     RoomInputOptions(noise_cancellation=nc) raised UnboundLocalError at runtime.
     Now guarded: only used when both RoomInputOptions is not None and nc loaded OK.
"""

import asyncio
import os
import sys
import json
import uuid
import signal
import subprocess
import threading
import webbrowser
import logging
import hashlib
import base64
import struct
import socket
from pathlib import Path
from dotenv import load_dotenv
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from vani.config import ASSETS_ROOT, PACKAGE_ROOT, PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vani")

# ── Model routing ─────────────────────────────────────────────────────────────
PREFERRED_MODEL = "gemini-3.1-flash"
REALTIME_MODEL  = "gemini-2.5-flash-native-audio-preview-12-2025"
log.info(f"[MODEL] Preferred: {PREFERRED_MODEL}  Runtime (realtime): {REALTIME_MODEL}")


# ── FIX 5: Single AUDIO_PRIORITY import block — duplicate except removed ───────
# Original had two except ImportError handlers; the second always ran and set
# AUDIO_PRIORITY = False even when the first import succeeded.
try:
    from vani.audio.priority import vani_activated, vani_deactivated
    AUDIO_PRIORITY = True
except Exception as e:
    log.warning(f"[audio] vani_audio_priority.py nahi mila — priority disabled: {e}")
    AUDIO_PRIORITY = False
    def vani_activated(): pass
    def vani_deactivated(): pass


# ── Security state — unverified speaker lockdown ──────────────────────────────
try:
    from vani.security_state import (
        activate_lockdown, deactivate_lockdown, is_locked_down,
        get_lockdown_response, is_verify_enabled,
        all_questions_answered,
    )
    SECURITY_ENABLED = True
except ImportError:
    SECURITY_ENABLED = False
    def activate_lockdown(): pass
    def deactivate_lockdown(): pass
    def is_locked_down(): return False
    def get_lockdown_response(t): return ""
    def is_verify_enabled(): return False
    def all_questions_answered(): return False


ROOT      = PROJECT_ROOT
HTML_PATH = PACKAGE_ROOT / "ui" / "ui.html"
PATCHED_HTML_PATH = PROJECT_ROOT / "_ui_patched.html"
IS_MAC    = sys.platform == "darwin"
IS_WIN    = sys.platform == "win32"

# ── Phase 9: Cross-platform adapter ───────────────────────────────────────────
try:
    from vani.core.platform import _adapter as _platform_adapter, notify_mac as _notify_mac_p9
    _PLATFORM_ADAPTER_OK = True
except Exception as _p9_err:
    log.warning(f"[platform] Phase 9 adapter unavailable (non-fatal): {_p9_err}")
    _PLATFORM_ADAPTER_OK = False
# ──────────────────────────────────────────────────────────────────────────────

state = {
    "speaking":   False,
    "listening":  False,
    "processing": False,
    "connected":  False,
    "text_ready": False,
    "status":     "Starting up...",
}

# ── WebSocket push manager ─────────────────────────────────────────────────────
_ws_clients: set = set()
_ws_clients_lock = threading.Lock()
_ws_push_lock = threading.Lock()
_state_snapshot: str = ""
_ws_client_counter = 0


def _ws_handshake(sock, headers_or_raw) -> bool:
    try:
        if hasattr(headers_or_raw, "get"):
            key_header = headers_or_raw.get("Sec-WebSocket-Key", "").strip()
        else:
            request = headers_or_raw.decode("utf-8", errors="replace")
            key_header = ""
            for line in request.split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key_header = line.split(":", 1)[1].strip()
                    break
        if not key_header:
            return False
        magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        accept = base64.b64encode(
            hashlib.sha1((key_header + magic).encode()).digest()
        ).decode()
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "\r\n"
        )
        sock.sendall(response.encode())
        return True
    except Exception as e:
        log.warning(f"[WS] Handshake failed: {e}")
        return False


def _ws_encode(payload: str) -> bytes:
    data = payload.encode("utf-8")
    length = len(data)
    if length <= 125:
        header = struct.pack("!BB", 0x81, length)
    elif length <= 65535:
        header = struct.pack("!BBH", 0x81, 126, length)
    else:
        header = struct.pack("!BBQ", 0x81, 127, length)
    return header + data


def _ws_push_state():
    global _state_snapshot
    with _ws_push_lock:
        payload = json.dumps(state)
        if payload == _state_snapshot:
            return
        _state_snapshot = payload
        frame = _ws_encode(payload)
        with _ws_clients_lock:
            clients = set(_ws_clients)
    dead = set()
    for sock in clients:
        try:
            sock.sendall(frame)
        except Exception:
            dead.add(sock)
    if dead:
        with _ws_clients_lock:
            _ws_clients.difference_update(dead)
        for s in dead:
            try: s.close()
            except Exception: pass


def _ws_client_thread(sock, client_id: int = 0):
    sock.settimeout(60.0)
    try:
        with _ws_clients_lock:
            _ws_clients.add(sock)
        try:
            sock.sendall(_ws_encode(json.dumps(state)))
        except Exception:
            with _ws_clients_lock:
                _ws_clients.discard(sock)
            return
        while True:
            try:
                header = sock.recv(2)
                if not header or len(header) < 2:
                    break
                b1, b2 = header[0], header[1]
                opcode = b1 & 0x0F
                if opcode == 0x8:
                    break
                masked = bool(b2 & 0x80)
                plen = b2 & 0x7F
                if plen == 126:
                    plen = struct.unpack("!H", sock.recv(2))[0]
                elif plen == 127:
                    plen = struct.unpack("!Q", sock.recv(8))[0]
                to_read = plen + (4 if masked else 0)
                while to_read > 0:
                    chunk = sock.recv(min(to_read, 4096))
                    if not chunk:
                        return
                    to_read -= len(chunk)
            except socket.timeout:
                try:
                    sock.sendall(struct.pack("!BB", 0x89, 0))
                except Exception:
                    break
            except Exception:
                break
    finally:
        with _ws_clients_lock:
            _ws_clients.discard(sock)
        try:
            sock.close()
        except Exception:
            pass
        log.debug(f"[WS] client-{client_id} disconnected")


def _patched_state_update(new_values: dict):
    state.update(new_values)
    _ws_push_state()


def _notify_mac(title: str, message: str):
    """
    Cross-platform notification shim (Phase 9).
    Routes through the platform adapter so it works on Mac, Windows, Linux.
    Falls back to the original macOS-only implementation if adapter unavailable.
    """
    if _PLATFORM_ADAPTER_OK:
        try:
            _notify_mac_p9(title, message)
            return
        except Exception:
            pass
    # Legacy fallback (Mac only)
    if not IS_MAC or os.getenv("VANI_MAC_NOTIFICATIONS", "1") != "1":
        return
    try:
        script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


async def _run_text_command(msg: str) -> str:
    from vani.services.text_chat import handle_text_command
    return await handle_text_command(msg)


async def _prewarm_ollama():
    try:
        import requests
        url = "http://localhost:11434/api/generate"
        await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: requests.post(url, json={"model": "qwen2.5:3b", "prompt": "hi", "stream": False}, timeout=10)
        )
        log.info("[ollama] Model warmed up successfully.")
    except Exception as e:
        log.warning(f"[ollama] Warmup failed: {e}")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except AttributeError:
            pass
        finally:
            if self.connection is None:
                self.close_connection = True

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if self.path == "/send_text":
            try:
                length = int(self.headers.get("Content-Length", 0))
                try:
                    body = json.loads(self.rfile.read(length))
                except (json.JSONDecodeError, ValueError):
                    self._send_json(400, {"reply": "Invalid JSON payload."})
                    return
                msg    = body.get("message", "").strip()
                reply  = ""
                spoken = False

                if msg:
                    try:
                        from vani.reasoning.tools.study_mode import (
                            is_study_mode_active, is_distraction_query, get_distraction_reply,
                        )
                        if is_study_mode_active():
                            _is_dist, _topic = is_distraction_query(msg)
                            if _is_dist:
                                _daant = get_distraction_reply(_topic)
                                try:
                                    from vani.reasoning import speak_to_user_from_thread
                                    speak_to_user_from_thread(_daant)
                                except Exception:
                                    pass
                                self._send_json(200, {"reply": _daant, "spoken": True, "mode": "study_block"})
                                return
                    except Exception as _se:
                        log.warning(f"[study] distraction check failed: {_se}")

                    if os.getenv("VANI_TEXT_TO_REALTIME", "1") == "1":
                        try:
                            from vani.reasoning import ask_realtime_from_text_thread
                            spoken = ask_realtime_from_text_thread(msg)
                        except Exception as e:
                            log.warning(f"[text] realtime route failed: {e}")
                            spoken = False

                    if spoken:
                        reply = "Vani voice mein answer kar rahi hai."
                    else:
                        try:
                            reply = asyncio.run(_run_text_command(msg))
                        except asyncio.TimeoutError:
                            timeout_secs = os.getenv("VANI_TEXT_TIMEOUT", "8")
                            reply = (
                                f"Timeout ho gaya ({timeout_secs}s). "
                                "Ollama slow hai ya band hai — 'ollama serve' check karo."
                            )
                        except RuntimeError as e:
                            log.warning(f"[text] asyncio.run conflict: {e} — using executor")
                            import concurrent.futures
                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                                fut = ex.submit(asyncio.run, _run_text_command(msg))
                                try:
                                    reply = fut.result(timeout=float(os.getenv("VANI_TEXT_TIMEOUT", "8")))
                                except Exception as ex2:
                                    reply = f"Error: {ex2}"
                        except Exception as e:
                            log.exception("[text] _run_text_command failed")
                            reply = f"Error: {e}"

                if not reply or not reply.strip():
                    reply = "Sun rahi hoon — kuch samajh nahi aaya, dobara bol sakte ho?"

                if not spoken:
                    try:
                        from vani.reasoning import speak_to_user_from_thread
                        spoken = speak_to_user_from_thread(reply, limit=None)
                    except Exception as e:
                        log.warning(f"[text] speak reply failed: {e}")

                self._send_json(200, {
                    "reply": reply,
                    "spoken": spoken,
                    "mode": "realtime" if spoken else "text",
                })
            except Exception as e:
                log.exception("[text] /send_text handler crashed")
                self._send_json(500, {"reply": f"❌ Server error: {e}"})

        elif self.path == "/analyze_document":
            try:
                import cgi
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0:
                    self._send_json(400, {"reply": "Document upload empty hai."})
                    return
                max_upload_mb = int(os.getenv("VANI_BOOK_MAX_UPLOAD_MB", "60"))
                if length > max_upload_mb * 1024 * 1024:
                    self._send_json(413, {"reply": f"File bahut badi hai. {max_upload_mb} MB se chhoti file bhejo."})
                    return
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        "REQUEST_METHOD": "POST",
                        "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                        "CONTENT_LENGTH": str(length),
                    },
                )
                file_item = form["file"] if "file" in form else None
                if file_item is None or not getattr(file_item, "filename", ""):
                    self._send_json(400, {"reply": "Koi document select nahi hua."})
                    return
                filename = Path(file_item.filename).name
                data = file_item.file.read()
                user_prompt = form.getfirst("prompt", "").strip()
                browser_mime = self.headers.get("Content-Type", "")
                self._send_json(200, {
                    "reply": f"⏳ '{filename}' padh rahi hoon... ek second.",
                    "filename": filename,
                })
                def _ingest():
                    try:
                        from vani.services.document_service import analyze_document
                        ok, reply_text = analyze_document(
                            filename, data,
                            user_prompt=user_prompt,
                            browser_mime=browser_mime,
                        )
                        if ok:
                            try:
                                from vani.reasoning.worker import notify_realtime_doc_upload_thread
                                notify_realtime_doc_upload_thread(filename)
                            except Exception as e:
                                log.warning(f"[docs] voice ack failed: {e}")
                        else:
                            log.warning(f"[docs] ingest failed: {reply_text}")
                    except Exception:
                        log.exception("[docs] background ingest crashed")
                import threading
                threading.Thread(target=_ingest, daemon=True, name="doc-ingest").start()
            except Exception as e:
                log.exception("[docs] analyze_document failed")
                self._send_json(500, {"reply": f"❌ Document read error: {e}"})

        elif self.path == "/analyze_image":
            try:
                import cgi
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0:
                    self._send_json(400, {"reply": "Image upload empty hai."})
                    return
                max_upload_mb = int(os.getenv("VANI_IMAGE_MAX_UPLOAD_MB", "15"))
                if length > max_upload_mb * 1024 * 1024:
                    self._send_json(413, {"reply": f"Image bahut badi hai. {max_upload_mb} MB se chhoti image bhejo."})
                    return
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        "REQUEST_METHOD": "POST",
                        "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                        "CONTENT_LENGTH": str(length),
                    },
                )
                file_item = form["file"] if "file" in form else None
                if file_item is None or not getattr(file_item, "filename", ""):
                    self._send_json(400, {"reply": "Koi image select nahi hui."})
                    return
                filename = Path(file_item.filename).name
                data = file_item.file.read()
                user_prompt = form.getfirst("prompt", "").strip()
                browser_mime = getattr(file_item, "type", "") or ""
                try:
                    from vani.reasoning import speak_to_user_from_thread
                    speak_to_user_from_thread("Image mil gayi. Dekh rahi hoon.", limit=None)
                except Exception as e:
                    log.warning(f"[image] speak upload status failed: {e}")
                from vani.services.image_chat import analyze_image
                ok, reply = analyze_image(filename, data, user_prompt=user_prompt, browser_mime=browser_mime)
                try:
                    from vani.reasoning import speak_to_user_from_thread
                    speak_to_user_from_thread(reply, limit=int(os.getenv("VANI_IMAGE_SPEECH_MAX_CHARS", "1400")))
                except Exception as e:
                    log.warning(f"[image] speak final reply failed: {e}")
                self._send_json(200 if ok else 400, {"reply": reply, "filename": filename})
            except Exception as e:
                log.exception("[image] analyze_image failed")
                self._send_json(500, {"reply": f"❌ Image review error: {e}"})

        elif self.path == "/clear_document":
            try:
                from vani.memory.human_memory import clear_active_document
                clear_active_document()
                self._send_json(200, {"ok": True, "reply": "Document memory clear ho gaya."})
            except Exception as e:
                self._send_json(500, {"reply": f"❌ Clear error: {e}"})

        elif self.path == "/enroll_voice":
            try:
                import numpy as np
                from vani.services.voice_enrollment import enroll_from_audio
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length == 0:
                    self._send_json(400, {"ok": False, "reason": "no_audio"})
                    return
                body = self.rfile.read(content_length)
                wav = np.frombuffer(body, dtype=np.float32)
                result = enroll_from_audio([wav], sr=16000)
                self._send_json(200, result)
            except Exception as exc:
                log.warning("enroll_voice error: %s", exc)
                self._send_json(500, {"ok": False, "reason": str(exc)})

        elif self.path == "/delete_enrollment":
            try:
                from vani.services.voice_enrollment import delete_voiceprint
                ok = delete_voiceprint()
                self._send_json(200, {"ok": ok})
            except Exception as exc:
                self._send_json(500, {"ok": False, "reason": str(exc)})

        else:
            self.send_response(404); self.end_headers()

    def do_GET(self):
        try:
            if self.path == "/ws":
                upgrade = self.headers.get("Upgrade", "").lower()
                if upgrade == "websocket":
                    if _ws_handshake(self.connection, self.headers):
                        with _ws_clients_lock:
                            global _ws_client_counter
                            _ws_client_counter += 1
                            cid = _ws_client_counter
                        t = threading.Thread(
                            target=_ws_client_thread,
                            args=(self.connection, cid),
                            daemon=True,
                            name=f"ws-client-{cid}",
                        )
                        t.start()
                        self.connection = None
                        return
                self.send_response(400); self.end_headers()
                return

            elif self.path == "/state":
                body = json.dumps(state).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            elif self.path == "/document_status":
                try:
                    from vani.memory.human_memory import get_active_document_status
                    status = get_active_document_status()
                except Exception:
                    status = {"present": False}
                self._send_json(200, status)

            elif self.path == "/enrollment_status":
                try:
                    from vani.services.voice_enrollment import get_enrollment_status
                    self._send_json(200, get_enrollment_status())
                except Exception as exc:
                    self._send_json(200, {"enrolled": False, "error": str(exc)})

            elif self.path == "/ui":
                html_file = HTML_PATH
                if PATCHED_HTML_PATH.exists() and PATCHED_HTML_PATH.stat().st_mtime >= HTML_PATH.stat().st_mtime:
                    html_file = PATCHED_HTML_PATH
                body = html_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            else:
                ALLOWED_ASSETS = {
                    "/vani_idle.png":              (ASSETS_ROOT / "images" / "vani_idle.png",                  "image/png"),
                    "/opening.mp4":                (ASSETS_ROOT / "video"  / "opening.mp4",                   "video/mp4"),
                    "/opening2.mp4":               (ASSETS_ROOT / "video"  / "opening2.mp4",                  "video/mp4"),
                    "/listening_optimized.mp4":    (ASSETS_ROOT / "video"  / "listening_optimized.mp4",       "video/mp4"),
                    "/listening.mp4":              (ASSETS_ROOT / "video"  / "listening.mp4",                  "video/mp4"),
                    "/listening.gif":              (ASSETS_ROOT / "images" / "listening.gif",                  "image/gif"),
                    "/talking1.mp4":               (ASSETS_ROOT / "video"  / "talking1.mp4",                   "video/mp4"),
                    "/taking1.mp4":                (ASSETS_ROOT / "video"  / "taking1.mp4",                    "video/mp4"),
                    "/vani_avatar.mp4":            (ASSETS_ROOT / "video"  / "vani_avatar.mp4",                "video/mp4"),
                    "/livekit-client.umd.min.js":  (ASSETS_ROOT / "vendor" / "livekit-client.umd.min.js",     "application/javascript"),
                }
                if self.path not in ALLOWED_ASSETS:
                    self.send_response(404); self.end_headers(); return
                asset_file, mime_type = ALLOWED_ASSETS[self.path]
                if not asset_file.exists():
                    self.send_response(404); self.end_headers(); return
                file_size    = asset_file.stat().st_size
                range_header = self.headers.get("Range")
                with open(asset_file, "rb") as f:
                    if range_header and mime_type.startswith("video/"):
                        try:
                            byte_range = range_header.strip().replace("bytes=", "")
                            byte_range = byte_range.split(",")[0].strip()
                            parts = byte_range.split("-", 1)
                            start_str = parts[0].strip()
                            end_str   = parts[1].strip() if len(parts) > 1 else ""
                            start  = int(start_str) if start_str else 0
                            end    = int(end_str) if end_str else min(start + 1024 * 1024, file_size - 1)
                            start = max(0, min(start, file_size - 1))
                            end   = max(start, min(end, file_size - 1))
                        except (ValueError, IndexError):
                            start, end = 0, file_size - 1
                        length = end - start + 1
                        f.seek(start)
                        body = f.read(length)
                        self.send_response(206)
                        self.send_header("Content-Type",   mime_type)
                        self.send_header("Content-Range",  f"bytes {start}-{end}/{file_size}")
                        self.send_header("Content-Length", str(length))
                        self.send_header("Accept-Ranges",  "bytes")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(body)
                    else:
                        self.send_response(200)
                        self.send_header("Content-Type",   mime_type)
                        self.send_header("Content-Length", str(file_size))
                        self.send_header("Accept-Ranges",  "bytes")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        while chunk := f.read(64 * 1024):
                            self.wfile.write(chunk)
        except BrokenPipeError:
            pass


def _run_state_server():
    server = ThreadingHTTPServer(("127.0.0.1", 5500), _Handler)
    server.daemon_threads = True
    server.serve_forever()


# ── P3: FastAPI server for Tauri desktop app (port 8765) ──────────────────────
# The Tauri Rust layer talks to Python via HTTP on port 8765.
# All endpoints are non-blocking and safe to call from a Rust async task.

def _start_tauri_api_server():
    """Start the FastAPI/uvicorn server for Tauri IPC on port 8765.
    Runs in a background daemon thread so it never blocks the main loop."""
    try:
        import uvicorn
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware

        tauri_api = FastAPI(title="Vani Tauri API", version="0.1.0")
        tauri_api.add_middleware(
            CORSMiddleware,
            allow_origins=["tauri://localhost", "http://localhost:1420"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # ── /query — main chat endpoint ───────────────────────────────────────
        @tauri_api.post("/query")
        async def tauri_query(body: dict):
            """Route a text query through Vani's existing reasoning stack."""
            text = body.get("text", "").strip()
            if not text:
                return {"text": "", "model_used": "", "duration_ms": 0, "tool_calls": []}
            import time as _time
            t0 = _time.monotonic()
            try:
                from vani.services.text_chat import handle_text_command
                reply = await handle_text_command(text)
            except Exception as e:
                log.warning(f"[tauri_api] /query error: {e}")
                reply = f"Error: {e}"
            duration_ms = int((_time.monotonic() - t0) * 1000)
            return {
                "text": reply,
                "model_used": os.getenv("PREFERRED_MODEL", "unknown"),
                "duration_ms": duration_ms,
                "tool_calls": [],
            }

        # ── /memory/stats — memory summary ───────────────────────────────────
        @tauri_api.get("/memory/stats")
        async def tauri_memory_stats():
            """Return semantic memory + working memory counts."""
            try:
                from vani.memory.working_memory import WorkingMemory
                wm = WorkingMemory()
                working_entries = len(wm.get_all()) if hasattr(wm, "get_all") else 0
            except Exception:
                working_entries = 0
            try:
                from vani.vani_legacy.db import get_memory_count
                semantic_memories = get_memory_count()
            except Exception:
                semantic_memories = 0
            return {
                "semantic_memories": semantic_memories,
                "working_entries": working_entries,
                "has_permanent": semantic_memories > 0,
            }

        # ── /memory/search — semantic search ─────────────────────────────────
        @tauri_api.post("/memory/search")
        async def tauri_memory_search(body: dict):
            """Search semantic memory and return ranked results."""
            query = body.get("query", "").strip()
            top_k = int(body.get("top_k", 10))
            if not query:
                return []
            try:
                from vani.vani_legacy.memory_semantic import SemanticMemory
                sem = SemanticMemory()
                results = await sem.search(query, top_k=top_k)
                return results
            except Exception as e:
                log.warning(f"[tauri_api] /memory/search error: {e}")
                return []

        # ── /tools/history — tool audit log ──────────────────────────────────
        @tauri_api.get("/tools/history")
        async def tauri_tool_history(tool: str = None):
            """Return recent tool calls from the audit log."""
            try:
                from vani.vani_legacy.db import get_tool_audit_log
                rows = get_tool_audit_log(tool_name=tool, limit=50)
                return rows
            except Exception as e:
                log.warning(f"[tauri_api] /tools/history error: {e}")
                return []

        # ── /models/status — model router health ─────────────────────────────
        @tauri_api.get("/models/status")
        async def tauri_model_status():
            """Return health status of all models in the fallback chain."""
            try:
                from vani.vani_legacy.model_router import model_router as _mr
                return _mr.status()
            except Exception as e:
                log.warning(f"[tauri_api] /models/status error: {e}")
                # Fallback: probe Ollama directly
                models = {}
                try:
                    import requests as _req
                    r = _req.get("http://127.0.0.1:11434/api/tags", timeout=2)
                    if r.ok:
                        for m in r.json().get("models", []):
                            name = m.get("name", "").split(":")[0]
                            models[name] = {"healthy": True, "provider": "ollama", "tier": "medium"}
                except Exception:
                    pass
                return models

        # ── /state — mirror existing state dict ──────────────────────────────
        @tauri_api.get("/state")
        async def tauri_get_state():
            return state

        def _run():
            config = uvicorn.Config(
                tauri_api,
                host="127.0.0.1",
                port=8765,
                loop="asyncio",
                log_level="warning",
                access_log=False,
            )
            server = uvicorn.Server(config)
            import asyncio as _asyncio
            _loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(_loop)
            _loop.run_until_complete(server.serve())

        t = threading.Thread(target=_run, daemon=True, name="tauri-api")
        t.start()
        log.info("[tauri_api] FastAPI server started on http://127.0.0.1:8765")
    except ImportError as e:
        log.warning(
            f"[tauri_api] fastapi/uvicorn not installed — Tauri IPC disabled: {e}\n"
            "  Install with: pip install fastapi uvicorn"
        )
    except Exception as e:
        log.warning(f"[tauri_api] Failed to start Tauri API server (non-fatal): {e}")
# ──────────────────────────────────────────────────────────────────────────────


def _generate_token(room_name: str, identity: str) -> str:
    try:
        from livekit.api import AccessToken, VideoGrants
        key    = os.getenv("LIVEKIT_API_KEY", "")
        secret = os.getenv("LIVEKIT_API_SECRET", "")
        if not key or not secret:
            log.error("[livekit] API key/secret missing"); return ""
        return (
            AccessToken(key, secret)
            .with_identity(identity)
            .with_name("Vani User")
            .with_grants(VideoGrants(room_join=True, room=room_name,
                                     can_publish=True, can_subscribe=True))
            .to_jwt()
        )
    except Exception as e:
        log.error(f"[livekit] Token error: {e}"); return ""


async def _setup_room(room_name: str):
    try:
        from livekit.api import LiveKitAPI, CreateRoomRequest, CreateAgentDispatchRequest
        lk = LiveKitAPI(
            os.getenv("LIVEKIT_URL", ""),
            os.getenv("LIVEKIT_API_KEY", ""),
            os.getenv("LIVEKIT_API_SECRET", ""),
        )
        try:
            await lk.room.create_room(CreateRoomRequest(name=room_name))
            log.info(f"[livekit] Room '{room_name}' created OK")
            await lk.agent_dispatch.create_dispatch(
                CreateAgentDispatchRequest(agent_name="vani", room=room_name)
            )
            log.info(f"[livekit] Agent dispatched OK")
        finally:
            await lk.aclose()
    except Exception as e:
        log.error(f"[livekit] Room setup error: {e}")


def _patch_html(lk_url: str = "", token: str = "", voice_backend: str = "none") -> Path:
    import html as _html
    html = HTML_PATH.read_text(encoding="utf-8")
    livekit_meta = ""
    if voice_backend == "livekit" and lk_url and token:
        safe_url   = _html.escape(lk_url,   quote=True)
        safe_token = _html.escape(token,     quote=True)
        livekit_meta = (
            f'<meta name="lk-url"   content="{safe_url}">\n'
            f'    <meta name="lk-token" content="{safe_token}">\n'
        )
    meta = (livekit_meta +
            f'    <meta name="voice-backend" content="{voice_backend}">\n'
            f'    <meta name="state-url" content="http://127.0.0.1:5500/state">\n'
            f'    <meta name="ui-low-power" content="{os.getenv("VANI_LOW_POWER_UI", "0")}">\n'
            f'    <meta name="ui-fast-start" content="{os.getenv("VANI_FAST_START_UI", "1")}">\n')
    html = html.replace("<head>", f"<head>\n    {meta}", 1)
    out  = PATCHED_HTML_PATH
    out.write_text(html, encoding="utf-8")
    return out


def _open_ui(html_path: Path):
    url = "http://127.0.0.1:5500/ui"
    # ── Phase 9: Use platform adapter when available ───────────────────────────
    if _PLATFORM_ADAPTER_OK:
        try:
            _platform_adapter.open_app_browser(url)
            log.info(f"[ui] Opened via platform adapter ({_platform_adapter.name})")
            return
        except Exception as _e:
            log.warning(f"[ui] Platform adapter open_app_browser failed: {_e}")
    # ── Legacy fallback (original Mac/Win/else logic) ──────────────────────────
    if IS_MAC:
        for chrome in [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ]:
            if os.path.exists(chrome):
                subprocess.Popen([chrome, f"--app={url}",
                    "--window-size=420,680", "--window-position=50,50",
                    "--disable-extensions", "--no-first-run", "--no-default-browser-check"])
                log.info("[ui] Opened with Chrome app mode OK")
                return
        subprocess.Popen(["open", "-a", "Safari", "http://127.0.0.1:5500/ui"])
    elif IS_WIN:
        for chrome in [
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]:
            if os.path.exists(chrome):
                subprocess.Popen([chrome, f"--app={url}", "--window-size=420,680"])
                return
        webbrowser.open(url)
    else:
        webbrowser.open(url)


# ── Module-level entrypoint ───────────────────────────────────────────────────

async def entrypoint(ctx):
    from livekit.agents import AgentSession, Agent
    # ── FIX 6: RoomInputOptions import guarded — set to None if unavailable ───
    # Original code imported this at entrypoint top and used it unchecked below.
    # If the import fails, the later RoomInputOptions(noise_cancellation=nc) call
    # would raise UnboundLocalError. Now None-checked before use.
    try:
        from livekit.agents import RoomInputOptions
    except ImportError:
        RoomInputOptions = None

    from livekit.plugins import google
    try:
        from livekit.plugins import noise_cancellation
    except ImportError:
        noise_cancellation = None

    from vani.prompts import get_realtime_prompt
    from vani.reasoning import get_thinking_capability_tool

    log.info(f"[vani] room={ctx.room.name} session starting")
    state["status"] = "Connecting..."

    MEMORY_ENABLED = False
    try:
        from vani.memory.memory_loop import MemoryExtractor
        MEMORY_ENABLED = True
    except ImportError:
        pass

    import time as _time
    _last_utt: dict = {"text": "", "ts": 0.0, "responded": False}

    def _normalise(text: str) -> str:
        """Lowercase, strip, collapse multiple spaces."""
        import re
        return re.sub(r"\s+", " ", (text or "").strip().lower())

    def _token_overlap_ratio(a: str, b: str) -> float:
        """Fraction of tokens in the shorter string that appear in the longer."""
        ta, tb = a.split(), b.split()
        if not ta or not tb:
            return 0.0
        shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        common = sum(1 for w in shorter if w in longer)
        return common / len(shorter)

    def _is_repeated_content(new_text: str, old_text: str) -> bool:
        """
        True if new_text is clearly just old_text repeated / extended.
        Catches:
          - "hlo" → "hlo hlo"          (old is prefix of new)
          - "hello" → "hello hello"    (repetition pattern)
          - near-identical short phrases
        """
        if not old_text:
            return False
        nt, ot = _normalise(new_text), _normalise(old_text)
        # Exact match
        if nt == ot:
            return True
        nt_words, ot_words = nt.split(), ot.split()
        # "hlo hlo" when old was "hlo" — new is just old repeated twice
        if len(nt_words) <= 6 and len(nt_words) >= 2:
            half = len(nt_words) // 2
            # check first-half == second-half (repetition)
            if nt_words[:half] == nt_words[half:half*2]:
                return True
        # new starts with old (old is prefix — interim→final extension)
        if nt.startswith(ot) and len(ot_words) <= 4:
            return True
        # very high token overlap on short utterances
        if len(nt_words) <= 5 and _token_overlap_ratio(nt, ot) >= 0.85:
            return True
        return False

    def _is_duplicate_utterance(text: str, window: float = 4.0) -> bool:
        """
        Returns True if this transcript should be DROPPED:
          1. It is a final-ish repeat of what was just processed.
          2. It contains only repeated/stuttered words (e.g. "hlo hlo hlo").
        Also updates the last-utterance cache on ACCEPT.
        """
        now = _time.monotonic()
        t = _normalise(text)
        age = now - _last_utt["ts"]

        if age < window and _is_repeated_content(t, _last_utt["text"]):
            log.info("[dedup] Dropped repeated/extended utterance: %r (prev=%r age=%.1fs)",
                     t, _last_utt["text"], age)
            return True

        # Accept — update cache
        _last_utt["text"] = t
        _last_utt["ts"] = now
        _last_utt["responded"] = False
        return False

    class Assistant(Agent):
        def __init__(self):
            realtime_prompt = (
                get_realtime_prompt()
                + "\n\nVOICE DELIVERY:\n"
                + "- Keep normal replies short and natural in Hinglish.\n"
                + "- If Rudra explicitly asks for detail, explanation, teaching, story, or step-by-step guidance, speak longer.\n"
                + "- Complete answers do — beech mein mat ruko. Agar lamba hai toh pehle summary bol phir details.\n"
                + "- Keep speech smooth: avoid markdown, code blocks, and repeated filler while speaking.\n"
            )
            super().__init__(
                instructions=realtime_prompt,
                llm=google.beta.realtime.RealtimeModel(
                    model=REALTIME_MODEL,
                    voice="Aoede",
                    temperature=float(os.getenv("VANI_REALTIME_TEMPERATURE", "0.65")),
                    instructions=realtime_prompt,
                    modalities=["AUDIO"],
                ),
                tools=[get_thinking_capability_tool()],
            )

    class FallbackAssistant(Agent):
        def __init__(self):
            realtime_prompt = (
                get_realtime_prompt()
                + "\n\nVOICE DELIVERY: Keep normal replies brief. If Rudra asks for detail, speak longer in small, clear sections."
            )
            super().__init__(
                instructions=realtime_prompt,
                llm=google.LLM(model="gemini-1.5-flash"),
                tools=[get_thinking_capability_tool()],
            )

    await ctx.connect()
    if os.getenv("VANI_PREWARM_OLLAMA", "0") == "1":
        asyncio.create_task(_prewarm_ollama())

    vad = None
    if os.getenv("VANI_USE_SILERO", "0") == "1":
        try:
            from livekit.plugins import silero
            vad = silero.VAD.load(
                min_speech_duration=float(os.getenv("VANI_VAD_MIN_SPEECH", "0.04")),
                min_silence_duration=float(os.getenv("VANI_VAD_MIN_SILENCE", "0.08")),
                prefix_padding_duration=float(os.getenv("VANI_VAD_PREFIX_PADDING", "0.08")),
                activation_threshold=float(os.getenv("VANI_VAD_THRESHOLD", "0.45")),
                sample_rate=16000,
            )
        except Exception as e:
            vad = None
            log.warning(f"[vad] Silero VAD load failed: {e}")

    max_retries = 3
    retry_count = 0
    session = None
    connected = False

    from concurrent.futures import ThreadPoolExecutor
    _audio_executor = ThreadPoolExecutor(max_workers=1)

    def _run_audio(fn):
        if AUDIO_PRIORITY:
            try:
                _audio_executor.submit(fn)
            except RuntimeError:
                pass

    def _register_session_events(sess):
        @sess.on("agent_started_speaking")
        def _on_speak(*_):
            _patched_state_update(dict(speaking=True, listening=False, processing=False, status="Speaking..."))
            _run_audio(vani_deactivated)

        @sess.on("agent_stopped_speaking")
        def _on_stop(*_):
            _patched_state_update(dict(speaking=False, listening=True, processing=False, status="Listening..."))
            _run_audio(vani_activated)

        @sess.on("user_started_speaking")
        def _on_user(*_):
            _patched_state_update(dict(speaking=False, listening=True, processing=False, status="Listening..."))

        @sess.on("user_stopped_speaking")
        def _on_stop2(*_):
            _patched_state_update(dict(speaking=False, listening=False, processing=True, status="Thinking..."))

        @sess.on("user_input_transcribed")
        def _on_transcript(event, *_):
            try:
                text = getattr(event, "transcript", None) or getattr(event, "text", None) or ""
                if not text:
                    return

                # ── Only act on FINAL transcripts ────────────────────────────
                # LiveKit fires this event for both interim and final results.
                # Interim transcripts (is_final=False) are used only for UI display,
                # NOT for triggering commands — otherwise every partial result
                # ("hlo", then "hlo hlo") fires a separate response, making
                # Vani feel buggy and chatty.
                is_final = getattr(event, "is_final", None)
                if is_final is False:
                    # Strictly interim — skip processing entirely
                    return
                # is_final is True or None (attribute absent = treat as final)

                # ── Security lockdown intercept ───────────────────────────────
                if SECURITY_ENABLED and is_locked_down():
                    log.warning("[SECURITY] Lockdown active — intercepting transcript: %r", text)
                    try:
                        asyncio.create_task(sess.interrupt())
                    except Exception:
                        pass
                    response = get_lockdown_response(text)
                    if response:
                        asyncio.create_task(_say_lockdown(sess, response))
                    return

                # ── Dedup / repeated-word filter ──────────────────────────────
                if _is_duplicate_utterance(text):
                    try:
                        asyncio.create_task(sess.interrupt())
                    except Exception:
                        pass
            except Exception:
                pass

        async def _say_lockdown(session, text: str):
            try:
                await asyncio.sleep(0.15)
                from vani.reasoning.worker import say_to_user
                await say_to_user(text)
            except Exception as exc:
                log.warning("[SECURITY] _say_lockdown failed: %s", exc)

    def _new_agent_session():
        try:
            from livekit.agents import TurnHandlingOptions
            turn_handling = TurnHandlingOptions(
                allow_interruptions=True,
                min_endpointing_delay=float(os.getenv("VANI_ENDPOINT_MIN_DELAY", "0.12")),
                max_endpointing_delay=float(os.getenv("VANI_ENDPOINT_MAX_DELAY", "0.45")),
            )
            session_kwargs = {"turn_handling": turn_handling}
        except ImportError:
            session_kwargs = {
                "allow_interruptions": True,
                "min_endpointing_delay": float(os.getenv("VANI_ENDPOINT_MIN_DELAY", "0.12")),
                "max_endpointing_delay": float(os.getenv("VANI_ENDPOINT_MAX_DELAY", "0.45")),
            }
        if vad:
            session_kwargs["vad"] = vad
        return AgentSession(**session_kwargs)

    while retry_count < max_retries:
        try:
            session = _new_agent_session()
            _register_session_events(session)

            # ── FIX 6 (continued): RoomInputOptions None-checked before use ───
            # Only build room_input when BOTH RoomInputOptions imported OK and
            # noise_cancellation loaded OK. Otherwise leave as None (no NC).
            room_input = None
            if (
                os.getenv("VANI_NOISE_CANCELLATION", "0") == "1"
                and RoomInputOptions is not None
                and noise_cancellation is not None
            ):
                try:
                    nc = noise_cancellation.BVC()
                    room_input = RoomInputOptions(noise_cancellation=nc)
                except Exception as e:
                    log.warning(f"[nc] Noise cancellation setup failed: {e}")
                    room_input = None

            await session.start(
                room=ctx.room,
                agent=Assistant(),
                **({"room_input_options": room_input} if room_input else {}),
            )
            connected = True
            log.info("[vani] realtime session started OK")
            try:
                from vani.reasoning import register_session
                register_session(session)
            except Exception as e:
                log.error(f"[vani] Failed to register realtime session: {e}")
            break
        except Exception as e:
            retry_count += 1
            if retry_count < max_retries:
                wait_time = 2 ** retry_count
                log.warning(f"[vani] Realtime attempt {retry_count} failed: {e}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                log.error(f"[vani] Realtime failed after {max_retries} attempts: {e}")

    if not connected:
        log.info("[vani] Switching to standard Gemini fallback...")
        try:
            session = _new_agent_session()
            _register_session_events(session)
            await session.start(
                room=ctx.room,
                agent=FallbackAssistant(),
            )
            log.info("[vani] fallback session started OK")
            try:
                from vani.reasoning import register_session
                register_session(session)
            except Exception as e:
                log.error(f"[vani] Failed to register fallback session: {e}")
        except Exception as e:
            log.error(f"[vani] Fallback failed: {e}")
            state["status"] = f"Error: {e}"
            return

    _patched_state_update(dict(connected=True, status="Ready - say something!"))
    _patched_state_update(dict(speaking=False, listening=True, processing=False))
    _notify_mac("Vani ready", "Voice conversation ready hai.")
    try:
        from vani.reasoning import say_to_user
        asyncio.create_task(say_to_user("Vani ready hai. Ab bol sakte ho.", limit=None))
        if os.getenv("VANI_STARTUP_MEMORY_BRIEF", "1") == "1":
            from vani.memory.working_memory import get_startup_memory_brief
            brief = get_startup_memory_brief()
            if brief:
                asyncio.create_task(say_to_user(brief, limit=320))
    except Exception as e:
        log.warning(f"[vani] ready speech failed: {e}")

    shutdown_event = asyncio.Event()

    async def _on_shutdown(reason: str = ""):
        log.info(f"[vani] shutdown: {reason}")
        _run_audio(vani_deactivated)
        _audio_executor.shutdown(wait=False)
        shutdown_event.set()

    ctx.add_shutdown_callback(_on_shutdown)

    if MEMORY_ENABLED:
        try:
            def _live_msgs():
                if hasattr(session, "history") and hasattr(session.history, "items"):
                    return list(session.history.items)
                return []

            async def _mem_session_proxy():
                from vani.memory.memory_store import ConversationMemory
                import time as _time
                memory = ConversationMemory("Rudra_Vani")
                saved_count = 0
                try:
                    while True:
                        await asyncio.sleep(10)
                        msgs = _live_msgs()
                        if len(msgs) <= saved_count: continue
                        new_msgs = msgs[saved_count:]
                        payload = {"messages": [str(m) for m in new_msgs], "timestamp": _time.time()}
                        memory.save_conversation(payload)
                        saved_count = len(msgs)
                except asyncio.CancelledError: raise

            mem_task = asyncio.create_task(_mem_session_proxy())
            await shutdown_event.wait()
            mem_task.cancel()
        except Exception as e:
            await shutdown_event.wait()
    else:
        await shutdown_event.wait()

    _patched_state_update(dict(connected=False, speaking=False, listening=False, processing=False, status="Disconnected"))
    log.info("[vani] session ended")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-agent", action="store_true")
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    voice_backend = os.getenv("VANI_VOICE_BACKEND", "livekit").strip().lower()

    if args.worker:
        if voice_backend != "livekit":
            print("Worker mode requires VANI_VOICE_BACKEND=livekit.")
            return
        from livekit import agents
        sys.argv = [sys.argv[0], "start"]
        agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name="vani"))
        return

    print("======================================")
    print("          Vani - Fixed Launch         ")
    print("======================================")

    try:
        result = subprocess.run(["lsof", "-ti:8081"], capture_output=True, text=True)
        for pid in result.stdout.strip().split():
            if pid.strip(): os.kill(int(pid), signal.SIGKILL)
    except Exception: pass

    threading.Thread(target=_run_state_server, daemon=True).start()

    # ── P3: Start Tauri API server (port 8765) ────────────────────────────────
    _start_tauri_api_server()
    # ──────────────────────────────────────────────────────────────────────────

    # ── Phase 7: Start background workers ─────────────────────────────────────
    # Reminder checker, maintenance, and self-improvement run as daemon threads.
    # If workers fail to start, VANI continues normally — fully non-fatal.
    try:
        from vani.workers import start_background_workers
        start_background_workers()
        log.info("[workers] Background workers started")
    except Exception as _worker_err:
        log.warning(f"[workers] Worker startup failed (non-fatal): {_worker_err}")
    # ──────────────────────────────────────────────────────────────────────────
    if voice_backend == "livekit":
        _patched_state_update(dict(text_ready=True, status="Text/image ready - voice connecting..."))
    else:
        _patched_state_update(dict(
            text_ready=True,
            connected=False,
            status=f"Text/image ready - voice backend: {voice_backend}",
        ))

    lk_url    = os.getenv("LIVEKIT_URL", "")
    room_name = f"vani-{uuid.uuid4().hex[:8]}"
    html_path = _patch_html(voice_backend=voice_backend)

    if voice_backend == "livekit" and lk_url:
        token = _generate_token(room_name, "vani-user")
        if token:
            html_path = _patch_html(lk_url, token, voice_backend=voice_backend)
            def _bg_room_setup():
                try:
                    _loop = asyncio.new_event_loop()
                    _loop.run_until_complete(_setup_room(room_name))
                    _loop.close()
                except Exception: pass
            threading.Thread(target=_bg_room_setup, daemon=True).start()

    _open_ui(html_path)
    if voice_backend == "livekit":
        _notify_mac("Vani starting", "Text aur image chat ready hai. Voice connect ho rahi hai.")
    else:
        _notify_mac("Vani starting", "Text aur image chat ready hai.")

    if not args.no_agent and voice_backend == "livekit":
        from livekit import agents
        sys.argv = [sys.argv[0], "start"]
        agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name="vani"))
    else:
        try:
            import time
            while True: time.sleep(1)
        except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()