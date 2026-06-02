"""
vani/reasoning/screen.py  — v3 (maximum accuracy)

Pipeline per request:
  ① Fast context   — Accessibility API / browser DOM / VS Code diagnostics  (0 screenshot)
  ② If enough      → return immediately (no screenshot at all)
  ③ Active-window  — screencapture -l <winID>  (NOT full 1920-px dump)
  ④ OCR            — Apple Vision accurate-mode → Tesseract CLI  (PaddleOCR removed)
  ⑤ Gemini vision  — cropped window image + OCR text + structured context
"""

import os
import re
import time
import subprocess
import asyncio
import tempfile
import concurrent.futures
from langchain_core.tools import tool

from vani.reasoning.shared import (
    IS_MAC,
    logger,
    _osascript,
    _compact_lines,
    _frontmost_app_name,
)

# ─────────────────────────────────────────────────────────────────────────────
# 1.  INTENT DETECTION
# ─────────────────────────────────────────────────────────────────────────────

_SCREEN_HINTS = [
    # English
    "read my screen","read screen","see my screen","what is on my screen",
    "what's on my screen","explain this","help me here","what am i doing",
    "analyze this","look at my screen","check my screen","active tab","current page",
    # Hindi / Hinglish
    "meri screen dekho","screen dekho","meri screen padh","yeh kya hai",
    "main kya kar raha","isko samjhao","meri help karo","isme kya problem",
    "code check karo","yeh error kya hai","screen pe kya dikh",
    "kya dikh raha hai","isme kya ho raha",
    "screen dekh","yeh kya chal raha","isko explain kar","code dekh",
    "meri screen check","isme issue kya","dekh kya galti","screen check kar",
    "bhai screen","zara screen","screen pe dekh","screen mein kya",
    "galti kya hai","error kya hai","problem kya hai screen",
    # VS Code / IDE specific
    "sidebar dekho","sidebar dekh","main code dekho","vscode dekho",
    "terminal dekho","console dekho","error dekho","debugger dekho",
    "code section dekho","problems dekho","output dekho",
]

def _is_screen_intent(query: str) -> bool:
    q = query.lower().strip()
    if any(h in q for h in _SCREEN_HINTS):
        return True
    toks = set(q.split())
    has_screen = bool(toks & {"screen","dekh","sidebar","terminal","console","editor"})
    has_action = bool(toks & {"dekho","dekh","check","samjhao","explain","read",
                               "analyze","see","galti","error","problem","issue","dikh"})
    return has_screen and has_action


# ─────────────────────────────────────────────────────────────────────────────
# 2.  APP CATEGORY
# ─────────────────────────────────────────────────────────────────────────────

_BROWSERS  = {"Google Chrome","Brave Browser","Microsoft Edge","Safari","Firefox"}
_TERMINALS = {"Terminal","iTerm2","Warp","Alacritty","kitty","Hyper","Ghostty"}
_VSCODE    = {"Code","Visual Studio Code","Cursor","Windsurf"}
_IDES      = {"PyCharm","IntelliJ IDEA","WebStorm","Xcode","Android Studio","Fleet"}

def _category(app: str) -> str:
    if app in _BROWSERS:  return "browser"
    if app in _VSCODE:    return "vscode"
    if app in _IDES:      return "ide"
    if app in _TERMINALS: return "terminal"
    return "other"


# ─────────────────────────────────────────────────────────────────────────────
# 3.  FAST CONTEXT  (no screenshot — Accessibility / DOM / diagnostics)
# ─────────────────────────────────────────────────────────────────────────────

_ctx_cache: tuple | None = None
_CTX_TTL = 3.0   # seconds


# ── 3a. VS Code / Cursor ──────────────────────────────────────────────────────

def _vscode_diagnostics() -> str:
    """
    Pull Problems panel errors/warnings directly from Accessibility tree.
    Returns empty string if nothing found or VS Code not running.
    """
    script = r'''
on safe(t)
    try
        set s to t as text
        if s is "missing value" then return ""
        return s
    on error
        return ""
    end try
end safe

tell application "System Events"
    set procs to every process whose name is in {"Code","Cursor","Windsurf"}
    if (count of procs) = 0 then return ""
    set proc to item 1 of procs
    set out to ""
    try
        tell proc
            if not (exists window 1) then return ""
            -- Walk two levels looking for list/table rows that mention error/warning
            repeat with el in UI elements of window 1
                try
                    set r to role of el
                    if r is in {"AXList","AXTable","AXOutline","AXGroup"} then
                        repeat with row in UI elements of el
                            try
                                set nm to my safe(name of row)
                                set vl to my safe(value of row)
                                set combined to nm & " " & vl
                                if combined contains "error" or combined contains "warning" ¬
                                   or combined contains "Error" or combined contains "Warning" then
                                    set out to out & combined & linefeed
                                    if (length of out) > 2500 then return out
                                end if
                            end try
                        end repeat
                    end if
                end try
            end repeat
        end tell
    end try
    return out
end tell
'''
    return _compact_lines(_osascript(script, timeout=2.5), max_lines=60, max_chars=2500)


def _vscode_active_file() -> str:
    """Window title contains active file path in VS Code."""
    script = r'''
tell application "System Events"
    set procs to every process whose name is in {"Code","Cursor","Windsurf"}
    if (count of procs) = 0 then return ""
    tell item 1 of procs
        if not (exists window 1) then return ""
        return name of window 1
    end tell
end tell
'''
    return _osascript(script, timeout=1.0)


def _vscode_editor_text() -> str:
    """
    Try to grab visible editor content via Accessibility (AXTextArea).
    Returns first ~1200 chars so we don't overflow context.
    """
    script = r'''
tell application "System Events"
    set procs to every process whose name is in {"Code","Cursor","Windsurf"}
    if (count of procs) = 0 then return ""
    tell item 1 of procs
        if not (exists window 1) then return ""
        try
            set areas to every UI element of window 1 whose role is "AXTextArea"
            if (count of areas) > 0 then
                set v to value of item 1 of areas
                if v is missing value then return ""
                set v to v as text
                if length of v > 1200 then set v to text 1 thru 1200 of v
                return v
            end if
        end try
        return ""
    end tell
end tell
'''
    return _osascript(script, timeout=2.0)


def _vscode_full_context() -> str:
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        f1 = ex.submit(_vscode_active_file)
        f2 = ex.submit(_vscode_diagnostics)
        f3 = ex.submit(_vscode_editor_text)
        title  = f1.result()
        errors = f2.result()
        code   = f3.result()

    parts = []
    if title:
        parts.append(f"Active file/window: {title}")
    if errors:
        parts.append(f"Problems panel (errors/warnings):\n{errors}")
    if code:
        parts.append(f"Editor content (partial):\n{code}")
    return "\n\n".join(parts)


# ── 3b. Browser ───────────────────────────────────────────────────────────────

_BROWSER_TAB_SCRIPT = {
    "Google Chrome": '''
tell application "Google Chrome"
    if (count of windows) = 0 then return ""
    set t to active tab of front window
    return title of t & linefeed & URL of t
end tell''',
    "Brave Browser": '''
tell application "Brave Browser"
    if (count of windows) = 0 then return ""
    set t to active tab of front window
    return title of t & linefeed & URL of t
end tell''',
    "Microsoft Edge": '''
tell application "Microsoft Edge"
    if (count of windows) = 0 then return ""
    set t to active tab of front window
    return title of t & linefeed & URL of t
end tell''',
    "Safari": '''
tell application "Safari"
    if (count of windows) = 0 then return ""
    return name of current tab of front window & linefeed & URL of current tab of front window
end tell''',
}

_BROWSER_TEXT_SCRIPT = {
    "Google Chrome":
        'tell application "Google Chrome"\n  if (count of windows)=0 then return ""\n  return execute active tab of front window javascript "document.body.innerText.slice(0,3000)"\nend tell',
    "Brave Browser":
        'tell application "Brave Browser"\n  if (count of windows)=0 then return ""\n  return execute active tab of front window javascript "document.body.innerText.slice(0,3000)"\nend tell',
    "Microsoft Edge":
        'tell application "Microsoft Edge"\n  if (count of windows)=0 then return ""\n  return execute active tab of front window javascript "document.body.innerText.slice(0,3000)"\nend tell',
    "Safari":
        'tell application "Safari"\n  if (count of windows)=0 then return ""\n  return do JavaScript "document.body.innerText.slice(0,3000)" in current tab of front window\nend tell',
}

def _browser_context(app: str) -> str:
    parts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(_osascript, _BROWSER_TAB_SCRIPT.get(app, ""), 1.2)
        f2 = ex.submit(_osascript, _BROWSER_TEXT_SCRIPT.get(app, ""), 1.8)
        tab_raw = f1.result()
        page_text = f2.result()
    if tab_raw:
        lines = [l.strip() for l in tab_raw.splitlines() if l.strip()]
        parts.append(f"Tab: {lines[0]}")
        if len(lines) > 1:
            parts.append(f"URL: {lines[1]}")
    if page_text:
        parts.append(f"Page text:\n{_compact_lines(page_text, 35, 2500)}")
    return "\n".join(parts)


# ── 3c. Terminal ──────────────────────────────────────────────────────────────

def _terminal_context(app: str) -> str:
    a = app.replace('"', '\\"')
    script = f'''
tell application "System Events"
    tell process "{a}"
        if not (exists window 1) then return ""
        try
            set sa to first UI element of window 1 whose role is "AXScrollArea"
            set ta to first UI element of sa whose role is "AXTextArea"
            set v to value of ta
            if v is missing value then return ""
            set v to v as text
            if length of v > 2500 then set v to text ((length of v)-2499) thru -1 of v
            return v
        end try
        return ""
    end tell
end tell
'''
    return _compact_lines(_osascript(script, timeout=2.0), max_lines=50, max_chars=2500)


# ── 3d. Generic Accessibility snapshot ───────────────────────────────────────

def _accessibility_snapshot(app: str, depth: int = 3) -> str:
    if not app:
        return ""
    a = app.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
on safe(t)
    try
        set s to t as text
        if s is "missing value" then return ""
        return s
    on error
        return ""
    end try
end safe

on collect(e, d)
    if d <= 0 then return ""
    set out to ""
    set nm to my safe(name of e)
    set vl to my safe(value of e)
    set ro to my safe(role of e)
    if nm is not "" or vl is not "" then
        set out to ro & ": " & nm & " " & vl & linefeed
    end if
    try
        repeat with child in UI elements of e
            set out to out & my collect(child, d-1)
            if (length of out) > 2000 then return out
        end repeat
    end try
    return out
end collect

tell application "System Events"
    tell process "{a}"
        if not (exists window 1) then return ""
        return my collect(window 1, {depth})
    end tell
end tell
'''
    return _compact_lines(_osascript(script, timeout=2.0), max_lines=35, max_chars=2000)


# ── 3e. Master fast-context entry point ──────────────────────────────────────

def _get_fast_context() -> tuple:
    """Returns (context_str, front_app, category)."""
    global _ctx_cache

    if not IS_MAC:
        return "", "", "other"

    now = time.monotonic()
    if _ctx_cache and (now - _ctx_cache[0]) < _CTX_TTL:
        return _ctx_cache[1], _ctx_cache[2], _ctx_cache[3]

    front_app = _osascript(
        'tell application "System Events" to get name of first application process whose frontmost is true',
        timeout=1.0,
    )
    window_title = _osascript(
        'tell application "System Events" to tell first application process '
        'whose frontmost is true to get name of front window',
        timeout=1.0,
    )
    cat = _category(front_app)

    lines = []
    if front_app:
        lines.append(f"Active app: {front_app}")
    if window_title and window_title != front_app:
        lines.append(f"Window: {window_title}")

    if cat == "vscode":
        ctx = _vscode_full_context()
        if ctx:
            lines.append(ctx)
    elif cat == "browser":
        ctx = _browser_context(front_app)
        if ctx:
            lines.append(ctx)
    elif cat == "terminal":
        ctx = _terminal_context(front_app)
        if ctx:
            lines.append(f"Terminal output:\n{ctx}")
    else:
        acc = _accessibility_snapshot(front_app, depth=3)
        if acc:
            lines.append(f"UI text:\n{acc}")

    result = "\n".join(lines).strip()
    _ctx_cache = (now, result, front_app, cat)
    return result, front_app, cat


def _fast_enough(query: str, ctx: str, cat: str) -> bool:
    """True = no screenshot needed."""
    if not ctx:
        return False
    q = query.lower()

    # purely meta questions
    if any(p in q for p in ["what am i watching","kya dekh raha","active tab",
                              "which page","current page","url kya","kaunsi website"]):
        return True

    # VS Code: if Problems panel data is present and user asks about error
    if cat == "vscode" and "Problems panel" in ctx:
        if any(kw in q for kw in ["error","galti","problem","fix","kya hua",
                                    "issue","kyu","kyun","warning"]):
            return True

    # Browser: if page text is present and user asks about content
    if cat == "browser" and "Page text:" in ctx and len(ctx) > 300:
        if any(kw in q for kw in ["explain","samjhao","padh","read","kya likha"]):
            return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# 4.  SCREEN CAPTURE  (active window, not full desktop)
# ─────────────────────────────────────────────────────────────────────────────

def _frontmost_window_id() -> str:
    """
    Use Quartz CGWindowListCopyWindowInfo to get the macOS window ID
    of the topmost on-screen window (layer 0).
    """
    py = (
        "import Quartz\n"
        "opts=Quartz.kCGWindowListOptionOnScreenOnly|Quartz.kCGWindowListExcludeDesktopElements\n"
        "wins=Quartz.CGWindowListCopyWindowInfo(opts,Quartz.kCGNullWindowID)\n"
        "for w in wins:\n"
        "    if w.get('kCGWindowLayer',999)==0:\n"
        "        print(w.get('kCGWindowNumber',''));break\n"
    )
    try:
        r = subprocess.run(["python3", "-c", py],
                           capture_output=True, text=True, timeout=2)
        return r.stdout.strip()
    except Exception:
        return ""


def _capture_active_window() -> str:
    """
    Capture only the frontmost window.
    Fallback order: window-id capture → frontmost-only → full screen.
    Returns path to PNG, or "" on failure.
    """
    tmp = tempfile.mktemp(suffix=".png")

    if IS_MAC:
        win_id = _frontmost_window_id()
        if win_id:
            r = subprocess.run(
                ["screencapture", "-x", "-o", "-l", win_id, tmp],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 1000:
                return tmp

        # Fallback: capture frontmost window without needing its ID
        # -R uses the window bounds; we skip this and just do full-screen
        r = subprocess.run(
            ["screencapture", "-x", "-t", "png", tmp],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 1000:
            return tmp
        return ""

    # Non-macOS fallbacks
    for fn in [_capture_pyautogui, _capture_imagegrab]:
        path = fn(tmp)
        if path:
            return path
    return ""


def _capture_pyautogui(tmp: str) -> str:
    try:
        import pyautogui
        pyautogui.screenshot().save(tmp, "PNG")
        return tmp if os.path.exists(tmp) and os.path.getsize(tmp) > 1000 else ""
    except Exception:
        return ""


def _capture_imagegrab(tmp: str) -> str:
    try:
        from PIL import ImageGrab
        ImageGrab.grab().save(tmp, "PNG")
        return tmp if os.path.exists(tmp) and os.path.getsize(tmp) > 1000 else ""
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# 5.  OCR  (Apple Vision accurate → Tesseract CLI)
# ─────────────────────────────────────────────────────────────────────────────

def _ocr_apple_vision(path: str) -> str:
    """
    Apple Vision Framework — VNRequestTextRecognitionLevelAccurate + Revision 3.
    Best accuracy for code, IDE UI, small fonts.  Pure C-level, fast (~200 ms).
    Language correction OFF so variable/function names are preserved exactly.
    """
    if not IS_MAC:
        return ""
    try:
        import Vision
        from Foundation import NSURL

        texts: list[str] = []
        confs: list[float] = []

        def _cb(req, err):
            if err:
                return
            for obs in req.results() or []:
                cands = obs.topCandidates_(1)
                if cands and len(cands):
                    texts.append(str(cands[0].string()))
                    confs.append(float(cands[0].confidence()))

        url = NSURL.fileURLWithPath_(path)
        req = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(_cb)
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setUsesLanguageCorrection_(False)   # keep code tokens intact
        req.setMinimumTextHeight_(0.007)         # detect small IDE font sizes

        try:
            req.setRevision_(3)   # macOS 13+ — most accurate revision
        except Exception:
            pass

        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, {})
        handler.performRequests_error_([req], None)

        # Filter low-confidence results (junk from background gradients)
        MIN_CONF = 0.30
        filtered = [t for t, c in zip(texts, confs) if c >= MIN_CONF]
        return _compact_lines("\n".join(filtered), max_lines=100, max_chars=6000)
    except Exception as e:
        logger.debug(f"[SCREEN] Apple Vision unavailable: {e}")
        return ""


def _ocr_tesseract(path: str) -> str:
    """
    Tesseract 5 via CLI — fast C binary, excellent for monospace/code fonts.
    Uses LSTM engine (--oem 3) + single-block layout (--psm 6).
    """
    try:
        out_base = tempfile.mktemp()
        r = subprocess.run(
            ["tesseract", path, out_base,
             "--oem", "3",   # LSTM + legacy combined
             "--psm", "6",   # Assume uniform block of text
             "-l", "eng"],
            capture_output=True, text=True, timeout=12,
        )
        out_file = out_base + ".txt"
        if os.path.exists(out_file):
            with open(out_file) as f:
                text = f.read()
            try:
                os.unlink(out_file)
            except Exception:
                pass
            return _compact_lines(text, max_lines=100, max_chars=6000)
    except FileNotFoundError:
        pass   # tesseract not installed — silent skip
    except Exception as e:
        logger.debug(f"[SCREEN] Tesseract error: {e}")
    return ""


def _preprocess_image(path: str) -> str:
    """
    Optional preprocessing — upscale 1.5x + unsharp mask.
    Helps when IDE font size is 12-14 px (very common).
    Returns path to preprocessed image, or original path if cv2 not available.
    """
    try:
        import cv2
        img = cv2.imread(path)
        if img is None:
            return path
        h, w = img.shape[:2]
        # Only upscale if width is under 2400 to avoid memory blowup
        if w < 2400:
            img = cv2.resize(img, (int(w * 1.5), int(h * 1.5)),
                             interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Unsharp mask — sharpens text edges without blobbing
        blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
        sharp = cv2.addWeighted(gray, 1.6, blur, -0.6, 0)
        pre = tempfile.mktemp(suffix=".png")
        cv2.imwrite(pre, sharp)
        return pre
    except Exception:
        return path


def _run_ocr(path: str) -> str:
    """
    Run best available OCR.  Returns combined text.
    Order: Apple Vision (accurate) → Tesseract.  PaddleOCR removed.
    """
    pre = _preprocess_image(path)
    cleanup = (pre != path)
    try:
        # ① Apple Vision — best on macOS for code/IDE
        vision_text = _ocr_apple_vision(pre)
        if vision_text and len(vision_text) > 40:
            return vision_text

        # ② Tesseract — fast C binary, works on all platforms
        tess_text = _ocr_tesseract(pre)
        if tess_text and len(tess_text) > 20:
            return tess_text

        # ③ Apple Vision fast-mode as last resort
        return _ocr_apple_vision(path)  # use original, no preprocessing
    finally:
        if cleanup:
            try:
                os.unlink(pre)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# 6.  GEMINI VISION
# ─────────────────────────────────────────────────────────────────────────────

def _build_prompt(query: str, fast_ctx: str, ocr: str, cat: str) -> str:
    q = query.strip() or "Screen par exactly kya visible hai?"
    app_hint = {
        "vscode":   "VS Code/Cursor IDE open hai. Focus: active file name, red/yellow error indicators, Problems panel, sidebar structure, code content.",
        "browser":  "Browser open hai. Focus: page content, URL bar, any error messages, form fields.",
        "terminal": "Terminal open hai. Focus: last command run, its output, any error/traceback lines.",
        "ide":      "IDE open hai. Focus: code, error squiggles, file structure.",
        "other":    "",
    }.get(cat, "")

    evidence = []
    if fast_ctx:
        evidence.append(f"Structured local context:\n{fast_ctx}")
    if ocr:
        evidence.append(f"OCR text (Apple Vision / Tesseract):\n{ocr}")
    ev_block = "\n\n".join(evidence) or "No local context. Rely on screenshot pixels only."

    return f"""You are Vani's precise screen-reading module. The user asked:
{q}

{f"App context: {app_hint}" if app_hint else ""}

RULES — follow strictly:
- Base your answer ONLY on the screenshot and local evidence below.
- Do NOT invent file names, error messages, code, or UI elements not visible.
- For code / errors: quote EXACT text as visible. If unreadable, say "clearly nahi dikh raha".
- If VS Code: mention the active file, any red underlines, Problems panel entries, and sidebar items visible.
- If Terminal: quote the exact error/traceback if readable.
- Use hedged language ("dikh raha hai", "lag raha hai") for anything partially visible.
- Do NOT identify real people.

Local evidence:
{ev_block}

Answer in Hinglish. One clear opening sentence stating what's definitely visible, then details, then unclear areas last."""


def _encode_for_gemini(path: str) -> tuple:
    """Encode image as JPEG (optionally resized) for Gemini. Returns (b64, mime)."""
    import base64
    from io import BytesIO

    try:
        from PIL import Image
        with Image.open(path) as img:
            img = img.convert("RGB")
            max_w = int(os.getenv("VANI_SCREEN_MAX_WIDTH", "1600"))
            if img.width > max_w:
                img = img.resize(
                    (max_w, int(img.height * max_w / img.width)),
                    Image.LANCZOS,
                )
            buf = BytesIO()
            img.save(buf, "JPEG",
                     quality=int(os.getenv("VANI_SCREEN_JPEG_QUALITY", "88")),
                     optimize=True)
            return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"
    except Exception:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode(), "image/png"


def _gemini_vision(b64: str, mime: str, prompt: str, api_key: str) -> str | None:
    import requests, time as _t

    payload = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime, "data": b64}},
        ]}],
        "generationConfig": {
            "temperature": 0, "topP": 0.1, "topK": 1,
            "maxOutputTokens": 900,
        },
    }
    models = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-image"]

    for model in models:
        try:
            url = (f"https://generativelanguage.googleapis.com/v1beta"
                   f"/models/{model}:generateContent?key={api_key}")
            logger.info(f"[SCREEN] → {model}")
            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code == 429:
                _t.sleep(min(int(resp.headers.get("Retry-After", 3)), 5))
                continue
            resp.raise_for_status()
            data = resp.json()
            text = (data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", ""))
            return text.strip() or None
        except Exception as e:
            logger.warning(f"[SCREEN] {model} failed: {e}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 7.  MAIN TOOL
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def read_screen(query: str = "") -> str:
    """
    Screen ko accurately read karta hai — VS Code errors, terminal output, browser pages.

    Smart pipeline:
    • VS Code open → direct diagnostics/errors bina screenshot liye
    • Browser open  → DOM text direct
    • Screenshot lena pade → sirf active window (not 1920-px full dump)
    • OCR → Apple Vision accurate mode (code ke liye best)

    Triggers: 'screen dekho', 'error dekho', 'sidebar dekho', 'code dekho',
              'terminal dekho', 'read my screen', 'yeh kya chal raha' etc.
    """
    logger.info(f"[SCREEN] read_screen  query={query!r}")
    loop = asyncio.get_running_loop()

    # ① Fast context — Accessibility / DOM / VS Code diagnostics
    fast_ctx, front_app, cat = await loop.run_in_executor(None, _get_fast_context)
    logger.info(f"[SCREEN] app={front_app!r}  cat={cat}  ctx_len={len(fast_ctx)}")

    # ② Maybe no screenshot needed at all
    if _fast_enough(query, fast_ctx, cat):
        logger.info("[SCREEN] Fast context sufficient — no screenshot")
        return f"Screen context:\n{fast_ctx}"

    # ③ Capture active window
    screenshot = await loop.run_in_executor(None, _capture_active_window)

    if not screenshot:
        msg = ("Screenshot nahi le paaya. "
               "System Settings → Privacy & Security → Screen Recording mein "
               "Terminal / Python allow karo.")
        return f"{fast_ctx}\n\n{msg}" if fast_ctx else msg

    # ④ OCR (Apple Vision accurate → Tesseract)
    try:
        ocr_text = await asyncio.wait_for(
            loop.run_in_executor(None, _run_ocr, screenshot),
            timeout=9.0,
        )
    except asyncio.TimeoutError:
        logger.warning("[SCREEN] OCR timed out")
        ocr_text = ""

    logger.info(f"[SCREEN] OCR chars={len(ocr_text)}")

    # ⑤ Gemini vision (if key available)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    use_gemini = os.getenv("VANI_SCREEN_USE_GEMINI", "1") == "1"

    if not use_gemini or not api_key:
        try:
            os.unlink(screenshot)
        except Exception:
            pass
        parts = [p for p in [fast_ctx, f"OCR:\n{ocr_text}" if ocr_text else ""] if p]
        return "\n\n".join(parts) or "Screen read nahi ho paaya."

    # Encode image
    try:
        b64, mime = await loop.run_in_executor(None, _encode_for_gemini, screenshot)
    except Exception as e:
        return f"Image encode failed: {e}"
    finally:
        try:
            os.unlink(screenshot)
        except Exception:
            pass

    prompt = _build_prompt(query, fast_ctx, ocr_text, cat)

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None, _gemini_vision, b64, mime, prompt, api_key
            ),
            timeout=30.0,
        )
        if result:
            logger.info(f"[SCREEN] Gemini OK: {result[:80]!r}")
            return result
    except asyncio.TimeoutError:
        logger.warning("[SCREEN] Gemini timed out")

    # Fallback — return local data
    parts = [p for p in [fast_ctx, f"OCR:\n{ocr_text}" if ocr_text else ""] if p]
    return "\n\n".join(parts) or "Screen read nahi ho paaya."


# ─────────────────────────────────────────────────────────────────────────────
# 8.  SUPPORTING TOOLS  (unchanged API)
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def learn_this(content: str, raw: str = "") -> str:
    """
    User-taught fact ya preference ko permanently save karta hai.
    Triggers: 'yaad rakhna', 'remember this', 'seekho', 'save kar lo'.
    """
    try:
        from vani.memory.learning_memory import save_learning
    except ImportError:
        return "Learning module load nahi hua."
    item = save_learning(content, raw=raw)
    itype = item.get("type", "fact")
    if itype == "quiz":     return f"Thik hai, baad mein puchhungi: {content[:80]}"
    if itype == "preference": return f"Yaad rakh liya — {content[:80]}"
    if itype == "rule":     return f"Samajh gayi, save kar diya: {content[:80]}"
    return "Done, yaad rakh liya."


@tool
async def learn_name(name: str, phonetic: str = "", lang: str = "hindi") -> str:
    """
    Naam ka pronunciation seekhta aur cache karta hai.
    Triggers: 'Mera naam X hai', 'X ko aise bolte hain'.
    """
    try:
        from vani.name_pronunciation import ensure_name, cache_name
    except ImportError:
        return "Pronunciation module nahi mila."
    entry = ensure_name(name, lang_hint=lang)
    if phonetic:
        entry = cache_name(name, phonetic=phonetic, lang_hint=lang)
    return f"✅ '{entry['display']}' ka pronunciation yaad kar liya: {entry['phonetic']}"


@tool
async def google_search(query: str) -> str:
    """Google par search karta hai aur top 3 results return karta hai."""
    from vani.browser.search import google_search as _gs
    return await _gs.ainvoke({"query": query})


@tool
async def get_weather(city: str = "") -> str:
    """Current weather batata hai kisi bhi city ka."""
    from vani.services.weather import get_weather as _gw
    return await _gw.ainvoke({"city": city})

# Alias for backward compatibility
def _browser_visible_text(app: str = "") -> str:
    """Alias for _browser_context — backward compat."""
    return _browser_context(app)


# ── Stubs for backward compat with reasoning1.py ─────────────────────────────

def _build_strict_screen_prompt(context: str, query: str) -> str:
    return f"Screen context:\n{context}\n\nQuery: {query}"

def _capture_screen_mss_png() -> bytes:
    try:
        import mss, io
        from PIL import Image
        with mss.mss() as sct:
            raw = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return b""

def _fast_context_is_enough(query: str, context: str) -> bool:
    return bool(context and len(context) > 50)

def _flatten_paddle_result(result) -> str:
    if not result:
        return ""
    lines = []
    for block in result:
        for line in block:
            if isinstance(line, (list, tuple)) and len(line) >= 2:
                text = line[1][0] if isinstance(line[1], (list, tuple)) else str(line[1])
                lines.append(text)
    return "\n".join(lines)

def _format_local_screen_result(query: str, context: str) -> str:
    return f"[Screen] {context[:500]}"

def _get_fast_screen_context(app: str = "") -> str:
    return _browser_context(app) if app else ""

def _get_paddle_ocr():
    try:
        from paddleocr import PaddleOCR
        return PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    except Exception:
        return None

def _ocr_image_macos(png_bytes: bytes) -> str:
    try:
        import subprocess, tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png_bytes)
            tmp = f.name
        result = subprocess.run(
            ["shortcuts", "run", "OCR"], capture_output=True, text=True
        )
        os.unlink(tmp)
        return result.stdout.strip()
    except Exception:
        return ""

def _ocr_image_paddle(png_bytes: bytes) -> str:
    try:
        import numpy as np
        from PIL import Image
        import io
        ocr = _get_paddle_ocr()
        if not ocr:
            return ""
        img = Image.open(io.BytesIO(png_bytes))
        arr = np.array(img)
        result = ocr.ocr(arr, cls=True)
        return _flatten_paddle_result(result)
    except Exception:
        return ""

def _paddleocr_available() -> bool:
    try:
        import paddleocr
        return True
    except ImportError:
        return False

def _preprocess_for_paddleocr(png_bytes: bytes):
    try:
        import numpy as np
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        return np.array(img)
    except Exception:
        return None

def _screen_query_needs_ocr(query: str) -> bool:
    keywords = ["read", "text", "what does", "what is on", "screen", "says", "written"]
    q = query.lower()
    return any(k in q for k in keywords)
