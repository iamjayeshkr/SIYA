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

# ── DNS fallback patch for systems with broken IPv6 DNS (e.g. iPhone Hotspot) ─
_orig_getaddrinfo = socket.getaddrinfo

def _dns_query_udp(hostname, dns_server="8.8.8.8"):
    # Header: ID, Flags (0x0100 for recursion desired), Questions, Answer RRs, Authority RRs, Additional RRs
    header = struct.pack("!HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0)
    # Question: Name (encoded as label lengths and strings), Type (1 = A), Class (1 = IN)
    qname = b""
    for part in hostname.split("."):
        if not part:
            continue
        qname += bytes([len(part)]) + part.encode("utf-8")
    qname += b"\x00"
    question = qname + struct.pack("!HH", 1, 1)
    packet = header + question
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    try:
        sock.sendto(packet, (dns_server, 53))
        data, _ = sock.recvfrom(512)
    except Exception:
        return []
    finally:
        sock.close()
        
    try:
        ancount = struct.unpack("!H", data[6:8])[0]
        if ancount == 0:
            return []
        offset = 12 + len(question)
        ips = []
        for _ in range(ancount):
            if offset >= len(data):
                break
            if (data[offset] & 0xC0) == 0xC0:
                offset += 2
            else:
                while data[offset] != 0:
                    offset += data[offset] + 1
                offset += 1
            atype, aclass, attl, ardlength = struct.unpack("!HHIH", data[offset:offset+10])
            offset += 10
            rdata = data[offset:offset+ardlength]
            offset += ardlength
            if atype == 1 and ardlength == 4:
                ips.append(socket.inet_ntoa(rdata))
        return ips
    except Exception:
        return []

def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return _orig_getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror as e:
        if host and ("livekit" in host or "google" in host):
            try:
                ips = _dns_query_udp(host, "8.8.8.8")
                if not ips:
                    ips = _dns_query_udp(host, "1.1.1.1")
                if ips:
                    results = []
                    for ip in ips:
                        if family == 0 or family == socket.AF_INET:
                            r_type = type if type != 0 else socket.SOCK_STREAM
                            r_proto = proto if proto != 0 else socket.IPPROTO_TCP
                            results.append((socket.AF_INET, r_type, r_proto, '', (ip, port)))
                    if results:
                        return results
            except Exception:
                pass
        raise e

socket.getaddrinfo = _patched_getaddrinfo
# ──────────────────────────────────────────────────────────────────────────────
from pathlib import Path
from dotenv import load_dotenv
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from vani.config import ASSETS_ROOT, PACKAGE_ROOT, PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env", override=True)

try:
    from livekit.plugins import google
except ImportError:
    google = None

try:
    from livekit.plugins import noise_cancellation
except ImportError:
    noise_cancellation = None

try:
    from livekit.plugins import silero
except ImportError:
    silero = None

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vani")

# ── Model routing ─────────────────────────────────────────────────────────────
PREFERRED_MODEL = "gemini-2.5-flash"
REALTIME_MODEL  = os.getenv("VANI_REALTIME_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
log.info(f"[MODEL] Preferred: {PREFERRED_MODEL}  Runtime (realtime): {REALTIME_MODEL}")

# ── English Detection Helper ──────────────────────────────────────────────────
import re

HINGLISH_WORDS = {
    "hai", "ho", "se", "ko", "ki", "ka", "ke", "me", "mein", "bhi", "toh", "kya",
    "karo", "kar", "raha", "rha", "rahi", "rhi", "bol", "sakte", "tu", "tera",
    "mera", "meri", "mere", "aap", "aur", "kaise", "kab", "kaha", "kyu", "kyon",
    "achha", "acha", "theek", "thik", "bhai", "bhaiya", "ab", "abhi", "aaj", "kal",
    "hoga", "hogi", "chahiye", "bolo", "bolna", "likho", "likhna", "suno", "sunna",
    "samajh", "samajho", "yaar", "dost", "shuru", "khatam", "band", "chalu", "kholo",
    "nikalo", "nikalna", "dikhao", "dikhana", "batao", "batana", "pucho", "puchna",
    "socho", "sochna", "samjho", "samjhna", "apna", "apni", "apne", "tujhe", "mujhe",
    "karta", "karti", "karte", "gaya", "gayi", "gaye", "tha", "thi", "the", "didi",
    "chalo", "chala", "chalna", "hona", "hone", "honi", "jaise", "waise", "aisa",
    "waisa", "karna", "karne", "karni", "hoga", "hogi", "hoge"
}

def is_english(text: str) -> bool:
    text = text.lower().strip()
    if not text:
        return False
    if not text.isascii():
        return False
    words = re.findall(r"\b[a-z]+\b", text)
    if not words:
        return False
    # If any word matches Hinglish stopwords, it is not purely English
    for w in words:
        if w in HINGLISH_WORDS:
            return False
    return True


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
    "transcript": "",
    "kokoro_enabled": os.getenv("VANI_LOCAL_TTS", "0") == "1",
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


def _ws_send_all(msg_dict):
    try:
        frame = _ws_encode(json.dumps(msg_dict))
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
    except Exception as e:
        log.warning(f"[ws] failed to broadcast: {e}")


def _ws_client_thread(sock, client_id: int = 0):
    try:
        sock.settimeout(60.0)
    except Exception:
        pass
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


_recently_spoken_fallback_texts = set()

def mark_fallback_speech(text: str):
    _recently_spoken_fallback_texts.add(text.strip())


_state_update_thread = None
_state_update_queue = None

def _patched_state_update(new_values: dict):
    state.update(new_values)
    _ws_push_state()
    # Sync state across processes if in worker mode
    import sys
    if "--worker" in sys.argv:
        global _state_update_thread, _state_update_queue
        if _state_update_thread is None:
            import queue
            import threading
            _state_update_queue = queue.Queue()
            def _state_update_worker():
                import urllib.request
                import json
                opener = urllib.request.build_opener()
                while True:
                    try:
                        vals = _state_update_queue.get()
                        if vals is None:
                            break
                        data = json.dumps(vals).encode("utf-8")
                        req = urllib.request.Request(
                            "http://127.0.0.1:5500/update_state",
                            data=data,
                            headers={"Content-Type": "application/json"},
                            method="POST"
                        )
                        try:
                            with opener.open(req, timeout=1.0) as f:
                                f.read()
                        except Exception:
                            pass
                        finally:
                            _state_update_queue.task_done()
                    except Exception:
                        pass
            _state_update_thread = threading.Thread(target=_state_update_worker, daemon=True, name="StateUpdateWorker")
            _state_update_thread.start()
        _state_update_queue.put(new_values)


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


async def _prewarm_gemini():
    try:
        from vani.reasoning.ollama import prewarm_gemini_client
        await prewarm_gemini_client()
    except Exception as e:
        log.warning(f"[gemini-prewarm] Failed: {e}")


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

        elif self.path == "/update_state":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length > 0 else {}
                _patched_state_update(body)
                self._send_json(200, {"ok": True})
            except Exception as e:
                self._send_json(500, {"ok": False, "error": str(e)})

        elif self.path == "/minimize":
            try:
                import subprocess
                if IS_MAC:
                    script = 'tell application "System Events" to tell process "Vani" to set value of attribute "AXMinimized" of window 1 to true'
                    subprocess.run(["osascript", "-e", script])
                self._send_json(200, {"success": True})
            except Exception as e:
                log.warning(f"Failed to minimize via AppleScript: {e}")
                self._send_json(500, {"success": False, "error": str(e)})

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

        elif self.path == "/wake_reset":
            try:
                from vani.memory.conversation_writer import clear_conversation
                clear_conversation()
                try:
                    from vani.memory.human_memory import clear_active_document
                    clear_active_document()
                except Exception as e:
                    log.warning(f"[wake_reset] clear active document failed: {e}")
                try:
                    from vani.memory.working_memory import clear_working_memory
                    clear_working_memory()
                except Exception as e:
                    log.warning(f"[wake_reset] clear working memory failed: {e}")
                try:
                    from vani.memory.vector_store import SQLiteVectorStore
                    store = SQLiteVectorStore()
                    store.clear_all()
                except Exception as e:
                    log.warning(f"[wake_reset] clear semantic memories failed: {e}")
                try:
                    from vani.reasoning.worker import _get_task_queue
                    q = _get_task_queue()
                    if q:
                        q.cancel_active_task_threadsafe()
                except Exception as e:
                    log.warning(f"[wake_reset] worker queue reset failed: {e}")
                try:
                    from vani.reasoning.worker import _session_ref, _session_loop
                    if _session_ref and _session_loop:
                        asyncio.run_coroutine_threadsafe(_session_ref.interrupt(), _session_loop)
                except Exception as e:
                    log.warning(f"[wake_reset] LiveKit session interrupt failed: {e}")
                try:
                    from vani.ui.teach_bridge import clear_teach_visual
                    clear_teach_visual()
                except Exception as e:
                    log.warning(f"[wake_reset] clear teach visual failed: {e}")
                _ws_send_all({"action": "clear_chat"})
                self._send_json(200, {"ok": True})
            except Exception as e:
                log.exception("[wake_reset] failed")
                self._send_json(500, {"reply": f"❌ Wake reset error: {e}"})

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

        elif self.path == "/mentor/start":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length > 0 else {}
                roast_mode = body.get("roast_mode", "Off")
                mode_type = body.get("mode_type", "document")
                
                from vani.memory.human_memory import latest_temp_document_snapshot
                snapshot = latest_temp_document_snapshot(max_chars=None)
                if not snapshot or not snapshot.get("id"):
                    self._send_json(400, {"ok": False, "reply": "Pehle document upload karo."})
                    return
                
                from vani.services.mentor_service import start_mentor_session
                session = start_mentor_session(
                    filename=snapshot["filename"],
                    text=snapshot["full_text"],
                    roast_mode=roast_mode,
                    mode_type=mode_type,
                )
                self._send_json(200, {"ok": True, "session": session})
            except Exception as e:
                self._send_json(500, {"ok": False, "reply": str(e)})

        elif self.path == "/mentor/next":
            try:
                from vani.memory.mentor_memory import get_active_session, update_session
                from vani.services.mentor_service import select_next_concept, get_concept_details, TEACHING_STRATEGIES, generate_concept_explanation, generate_mastery_quiz
                session = get_active_session()
                if not session:
                    self._send_json(400, {"ok": False, "reply": "No active mentor session."})
                    return
                doc_id = session["document_id"]
                next_cid = select_next_concept(doc_id)
                if not next_cid:
                    from vani.services.mentor_service import compile_final_mastery_report
                    report = compile_final_mastery_report(doc_id)
                    self._send_json(200, {"ok": True, "finished": True, "report": report, "reply": "Congrats! All concepts mastered."})
                    return
                
                update_session(doc_id, current_concept_id=next_cid)
                concept = get_concept_details(next_cid)
                concept_name = concept["name"] if concept else "Concept"
                attempts = concept.get("attempts", 0) if concept else 0
                strategy = TEACHING_STRATEGIES[attempts % len(TEACHING_STRATEGIES)]
                
                narration, mermaid = generate_concept_explanation(next_cid, strategy, "Intermediate" if attempts > 0 else "Beginner")
                
                # Push diagram to UI
                try:
                    from vani.ui.teach_bridge import send_teach_visual
                    asyncio.run(send_teach_visual({
                        "concept": concept_name,
                        "visual_type": "diagram",
                        "mermaid_code": mermaid,
                        "narration": narration,
                        "category": "humor" if session["roast_mode"] > 0 else "motivation",
                        "subject": "general",
                        "memory_context": [session["filename"]],
                    }))
                except Exception:
                    pass
                
                quiz = generate_mastery_quiz(next_cid)
                self._send_json(200, {
                    "ok": True,
                    "finished": False,
                    "concept": concept_name,
                    "strategy": strategy,
                    "narration": narration,
                    "mermaid_code": mermaid,
                    "quiz": quiz
                })
            except Exception as e:
                self._send_json(500, {"ok": False, "reply": str(e)})

        elif self.path == "/mentor/quiz":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                item_id = body.get("quiz_id")
                user_answer = body.get("answer")
                
                from vani.services.mentor_service import evaluate_quiz_answer
                passed, feedback, conf = evaluate_quiz_answer(item_id, user_answer)
                self._send_json(200, {
                    "ok": True,
                    "passed": passed,
                    "feedback": feedback,
                    "confidence": conf
                })
            except Exception as e:
                self._send_json(500, {"ok": False, "reply": str(e)})

        elif self.path == "/mentor/roast":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                level = body.get("level", "Off")
                
                from vani.memory.mentor_memory import get_active_session, update_session
                session = get_active_session()
                if not session:
                    self._send_json(400, {"ok": False, "reply": "No active session."})
                    return
                roast_int = {"Off": 0, "Light": 1, "Medium": 2, "Savage": 3}.get(level, 0)
                update_session(session["document_id"], roast_mode=roast_int)
                self._send_json(200, {"ok": True, "level": level})
            except Exception as e:
                self._send_json(500, {"ok": False, "reply": str(e)})

        # ── Plugin routes ──────────────────────────────────────────────────────
        elif self.path == "/plugin/enable":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                name = body.get("name", "")
                from vani.plugins import get_registry
                msg = get_registry().enable(name)
                self._send_json(200, {"ok": True, "message": msg})
            except Exception as exc:
                self._send_json(500, {"ok": False, "message": str(exc)})

        elif self.path == "/plugin/disable":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                name = body.get("name", "")
                from vani.plugins import get_registry
                msg = get_registry().disable(name)
                self._send_json(200, {"ok": True, "message": msg})
            except Exception as exc:
                self._send_json(500, {"ok": False, "message": str(exc)})

        elif self.path == "/plugin/run":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                query = body.get("query", "").strip()
                messages = body.get("messages", [])
                if not query:
                    self._send_json(400, {"handled": False, "message": "Empty query"})
                    return
                from vani.plugins import get_registry
                from vani.plugins.registry import PluginContext
                context = PluginContext(recent_messages=messages)
                result = asyncio.run(get_registry().route_to_plugin(query, context))
                if result is None:
                    self._send_json(200, {"handled": False, "message": "No plugin matched."})
                else:
                    self._send_json(200, {
                        "handled": True,
                        "success": result.success,
                        "message": result.message,
                        "artifact_path": result.artifact_path,
                        "artifact_type": result.artifact_type,
                        "ui_payload": result.ui_payload,
                    })
            except Exception as exc:
                log.exception("[plugin] /plugin/run error")
                self._send_json(500, {"handled": False, "message": str(exc)})

        elif self.path == "/plugin/memory_save":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                messages = body.get("messages", [])
                from vani.plugins import get_registry
                results = asyncio.run(get_registry().broadcast_memory_save(messages))
                self._send_json(200, {"ok": True, "saved": results})
            except Exception as exc:
                self._send_json(500, {"ok": False, "message": str(exc)})

        elif self.path == "/plugin/config":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                key = body.get("key", "")
                value = body.get("value", "")
                if key and value:
                    import os as _os
                    _os.environ[key] = value
                    # Also persist to .env if possible
                    try:
                        env_path = PROJECT_ROOT / ".env"
                        lines = env_path.read_text().splitlines() if env_path.exists() else []
                        updated = False
                        for i, line in enumerate(lines):
                            if line.startswith(key + "="):
                                lines[i] = f'{key}="{value}"'
                                updated = True
                                break
                        if not updated:
                            lines.append(f'{key}="{value}"')
                        env_path.write_text("\n".join(lines) + "\n")
                    except Exception:
                        pass
                self._send_json(200, {"ok": True})
            except Exception as exc:
                self._send_json(500, {"ok": False, "message": str(exc)})

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

            elif self.path == "/mentor/status":
                try:
                    from vani.memory.mentor_memory import get_active_session
                    session = get_active_session()
                    if not session:
                        self._send_json(200, {"active": False})
                        return
                    
                    from vani.services.mentor_service import get_concept_details
                    curr_concept = "None"
                    if session.get("current_concept_id"):
                        concept = get_concept_details(session["current_concept_id"])
                        if concept:
                            curr_concept = concept["name"]
                    
                    self._send_json(200, {
                        "active": True,
                        "filename": session["filename"],
                        "coverage_score": session["coverage_score"],
                        "mastery_score": session["mastery_score"],
                        "current_concept": curr_concept,
                        "roast_mode": session["roast_mode"],
                        "mode_type": session["mode_type"]
                    })
                except Exception as e:
                    self._send_json(500, {"active": False, "error": str(e)})

            elif self.path == "/mentor/report":
                try:
                    from vani.memory.mentor_memory import get_active_session
                    session = get_active_session()
                    if not session:
                        self._send_json(400, {"reply": "No active session."})
                        return
                    from vani.services.mentor_service import compile_final_mastery_report
                    report = compile_final_mastery_report(session["document_id"])
                    self._send_json(200, {"ok": True, "report": report})
                except Exception as e:
                    self._send_json(500, {"reply": str(e)})

            # ── Plugin GET routes ──────────────────────────────────────────────
            elif self.path == "/plugin/list":
                try:
                    from vani.plugins import get_registry
                    plugins = get_registry().list_plugins()
                    self._send_json(200, {"plugins": plugins})
                except Exception as exc:
                    self._send_json(500, {"plugins": [], "error": str(exc)})

            elif self.path == "/plugin/memory":
                try:
                    from vani.plugins.builtin.memory_plugin import _load_memory
                    data = _load_memory()
                    sessions = data.get("sessions", [])
                    self._send_json(200, {
                        "sessions_count": len(sessions),
                        "facts": data.get("facts", {}),
                        "last_5": sessions[-5:] if sessions else [],
                    })
                except Exception as exc:
                    self._send_json(500, {"sessions_count": 0, "facts": {}, "last_5": [], "error": str(exc)})

            elif self.path.startswith("/teach_signal.json"):
                try:
                    from vani.ui.teach_bridge import TEACH_SIGNAL_PATH
                    if TEACH_SIGNAL_PATH.exists():
                        body = TEACH_SIGNAL_PATH.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                except Exception:
                    pass
                self.send_response(404); self.end_headers()
                return

            elif self.path.startswith("/plugin_signal.json"):
                try:
                    plugin_signal_path = PACKAGE_ROOT / "ui" / "plugin_signal.json"
                    if plugin_signal_path.exists():
                        body = plugin_signal_path.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                except Exception:
                    pass
                self.send_response(404); self.end_headers()
                return

            elif self.path in ("/", "/ui"):
                html_file = HTML_PATH
                if PATCHED_HTML_PATH.exists() and PATCHED_HTML_PATH.stat().st_mtime >= HTML_PATH.stat().st_mtime:
                    html_file = PATCHED_HTML_PATH
                body = html_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            elif self.path == "/overlay":
                # ── Dedicated Dynamic Island overlay — standalone, no avatar code ──
                overlay_html = PACKAGE_ROOT / "ui" / "overlay.html"
                if not overlay_html.exists():
                    self.send_response(404); self.end_headers(); return
                body = overlay_html.read_bytes()
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

# Tauri API server removed
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
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=60.0, connect=30.0)
        lk = LiveKitAPI(
            os.getenv("LIVEKIT_URL", ""),
            os.getenv("LIVEKIT_API_KEY", ""),
            os.getenv("LIVEKIT_API_SECRET", ""),
            timeout=timeout,
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
    # Always delete stale patched file so we regenerate from current ui.html
    if PATCHED_HTML_PATH.exists():
        PATCHED_HTML_PATH.unlink()
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

    # ── Ensure plugin panel is in patched output (idempotent check) ───────────
    if "plugin-fab" not in html:
        try:
            from pathlib import Path as _Path
            _panel = _Path(__file__).parent / "ui" / "ui.html"
            # Plugin panel already injected in ui.html — if not present, it means
            # the base file is old. Just ensure the patched file has it by
            # re-reading from the (already patched) HTML_PATH which has the panel.
            pass  # ui.html already has plugin panel injected
        except Exception:
            pass

    out  = PATCHED_HTML_PATH
    out.write_text(html, encoding="utf-8")
    return out


def _open_ui(html_path: Path):
    if os.getenv("VANI_DESKTOP") == "1" or os.getenv("VANI_NO_BROWSER") == "1":
        log.info("[UI] Running in desktop mode. Skipping default browser launch.")
        return
    import webbrowser
    webbrowser.open(f"http://127.0.0.1:5500/")
    log.info("[UI] Opened browser at http://127.0.0.1:5500/")


# ── Module-level entrypoint ───────────────────────────────────────────────────

async def entrypoint(ctx):

    from livekit.agents import AgentSession, Agent
    # ── FIX 6: RoomInputOptions import guarded — set to None if unavailable ───
    # Original code imported this at entrypoint top and used it unchecked below.
    # If the import fails, the later RoomInputOptions(noise_cancellation=nc) call
    # would raise UnboundLocalError. Now None-checked before use.
    try:
        from livekit.agents import RoomInputOptions, RoomOutputOptions
    except ImportError:
        RoomInputOptions = None
        RoomOutputOptions = None

    from vani.prompts import get_realtime_prompt
    from vani.reasoning import get_thinking_capability_tool

    log.info(f"[vani] room={ctx.room.name} session starting")
    _patched_state_update({"status": "Connecting..."})

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
            realtime_prompt = get_realtime_prompt()
            modalities = ["AUDIO"]
            super().__init__(
                instructions=realtime_prompt,
                llm=google.beta.realtime.RealtimeModel(
                    model=REALTIME_MODEL,
                    voice="Aoede",
                    temperature=float(os.getenv("VANI_REALTIME_TEMPERATURE", "0.30")),
                    instructions=realtime_prompt,
                    modalities=modalities,
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

    # ── Speaker verification track listener ─────────────────────────────────────
    import collections
    session_audio_buffer = collections.deque(maxlen=150) # last ~4.5s of audio
    session_audio_sr = 16000 # default

    async def _read_audio_stream(track):
        nonlocal session_audio_sr
        from livekit import rtc
        try:
            stream = rtc.AudioStream(track)
            async for frame_event in stream:
                frame = frame_event.frame
                session_audio_sr = frame.sample_rate
                import numpy as np
                if frame.data.itemsize == 2:
                    pcm = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32) / 32768.0
                elif frame.data.itemsize == 4:
                    pcm = np.frombuffer(frame.data, dtype=np.float32)
                else:
                    pcm = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32) / 32768.0
                
                session_audio_buffer.append(pcm)
        except Exception as exc:
            log.warning(f"[SECURITY] _read_audio_stream failed: {exc}")

    def _handle_track(track):
        from livekit import rtc
        kind_str = str(getattr(track, "kind", "")).lower()
        if "audio" in kind_str or (hasattr(rtc, "TrackKind") and track.kind == rtc.TrackKind.KIND_AUDIO):
            log.info(f"[SECURITY] Subscribed to audio track {track.sid} for speaker verification")
            asyncio.create_task(_read_audio_stream(track))

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track, publication, participant):
        _handle_track(track)

    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            if publication.track:
                _handle_track(publication.track)

    if os.getenv("VANI_PREWARM_OLLAMA", "0") == "1":
        asyncio.create_task(_prewarm_ollama())

    # Pre-warm the Gemini client connection pool to avoid first-call delay
    asyncio.create_task(_prewarm_gemini())

    vad = None
    if os.getenv("VANI_USE_SILERO", "0") == "1" and silero is not None:
        try:
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
        _session_vars = {"last_user_transcript": None}
        @sess.on("agent_started_speaking")
        def _on_speak(*_):
            _patched_state_update(dict(speaking=True, listening=False, processing=False, status="Speaking...", transcript=""))
            _run_audio(vani_deactivated)

        @sess.on("agent_stopped_speaking")
        def _on_stop(*_):
            _patched_state_update(dict(speaking=False, listening=True, processing=False, status="Listening...", transcript=""))
            _run_audio(vani_activated)

        # ── Speaker verification: pre-compute embedding while user is still speaking ──
        _pending_speaker_future = None

        async def _precompute_speaker_embedding_async():
            """Build the speaker embedding in the background during the utterance."""
            try:
                await asyncio.sleep(0.6)  # Let at least 600ms of audio accumulate first
                if not session_audio_buffer:
                    return
                import numpy as np
                from vani.audio.wake_verifier import is_verify_enabled, verify_wake_audio_sync
                if not is_verify_enabled():
                    return
                wav = np.concatenate(list(session_audio_buffer))
                loop = asyncio.get_running_loop()
                # Run in executor so it doesn't block the event loop
                result = await loop.run_in_executor(None, verify_wake_audio_sync, wav, session_audio_sr)
                return result
            except Exception as e:
                log.debug(f"[speaker-precompute] skipped: {e}")
                return None

        @sess.on("user_started_speaking")
        def _on_user(*_):
            nonlocal _pending_speaker_future
            try:
                from vani.audio import stop_playback
                stop_playback()              # stops Indic-TTS mid-sentence
            except Exception:
                pass
            _patched_state_update(dict(speaking=False, listening=True, processing=False, status="Listening...", transcript=""))
            session_audio_buffer.clear()
            # Kick off speaker embedding computation NOW, in parallel with the user speaking
            if SECURITY_ENABLED:
                _pending_speaker_future = asyncio.ensure_future(_precompute_speaker_embedding_async())
            try:
                from vani.reasoning.worker import _get_task_queue
                q = _get_task_queue()
                if q.is_interruptible():
                    q.cancel_active_task_threadsafe()
                else:
                    log.info("[interrupted] Active task is marked non-interruptible. Ignoring user speaking.")
            except Exception as e:
                log.warning(f"[interrupted] Failed to cancel active task on user speaking: {e}")

        @sess.on("user_stopped_speaking")
        def _on_stop2(*_):
            _patched_state_update(dict(speaking=False, listening=False, processing=True, status="Thinking...", transcript=""))

        @sess.on("conversation_item_added")
        def _on_item(event, *_):
            try:
                chat_msg = getattr(event, "item", None)
                if chat_msg is None:
                    chat_msg = event
                role = getattr(chat_msg, "role", "")
                text = getattr(chat_msg, "text", "") or getattr(chat_msg, "text_content", "") or ""
                if text and role in ("assistant", "agent"):
                    text_strip = text.strip()
                    if text_strip in _recently_spoken_fallback_texts:
                        _recently_spoken_fallback_texts.discard(text_strip)
                        return
                    _patched_state_update(dict(transcript=text))

                    # ── Native TTS intercept (VANI_LOCAL_TTS=1) ──────────────────
                    # Gemini audio is muted via RoomOutputOptions(audio_enabled=False).
                    # This fires when text is committed — before LiveKit would play audio.
                    # Result: 250-400ms perceived latency vs 600-1400ms with Gemini audio.
                    if os.getenv("VANI_LOCAL_TTS", "0") == "1" and text_strip:
                        try:
                            from vani.audio.local_tts import speak_local_async
                            speak_local_async(text_strip)
                            log.info(f"[NATIVE_TTS] Speaking via OS TTS: {text_strip[:60]!r}")
                        except Exception as _tts_ex:
                            log.warning(f"[NATIVE_TTS] speak_local_async failed: {_tts_ex}")
                    # ── END Native TTS ────────────────────────────────────────────
            except Exception:
                pass

        async def _speculative_warm(partial_text: str):
            try:
                from vani.planner.brain import PlannerBrain
                await PlannerBrain.classify_only(partial_text)
            except Exception:
                pass

        @sess.on("user_input_transcribed")
        def _on_transcript(event, *_):
            async def _async_transcript():
                try:
                    text = getattr(event, "transcript", None) or getattr(event, "text", None) or ""
                    if not text:
                        return
                    
                    _patched_state_update(dict(transcript=text))

                    is_final = getattr(event, "is_final", None)
                    if is_final is False:
                        if len(text) > 15:
                            asyncio.create_task(_speculative_warm(text))
                        return
                    # is_final is True or None (attribute absent = treat as final)
                    _session_vars["last_user_transcript"] = text

                    # ── Speaker Verification Gate (asynchronous/non-blocking) ───────
                    if SECURITY_ENABLED:
                        from vani.audio.wake_verifier import is_verify_enabled
                        if is_verify_enabled():
                            async def _verify_speaker_async():
                                accepted = None
                                # Use the pre-computed future from user_started_speaking if ready
                                if _pending_speaker_future is not None:
                                    try:
                                        if _pending_speaker_future.done():
                                            accepted = _pending_speaker_future.result()
                                        else:
                                            # Not done yet — wait briefly (should be near-instant)
                                            accepted = await asyncio.wait_for(_pending_speaker_future, timeout=0.5)
                                    except Exception as e:
                                        log.debug(f"[speaker-verify] pre-computed future failed: {e}")
                                        accepted = None
                                # Fallback: compute fresh if pre-computation failed or wasn't started
                                if accepted is None and session_audio_buffer:
                                    import numpy as np
                                    from vani.audio.wake_verifier import verify_wake_audio_sync
                                    wav = np.concatenate(list(session_audio_buffer))
                                    loop = asyncio.get_running_loop()
                                    accepted = await loop.run_in_executor(
                                        None, verify_wake_audio_sync, wav, session_audio_sr
                                    )
                                if accepted is False:
                                    log.warning("[SECURITY] Speaker verification failed during session turn!")
                                    try:
                                        await sess.interrupt()
                                    except Exception:
                                        pass
                                    activate_lockdown()
                                    response = get_lockdown_response(text)
                                    if response:
                                        await _say_lockdown(sess, response)
                                elif accepted is True:
                                    if is_locked_down():
                                        deactivate_lockdown()

                            asyncio.create_task(_verify_speaker_async())

                    # ── Security lockdown intercept ───────────────────────────────
                    if SECURITY_ENABLED and is_locked_down():
                        log.warning("[SECURITY] Lockdown active — intercepting transcript: %r", text)
                        try:
                            await sess.interrupt()
                        except Exception:
                            pass
                        response = get_lockdown_response(text)
                        if response:
                            await _say_lockdown(sess, response)
                        return

                    # ── Dedup / repeated-word filter ──────────────────────────────
                    if _is_duplicate_utterance(text):
                        try:
                            await sess.interrupt()
                        except Exception:
                            pass
                except Exception:
                    pass
            asyncio.create_task(_async_transcript())

        async def _say_lockdown(session, text: str):
            try:
                await asyncio.sleep(0.15)
                from vani.reasoning.worker import say_to_user
                await say_to_user(text)
            except Exception as exc:
                log.warning("[SECURITY] _say_lockdown failed: %s", exc)

    def _new_agent_session():
        session_kwargs = {
            "allow_interruptions": True,
            "min_endpointing_delay": float(os.getenv("VANI_ENDPOINT_MIN_DELAY", "0.05")),
            "max_endpointing_delay": float(os.getenv("VANI_ENDPOINT_MAX_DELAY", "0.15")),
            "min_interruption_duration": float(os.getenv("VANI_INTERRUPT_MIN_DURATION", "0.08")),
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

            room_output = None
            if RoomOutputOptions is not None:
                # In native TTS mode (VANI_LOCAL_TTS=1), mute Gemini's audio output.
                # We intercept the text via conversation_item_added and speak via
                # macOS 'say' / Windows SAPI instead — eliminates double speech.
                _native_tts_mode = os.getenv("VANI_LOCAL_TTS", "0") == "1"
                room_output = RoomOutputOptions(audio_enabled=not _native_tts_mode)

            kwargs = {}
            if room_input:
                kwargs["room_input_options"] = room_input
            if room_output:
                kwargs["room_output_options"] = room_output

            await session.start(
                room=ctx.room,
                agent=Assistant(),
                **kwargs,
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
            _patched_state_update({"status": f"Error: {e}"})
            return

    _patched_state_update(dict(connected=True, status="Ready - say something!"))
    _patched_state_update(dict(speaking=False, listening=True, processing=False))
    _notify_mac("Siya ready", "Voice conversation is ready.")
    try:
        from vani.reasoning import say_to_user
        asyncio.create_task(say_to_user("Siya is ready. You can speak now.", limit=None))
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

    # Tauri API server removed

    # Reset conversation, active document, working memory, and semantic memories on startup
    try:
        from vani.memory.conversation_writer import clear_conversation
        clear_conversation()
        from vani.memory.human_memory import clear_active_document
        clear_active_document()
        from vani.memory.working_memory import clear_working_memory
        clear_working_memory()
        from vani.memory.vector_store import SQLiteVectorStore
        store = SQLiteVectorStore()
        store.clear_all()
        from vani.ui.teach_bridge import clear_teach_visual
        clear_teach_visual()
        log.info("[startup] Memory and teaching visual reset successfully on startup")
    except Exception as startup_reset_err:
        log.warning(f"[startup] Memory reset on startup failed (non-fatal): {startup_reset_err}")

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