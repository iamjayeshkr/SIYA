"""
vani/reasoning/tools/study_mode.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Vani ka Focus / Study Session feature.

KAISE KAAM KARTA HAI:
  - "study session shuru karte hain" → start_study_session()
    • 50-min countdown timer shuru
    • macOS Do Not Disturb ON (Focus mode)
    • Distracting websites blocked (hosts file ya browser tabs close)
    • Vani strict mode mein aa jaati hai

  - Beech mein koi bhi off-topic baat → Vani daategi
    • is_distraction_query() se check hota hai
    • agar distraction hai → strict daant wali reply milegi

  - Timer poora hota hai → Vani khud bol degi "time up, break le"

  - "study session khatam" / "break lete hain" → end_study_session()
    • DND off, hosts restore, timer cancel

INTEGRATION:
  1. is_study_mode_active() — prompts.py mein check karke
     system prompt mein strict mode block inject karo
  2. is_distraction_query(text) — app.py / worker.py mein
     har user input se pehle check karo

TOOLS REGISTERED:
  - start_study_session  → langchain @tool
  - end_study_session    → langchain @tool
  - study_status         → langchain @tool

ROUTER TRIGGER (router.py mein add karo):
  Patterns: "study.*shuru", "padhai.*start", "focus.*mode",
            "study session", "pomodoro", "50 min.*padh"
"""

import asyncio
import os
import re
import sys
import threading
import subprocess
import logging
from datetime import datetime, timedelta
from typing import Optional
from langchain_core.tools import tool

logger = logging.getLogger("vani.study_mode")

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# ─────────────────────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────────────────────

_study_state: dict = {
    "active":        False,
    "start_time":    None,       # datetime
    "end_time":      None,       # datetime
    "duration_min":  50,
    "subject":       None,       # "maths", "C++", etc — optional
    "timer_task":    None,       # asyncio.Task
    "reminder_task": None,       # asyncio.Task — 25-min halfway nudge
    "break_count":   0,
    "distraction_count": 0,
}

# ─────────────────────────────────────────────────────────────────────────────
# DISTRACTION DETECTION
# ─────────────────────────────────────────────────────────────────────────────

# Topics jo study ke time waste hain
_DISTRACTION_PATTERNS = [
    # Entertainment
    r"\b(movie|film|web series|netflix|hotstar|prime|anime|manga|ott)\b",
    r"\b(game|gaming|pubg|bgmi|valorant|gta|minecraft|cod|free fire)\b",
    r"\b(cricket|ipl|football|match|score|live score)\b",
    r"\b(song|music|gaana|bajao|spotify|youtube.*song|gana)\b",
    r"\b(reel|instagram|insta|tiktok|meme|funny video)\b",
    # Gossip / random chit-chat
    r"\b(aaj kya hua|kya scene hai|bata kuch|bakwaas|timepass)\b",
    r"\b(gossip|celebrity|actor|actress|viral)\b",
    # Food ordering
    r"\b(khana order|swiggy|zomato|order karo|pizza|burger)\b",
    # Social media
    r"\b(whatsapp|telegram|message|chat|reply karo)\b",
    # Sleepy / procrastination signals
    r"\b(neend|nap|so jao|thak gaya|kal kar lena|baad mein)\b",
]

_DISTRACTION_RE = [re.compile(p, re.IGNORECASE) for p in _DISTRACTION_PATTERNS]

# These are always allowed even during study mode
_STUDY_SAFE_PATTERNS = [
    r"\b(doubt|explain|samjhao|concept|question|error|bug|code|kaise|kyun|kya hai)\b",
    r"\b(break|khatam|stop|end session|pomodoro)\b",
    r"\b(time|kitna bcha|kitna hua|progress|timer)\b",
    r"\b(calculator|formula|definition|example)\b",
    r"\b(google search|search karo|look up)\b",
    r"\b(pani|water|fresh air)\b",  # basic human needs — allowed 😂
]

_SAFE_RE = [re.compile(p, re.IGNORECASE) for p in _STUDY_SAFE_PATTERNS]

# Rotating daant responses — variety rakho, monotonous mat ho
_DAANT_RESPONSES = [
    "Abe yaar, abhi padhai chal rahi hai. {topic} baad mein dekh lena. Timer mein {remaining} bache hain.",
    "Seriously?! Abhi {topic}?! Focus karo bhai, {remaining} aur bache hain.",
    "Ek kaam nahi ho raha tera — baith ke padh. {topic} session ke baad.",
    "{remaining} baaki hai aur tu {topic} mein ghus gaya? Wapis aao.",
    "Nahi. Absolutely nahi. Pehle padho, {topic} session khatam hone ke baad.",
    "Main samajh rahi hoon, boring hai. Par {remaining} aur bache hain. Thoda aur.",
    "Bhai agar padh ke {topic} enjoy karna hai toh pehle padho. Deal?",
    "Timer dekha? {remaining} hai. Itna hi toh bacha hai.",
    "Study session chal raha hai. Distraction blocked. {topic}? Later.",
]

_daant_index = 0


def _get_daant(topic: str) -> str:
    global _daant_index
    remaining = _get_remaining_time_str()
    response = _DAANT_RESPONSES[_daant_index % len(_DAANT_RESPONSES)]
    _daant_index += 1
    return response.format(topic=topic, remaining=remaining)


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API — used by prompts.py / app.py
# ─────────────────────────────────────────────────────────────────────────────

def is_study_mode_active() -> bool:
    """prompts.py se call karo — True hone par strict system prompt inject karo."""
    return _study_state["active"]


def get_study_subject() -> Optional[str]:
    return _study_state.get("subject")


def _get_remaining_time_str() -> str:
    if not _study_state["end_time"]:
        return "?"
    delta = _study_state["end_time"] - datetime.now()
    if delta.total_seconds() <= 0:
        return "0 min"
    mins = int(delta.total_seconds() // 60)
    secs = int(delta.total_seconds() % 60)
    if mins > 0:
        return f"{mins} min {secs} sec"
    return f"{secs} sec"


def is_distraction_query(text: str) -> tuple[bool, str]:
    """
    Returns (is_distraction: bool, matched_topic: str).
    Call this BEFORE passing user input to LLM during study mode.

    if is_distraction_query(user_text)[0]:
        return _get_daant(matched_topic)
    """
    if not _study_state["active"]:
        return False, ""

    # Pehle safe patterns check karo — agar study-related hai toh allow karo
    for safe in _SAFE_RE:
        if safe.search(text):
            return False, ""

    # Ab distraction patterns check karo
    for pat in _DISTRACTION_RE:
        m = pat.search(text)
        if m:
            _study_state["distraction_count"] += 1
            # Extract the matched word as the "topic"
            topic = m.group(0).strip()
            return True, topic

    return False, ""


def get_distraction_reply(topic: str) -> str:
    """Ready-made daant reply — worker.py mein use karo say_to_user ke saath."""
    return _get_daant(topic)


def get_study_mode_prompt_block() -> str:
    """
    prompts.py mein inject karo jab study mode active ho.
    Vani ka persona strict ho jaata hai, distractions par daant deti hai.
    """
    if not _study_state["active"]:
        return ""

    subject = _study_state.get("subject") or "current subject"
    remaining = _get_remaining_time_str()
    start_str = _study_state["start_time"].strftime("%I:%M %p") if _study_state["start_time"] else "?"

    return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 STUDY SESSION ACTIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Session started: {start_str}
Subject: {subject}
Time remaining: {remaining}
Distractions attempted: {_study_state['distraction_count']}

STRICT MODE RULES (inhe override mat karna):
- Tu abhi Rudra ki strict study buddy hai, not a casual friend
- Agar koi bhi off-topic cheez mangega (entertainment, games, chat, songs, social media) →
  Seedha daanto. Warm nahi, firm raho. Short and sharp.
- Study se related koi bhi sawaal → full help karo, yahan compromise nahi
- Agar doubt poochhe → explain properly
- Agar confused ho → patiently samjhao lekin distraction allow mat karo
- Encouragement dete raho — har 15-20 min baad casually bolna "chal raha hai, keep going"
- Timer ka update casually dete raho jab relevant ho
- Tone: caring but strict — jaise ek actual padhai wali dost hoti hai
"""


# ─────────────────────────────────────────────────────────────────────────────
# DND / FOCUS MODE (macOS)
# ─────────────────────────────────────────────────────────────────────────────

def _enable_dnd_mac():
    """macOS Focus / Do Not Disturb ON via shortcuts app or defaults."""
    if not IS_MAC:
        return
    try:
        # macOS 12+: shortcuts CLI se Focus mode toggle
        script = (
            'tell application "System Events" to '
            'key code 23 using {command down, option down}'  # ⌘⌥5 = DND toggle on some setups
        )
        # More reliable: use shortcuts app if available
        result = subprocess.run(
            ["shortcuts", "run", "Enable Focus"],
            capture_output=True, timeout=5
        )
        if result.returncode != 0:
            # Fallback: defaults write
            subprocess.run([
                "defaults", "write",
                "com.apple.ncprefs", "dnd_prefs",
                "-dict-add", "userPref", "<dict><key>enabled</key><true/></dict>"
            ], capture_output=True, timeout=5)
            subprocess.run(["killall", "NotificationCenter"], capture_output=True)
        logger.info("[StudyMode] DND enabled on macOS")
    except Exception as e:
        logger.warning(f"[StudyMode] DND enable failed: {e}")


def _disable_dnd_mac():
    """macOS Focus / Do Not Disturb OFF."""
    if not IS_MAC:
        return
    try:
        subprocess.run(
            ["shortcuts", "run", "Disable Focus"],
            capture_output=True, timeout=5
        )
        logger.info("[StudyMode] DND disabled on macOS")
    except Exception as e:
        logger.warning(f"[StudyMode] DND disable failed: {e}")


def _close_distracting_tabs_mac():
    """Close any open YouTube / Instagram / Netflix / Reddit tabs in browsers."""
    if not IS_MAC:
        return
    distract_domains = [
        "youtube.com", "instagram.com", "netflix.com",
        "hotstar.com", "reddit.com", "twitter.com", "x.com",
        "facebook.com", "twitch.tv", "primevideo.com",
    ]
    script_parts = []
    for domain in distract_domains:
        script_parts.append(f"""
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "{domain}" then
                    close t
                end if
            end repeat
        end repeat
        """)

    chrome_script = f"""
    tell application "Google Chrome"
        {"".join(script_parts)}
    end tell
    """
    safari_script = f"""
    tell application "Safari"
        {"".join(script_parts)}
    end tell
    """
    try:
        subprocess.run(["osascript", "-e", chrome_script], capture_output=True, timeout=10)
        subprocess.run(["osascript", "-e", safari_script], capture_output=True, timeout=10)
        logger.info("[StudyMode] Distracting tabs closed")
    except Exception as e:
        logger.warning(f"[StudyMode] Tab cleanup failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TIMER LOGIC
# ─────────────────────────────────────────────────────────────────────────────

async def _study_timer(duration_min: int):
    """
    Background async timer.
    - 25 min pe halfway check-in
    - Session khatam hone par voice alert
    """
    total_secs = duration_min * 60
    halfway = total_secs // 2

    try:
        # Halfway nudge
        await asyncio.sleep(halfway)
        if _study_state["active"]:
            await _speak(
                f"Halfway! {duration_min // 2} minute ho gaye. "
                f"{duration_min // 2} aur bache hain. Keep going! 💪"
            )

        # Second half
        await asyncio.sleep(total_secs - halfway)

        if _study_state["active"]:
            _study_state["active"] = False
            _study_state["end_time"] = datetime.now()

            # DND off
            if IS_MAC:
                threading.Thread(target=_disable_dnd_mac, daemon=True).start()

            await _speak(
                f"Timer poora hua! {duration_min} minute complete. "
                f"Ekdum mast kiya tune! Ab 10 minute ka break le. "
                f"Paani pi, thoda chal, aankhen rest de. "
                f"Break ke baad wapas aajana! 🎉"
            )
            logger.info("[StudyMode] Session completed successfully")

    except asyncio.CancelledError:
        logger.info("[StudyMode] Timer cancelled")


async def _speak(text: str):
    """Say something to user via worker's say_to_user."""
    try:
        from vani.reasoning.worker import say_to_user
        await say_to_user(text)
    except Exception as e:
        logger.warning(f"[StudyMode] speak failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# LANGCHAIN TOOLS
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def start_study_session(subject: str = "", duration_min: int = 50) -> str:
    """
    Study / focus session shuru karta hai.
    - Stopwatch / countdown timer start hota hai (default 50 min)
    - macOS DND / Focus mode ON ho jaata hai
    - Distracting browser tabs band ho jaate hain
    - Vani strict mode mein aa jaati hai
    - Beech mein distraction maango toh daategi

    subject: kya padh rahe ho (optional) — "C++", "maths", "Java" etc
    duration_min: kitne minute ka session chahiye (default 50)

    Triggers: "study session shuru", "padhai start karo", "focus mode on",
              "pomodoro start", "50 min padhai", "concentrate karna hai"
    """
    global _study_state

    if _study_state["active"]:
        remaining = _get_remaining_time_str()
        return (
            f"Study session already chal raha hai! "
            f"{remaining} abhi bache hain. "
            f"Distraction mat le, wapas padho. 📚"
        )

    # Clamp duration
    duration_min = max(10, min(120, duration_min))
    subject = subject.strip() or "current topic"

    now = datetime.now()
    _study_state.update({
        "active":            True,
        "start_time":        now,
        "end_time":          now + timedelta(minutes=duration_min),
        "duration_min":      duration_min,
        "subject":           subject,
        "break_count":       0,
        "distraction_count": 0,
    })

    # Background tasks
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_study_timer(duration_min))
        _study_state["timer_task"] = task
    except RuntimeError:
        pass  # No running loop — timer won't work but session state will

    # macOS setup — background thread mein
    if IS_MAC:
        threading.Thread(
            target=lambda: (
                _enable_dnd_mac(),
                _close_distracting_tabs_mac()
            ),
            daemon=True
        ).start()

    end_time_str = (now + timedelta(minutes=duration_min)).strftime("%I:%M %p")

    return (
        f"Study session start! ⏱️\n"
        f"Subject: {subject}\n"
        f"Duration: {duration_min} min\n"
        f"Khatam hoga: {end_time_str}\n\n"
        f"DND on, distracting tabs band. "
        f"Ab sirf padhai. "
        f"Aage badhte hain — kya se start karna hai?"
    )


@tool
async def end_study_session(reason: str = "") -> str:
    """
    Study session khatam karta hai — manually.
    DND off, timer cancel, session stats show karta hai.

    Triggers: "session khatam", "break lete hain", "study band karo",
              "pomodoro end", "ruk jao", "bas aaj ke liye"
    """
    global _study_state

    if not _study_state["active"]:
        return "Koi study session chal nahi raha abhi."

    # Stats
    start = _study_state["start_time"]
    now = datetime.now()
    elapsed = int((now - start).total_seconds() // 60) if start else 0
    planned = _study_state["duration_min"]
    distractions = _study_state["distraction_count"]

    # Cancel timer
    task = _study_state.get("timer_task")
    if task and not task.done():
        task.cancel()

    # Reset state
    _study_state.update({
        "active":     False,
        "start_time": None,
        "end_time":   None,
        "subject":    None,
        "timer_task": None,
    })

    # DND off
    if IS_MAC:
        threading.Thread(target=_disable_dnd_mac, daemon=True).start()

    # Stats message
    completion_pct = int((elapsed / planned) * 100) if planned > 0 else 0
    if elapsed >= planned:
        verdict = "Full session complete! 🏆 Ekdum mast kiya!"
    elif elapsed >= planned * 0.7:
        verdict = f"Accha kiya! {completion_pct}% session complete hua."
    elif elapsed >= planned * 0.4:
        verdict = f"{elapsed} min padha. Thoda aur hota toh perfect tha."
    else:
        verdict = f"Sirf {elapsed} min? Aaram kar aur wapas aa jaa 😤"

    distraction_note = ""
    if distractions == 0:
        distraction_note = " Zero distractions — legend! 🔥"
    elif distractions <= 2:
        distraction_note = f" {distractions} baar distraction try kiya — decent!"
    else:
        distraction_note = f" {distractions} baar distract hone ki koshish ki... next time focus rakhna. 😒"

    return (
        f"Session khatam ✅\n"
        f"Padha: {elapsed} / {planned} min\n"
        f"{verdict}{distraction_note}\n\n"
        f"Break le. Paani pi. 10 minute baad wapas aa."
    )


@tool
async def study_status() -> str:
    """
    Current study session ka status batata hai — kitna time bcha, subject kya hai.

    Triggers: "kitna time bcha", "session status", "timer check", "kitna hua"
    """
    if not _study_state["active"]:
        return "Abhi koi study session active nahi hai. Shuru karein?"

    remaining = _get_remaining_time_str()
    elapsed_secs = (datetime.now() - _study_state["start_time"]).total_seconds()
    elapsed_min = int(elapsed_secs // 60)
    subject = _study_state.get("subject") or "topic"
    distractions = _study_state["distraction_count"]

    distraction_note = (
        f" Aur {distractions} baar distract hone ki koshish ki 👀" if distractions > 0 else ""
    )

    return (
        f"⏱️ {elapsed_min} min ho gaye, {remaining} bache hain.\n"
        f"Subject: {subject}{distraction_note}\n"
        f"Chal raha hai — keep going! 💪"
    )
