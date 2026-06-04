"""
vani/reasoning/worker.py
Background asyncio worker: task queue, Twin Brain dispatcher, LiveKit session speech.

── TWIN BRAIN ARCHITECTURE ──────────────────────────────────────────────────
Twin A (TALKER)  = Gemini Realtime session (_session_ref)
                   Speaks to user. Calls thinking_capability() as a tool.
                   Never blocked. Never waits for tools.

Twin B (WORKER)  = PlannerBrain (vani/planner/brain.py)
                   Runs silently inside _run_single_tool().
                   Plans → Executes → Returns result to Twin A to speak.

Flow:
  User speaks → Twin A hears → calls thinking_capability(query)
      → queued in LatestWinsQueue
      → _run_single_tool(query) picks it up
          → PlannerBrain.think_and_execute(query)   ← Worker Twin
              → TaskPlanner classifies intent
              → executor runs the tool via _dispatch_intent
              → result returned to thinking_capability
          → if PlannerBrain returns None → fall through to Qwen (unchanged)
      → result returned to Twin A → Twin A speaks it naturally
─────────────────────────────────────────────────────────────────────────────
"""

import os
import re
import asyncio
import logging

from vani.reasoning.shared import logger
from vani.reasoning.ollama import _qwen_decide_and_run

# ── Worker Twin: lazy import to avoid circular deps at module load ────────────
# PlannerBrain is imported inside _run_single_tool() on first call.
# If import fails, falls back to Qwen — zero breakage.
_PLANNER_BRAIN_AVAILABLE: bool | None = None   # None = not tried yet

try:
    from vani.reasoning.hinglish_speech import normalize_for_tts as _normalize_for_tts
    _HINGLISH_NORMALIZE = True
except ImportError:
    _HINGLISH_NORMALIZE = False
    def _normalize_for_tts(t): return t


# ── LatestWinsQueue ────────────────────────────────────────────────────────────
class LatestWinsQueue:
    """
    A single-slot queue that always keeps only the LATEST instruction.

    Algorithm (Last-Write-Wins):
    ┌──────────────────────────────────────────────────────────────┐
    │  put(item)                                                   │
    │   1. Resolve the pending future (if any) with a STALE        │
    │      sentinel so the worker discards it immediately.         │
    │   2. Cancel the currently-running tool task (if any) so      │
    │      Vanni stops working on the old instruction ASAP.        │
    │   3. Atomically swap _pending_item to the new instruction.   │
    │   4. Signal _event so the worker wakes and picks it up.      │
    │                                                              │
    │  get()   (called by worker loop — awaits until item ready)   │
    │   1. Wait on _event.                                         │
    │   2. Atomically take _pending_item (swap to None).           │
    │   3. Return (query, future).                                 │
    └──────────────────────────────────────────────────────────────┘

    Result:
      • If the user fires 10 instructions while Vanni is busy,
        only the 10th matters — all previous ones are silently dropped.
      • Zero stale replies queued up.
      • Vanni cancels stale in-flight work and jumps to the latest task.
    """

    _STALE = object()   # sentinel: tells a future "you were superseded"

    def __init__(self) -> None:
        self._event: asyncio.Event = asyncio.Event()
        self._pending_item: "tuple[str, asyncio.Future] | None" = None
        self._active_task: "asyncio.Task | None" = None   # currently-running tool task

    # ── called by thinking_capability (producer side) ─────────────────────────

    def put_nowait(self, item: "tuple[str, asyncio.Future]") -> None:
        """Discard any previously-pending item and replace with *item*."""
        # 1. Resolve stale pending future so its caller gets a fast no-op reply
        if self._pending_item is not None:
            _old_query, old_future = self._pending_item
            if not old_future.done():
                old_future.set_result(self._STALE)
            logger.info(f"[LWQ] ⚡ Stale pending task dropped: '{_old_query}'")

        # 2. Cancel the actively-running tool task so we stop wasting cycles
        if self._active_task is not None and not self._active_task.done():
            self._active_task.cancel()
            logger.info("[LWQ] 🛑 Active task cancelled — newer instruction arrived")

        # 3. Swap in the new instruction
        self._pending_item = item
        logger.info(f"[LWQ] ✅ New instruction stored: '{item[0]}'")

        # 4. Wake the worker
        self._event.set()

    async def put(self, item: "tuple[str, asyncio.Future]") -> None:
        """Async put — just calls put_nowait (no blocking needed)."""
        self.put_nowait(item)

    # ── called by _background_worker (consumer side) ──────────────────────────

    async def get(self) -> "tuple[str, asyncio.Future]":
        """Wait until an item is available, then return it atomically."""
        while True:
            await self._event.wait()
            item = self._pending_item
            if item is not None:
                self._pending_item = None
                self._event.clear()
                return item
            # Edge case: another coroutine raced us — loop and wait again
            self._event.clear()

    def task_done(self) -> None:
        """No-op — kept for API compatibility with asyncio.Queue callers."""
        pass

    def set_active_task(self, task: "asyncio.Task | None") -> None:
        """Register the currently-running tool asyncio.Task so it can be cancelled."""
        self._active_task = task

    def cancel_active_task_threadsafe(self) -> None:
        """Thread-safe cancel the active task and clear pending items."""
        if self._active_task is not None and not self._active_task.done():
            try:
                loop = self._active_task.get_loop()
                loop.call_soon_threadsafe(self._active_task.cancel)
                logger.info("[LWQ] Sent cancel signal thread-safely to active task")
            except Exception as e:
                logger.warning(f"[LWQ] Failed to cancel active task thread-safely: {e}")
                try:
                    self._active_task.cancel()
                except Exception:
                    pass
        self._pending_item = None
        self._event.clear()


# ── Session references ────────────────────────────────────────────────────────
_session_ref = None
_session_loop: "asyncio.AbstractEventLoop | None" = None

# ── Worker state ──────────────────────────────────────────────────────────────
_worker_task: "asyncio.Task | None" = None
_task_queue: "LatestWinsQueue | None" = None   # was: asyncio.Queue
_worker_loop: "asyncio.AbstractEventLoop | None" = None
_ollama_semaphore: "asyncio.Semaphore | None" = None  # local ref kept for compat

# ── Parallel tool execution config ────────────────────────────────────────────
# Max concurrent tool tasks. Keep low to avoid overwhelming Ollama/system.
_MAX_PARALLEL_TOOLS = int(os.getenv("VANI_MAX_PARALLEL_TOOLS", "3"))
_parallel_semaphore: "asyncio.Semaphore | None" = None   # bound to running loop
_parallel_semaphore_loop: "asyncio.AbstractEventLoop | None" = None


def _get_parallel_semaphore() -> "asyncio.Semaphore":
    """Return a Semaphore bound to the current loop (recreated on loop change)."""
    global _parallel_semaphore, _parallel_semaphore_loop
    loop = asyncio.get_running_loop()
    if _parallel_semaphore is None or _parallel_semaphore_loop is not loop:
        _parallel_semaphore = asyncio.Semaphore(_MAX_PARALLEL_TOOLS)
        _parallel_semaphore_loop = loop
    return _parallel_semaphore

_THINKING_DESCRIPTION = (
    "Use this for EVERY task the user gives: "
    "open/close apps, open any website or .com URL, play/search YouTube, save notes/plans/reminders, "
    "Google search, check weather, control mouse/keyboard, "
    "write code files, volume control, close browser tabs, "
    "Spotlight search, Talking Tom mode, "
    "read or send WhatsApp messages, make WhatsApp voice/video calls; calls must use the first search result directly, "
    "For WhatsApp contacts, use first name only when possible to save tokens; "
    "read or send Telegram messages, "
    "check Telegram chats, read Mac notifications, "
    "learn name pronunciation (when user says their name or corrects pronunciation), "
    "LEARN/REMEMBER facts, preferences, rules — triggers: yaad rakhna, remember this, seekho, save kar lo, baad mein puchna, bhoolna mat, "
    "READ SCREEN locally/free / analyze screen / screenshot — use for: 'screen dekho', 'read my screen', "
    "'what is on my screen', 'yeh kya hai', 'explain this', 'meri screen dekho', "
    "'code dekh', 'isme issue kya', 'bhai screen dekh', 'screen check kar'. "
    "For Hindi/Hinglish website requests like 'youtube par haule haule se play kardo', "
    "'google dot com kholo', 'chatgpt open karo', 'leetcode two sum open karo', call this tool with the exact user text. "
    "Never answer that tools/browser cannot work before calling this. "
    "Works on Mac and Windows. Runs in background — Vani stays free to talk."
)


def _get_task_queue() -> LatestWinsQueue:
    """Return a LatestWinsQueue bound to the current event loop.

    LiveKit can reconnect and create a new loop; keeping an old queue causes
    voice tool calls to wait forever or crash.

    LatestWinsQueue replaces asyncio.Queue so only the MOST RECENT user
    instruction is ever executed — all stale queued inputs are dropped.
    """
    global _task_queue, _worker_loop
    loop = asyncio.get_running_loop()
    if _task_queue is None or _worker_loop is not loop or loop.is_closed():
        _task_queue = LatestWinsQueue()
        _worker_loop = loop
    return _task_queue


def _ensure_worker():
    """Start background worker exactly once — race-condition safe."""
    global _worker_task, _task_queue, _worker_loop
    loop = asyncio.get_running_loop()
    stale_loop = _worker_loop is not None and _worker_loop is not loop
    if stale_loop:
        _worker_task = None
        _task_queue = None
    if _worker_task is not None and not _worker_task.done():
        return
    try:
        _worker_loop = loop
        _task_queue = LatestWinsQueue()
        _worker_task = loop.create_task(_background_worker())
    except Exception as e:
        logger.warning(f"[Worker] Could not start: {e}")


async def _run_single_tool(query: str, future: "asyncio.Future"):
    """
    Execute one tool call under the parallel semaphore.

    ── Twin Brain dispatch ───────────────────────────────────────────────────
    1. Try Worker Twin (PlannerBrain) first — fast, no LLM needed for known intents
    2. If PlannerBrain returns None → fall through to Qwen (unchanged behaviour)
    3. Talker Twin (Gemini Realtime) receives the result and speaks it naturally
    ─────────────────────────────────────────────────────────────────────────
    """
    global _PLANNER_BRAIN_AVAILABLE

    sem = _get_parallel_semaphore()
    async with sem:
        try:
            logger.info(f"[Worker] ▶ Twin Brain task start: '{query}'")
            # ── Try Worker Twin (PlannerBrain) ────────────────────────────────
            result = None

            if _PLANNER_BRAIN_AVAILABLE is not False:
                try:
                    from vani.planner.brain import PlannerBrain
                    _PLANNER_BRAIN_AVAILABLE = True
                    result = await PlannerBrain.think_and_execute(query)
                    if result is not None:
                        logger.info(f"[Worker] ✅ Worker Twin handled: '{query}'")
                    else:
                        logger.info(f"[Worker] Worker Twin deferred to Qwen: '{query}'")
                except ImportError:
                    _PLANNER_BRAIN_AVAILABLE = False
                    logger.warning("[Worker] PlannerBrain not available — using Qwen only")
                except asyncio.CancelledError:
                    raise   # must propagate
                except Exception as e:
                    logger.warning(
                        f"[Worker] Worker Twin error ({e}) — falling back to Qwen for: '{query}'"
                    )
                    result = None   # explicit: fall through to Qwen

            # ── Fall through to Qwen if Worker Twin didn't handle it ──────────
            if result is None:
                logger.info(f"[Worker] 🧠 Qwen path: '{query}'")
                result = await _qwen_decide_and_run(query)

            # ── Deliver result to Talker Twin ─────────────────────────────────
            timed_out = getattr(future, "_timed_out", False)
            if timed_out:
                # Future was already resolved by timeout — speak result directly
                logger.info(f"[Worker] ✅ Late result for: '{query}'")
                asyncio.create_task(say_to_user(result))
            elif not future.done():
                future.set_result(result)

        except asyncio.CancelledError:
            if not future.done():
                future.set_result("Task cancelled.")
            raise
        except Exception as e:
            logger.error(f"[Worker] Tool error for '{query}': {e}")
            if not future.done():
                future.set_exception(e)
            elif getattr(future, "_timed_out", False):
                asyncio.create_task(say_to_user(f"Ek kaam mein dikkat aayi: {e}"))


async def _background_worker():
    """
    Last-Write-Wins dispatcher — dequeues tasks and runs the LATEST one.

    When a new instruction arrives while one is already running or pending:
      • The pending (not-yet-started) item is discarded immediately.
      • The actively-running tool task is cancelled so Vanni stops wasting
        cycles on stale work and jumps straight to the newest instruction.

    This replaces the old parallel queue model.  A parallel queue caused
    stale instructions to pile up and execute in sequence, making UX worse.
    With Last-Write-Wins only the most recent user intent ever executes.
    """
    logger.info("[Worker] Last-Write-Wins worker started ✅")
    queue = _get_task_queue()

    while True:
        query = future = None
        try:
            query, future = await queue.get()

            # Bail immediately if this item was already superseded
            if future.done():
                logger.info(f"[Worker] ⏭ Skipping stale item: '{query}'")
                queue.task_done()
                continue

            logger.info(f"[Worker] ▶ Executing latest task: '{query}'")

            # Fire off the tool task and register it so it can be cancelled
            task = asyncio.create_task(
                _run_single_tool(query, future),
                name=f"tool:{query[:40]}"
            )
            queue.set_active_task(task)   # ← allows cancellation if user speaks again

            # Await the task.  If the user fires a new instruction mid-flight,
            # the LatestWinsQueue will cancel this task via set_active_task.
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f"[Worker] 🛑 Task cancelled (new instruction took over): '{query}'")
                if not future.done():
                    future.set_result("Naya kaam aa gaya — pehla chhod rahi hoon.")
            finally:
                queue.set_active_task(None)

        except asyncio.CancelledError:
            logger.info("[Worker] Worker cancelled.")
            break
        except Exception as e:
            logger.error(f"[Worker] Dispatcher error: {e}")
            if future and not future.done():
                future.set_exception(e)
        finally:
            if query is not None:
                try:
                    queue.task_done()
                except Exception:
                    pass


# ── Speech helpers ────────────────────────────────────────────────────────────

def _speech_safe_text(text: str, limit: "int | None" = None) -> str:
    """Keep tool results short enough for reliable realtime TTS playback."""
    clean = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    clean = re.sub(r"[*_`#>\-|]+", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    if limit is None or limit <= 0:
        return clean
    if len(clean) <= limit:
        return clean

    sentences = re.split(r"(?<=[.!?।])\s+", clean)
    picked = []
    total = 0
    for sentence in sentences:
        if total + len(sentence) > limit:
            break
        picked.append(sentence)
        total += len(sentence) + 1
    short = " ".join(picked).strip() or clean[:limit].rsplit(" ", 1)[0]
    return short + "... aur bhi hai, poochho toh bataungi."


async def say_to_user(text: str, limit: "int | None" = None):
    global _session_ref
    if not _session_ref:
        logger.warning(f"[MESSAGING] Cannot speak '{text}' - session reference is None.")
        return
    try:
        speech_text = _speech_safe_text(text, limit=limit)
        speech_text = _normalize_for_tts(speech_text)   # ← Hinglish TTS fix
        logger.info(f"[MESSAGING] Speaking to user: {speech_text}")
        # generate_reply works with RealtimeModel; session.say() requires a separate TTS model
        try:
            handle = _session_ref.generate_reply(
                user_input=speech_text,
                allow_interruptions=True,
            )
            if os.getenv("VANI_WAIT_FOR_SPEECH_PLAYOUT", "0") == "1":
                await handle.wait_for_playout()
        except (AttributeError, TypeError):
            # Fallback for non-realtime sessions
            handle = _session_ref.say(speech_text)
            if os.getenv("VANI_WAIT_FOR_SPEECH_PLAYOUT", "0") == "1":
                await handle.wait_for_playout()
    except Exception as e:
        logger.error(f"[MESSAGING] Error in say_to_user: {e}")


def speak_to_user_from_thread(text: str, limit: "int | None" = None) -> bool:
    """Queue speech from non-LiveKit threads such as the local HTTP server."""
    global _session_loop
    if not _session_ref:
        logger.warning(f"[MESSAGING] Cannot queue speech '{text}' - session reference is None.")
        return False
    try:
        if _session_loop and _session_loop.is_running():
            asyncio.run_coroutine_threadsafe(say_to_user(text, limit=limit), _session_loop)
            return True
        else:
            logger.warning("[MESSAGING] Session loop not running — cannot queue speech from thread")
            return False
    except Exception as e:
        logger.error(f"[MESSAGING] Error queueing speech: {e}")
        return False


async def ask_realtime_from_text(text: str) -> bool:
    """Ask the active realtime voice session to answer typed UI text by voice."""
    global _session_ref
    if not _session_ref:
        logger.warning("[TEXT→REALTIME] No active realtime session.")
        return False
    try:
        if os.getenv("VANI_TEXT_INTERRUPT_CURRENT_SPEECH", "1") == "1":
            try:
                await _session_ref.interrupt()
            except Exception:
                pass

        # generate_reply API changed between livekit-agents versions —
        # try the current API first, fall back to say() if not available.
        try:
            handle = _session_ref.generate_reply(
                user_input=text,
                instructions=(
                    "The user typed this in the UI text box. Answer it naturally by voice using "
                    "the realtime Gemini voice. If it is an actionable command, use your available "
                    "tool normally. Do not mention that it was typed unless relevant."
                ),
                allow_interruptions=True,
            )
            if os.getenv("VANI_WAIT_FOR_TEXT_REALTIME_PLAYOUT", "0") == "1":
                await handle.wait_for_playout()
        except (AttributeError, TypeError) as e:
            # generate_reply not available or signature changed — fall back to say()
            logger.warning(f"[TEXT→REALTIME] generate_reply unavailable ({e}), using say()")
            await say_to_user(text, limit=None)

        return True
    except Exception as e:
        logger.error(f"[TEXT→REALTIME] Failed: {e}")
        return False


async def notify_realtime_doc_upload(filename: str) -> bool:
    """
    Non-interrupting voice notification for document upload.
    Unlike ask_realtime_from_text, this does NOT interrupt current speech —
    it waits for Vani to finish before delivering the ack.
    Called from the HTTP handler thread via notify_realtime_doc_upload_thread().
    """
    global _session_ref
    if not _session_ref:
        return False
    try:
        handle = _session_ref.generate_reply(
            user_input=(
                f"Document '{filename}' upload ho gayi hai. "
                f"Briefly acknowledge it in one natural Hinglish sentence and ask what they want to know."
            ),
            instructions=(
                "A document was just uploaded in the background. "
                "Do NOT interrupt anything — deliver this acknowledgment naturally "
                "after current speech finishes. Keep it to one short sentence."
            ),
            allow_interruptions=True,
        )
        # Never wait for playout — fire and forget so HTTP thread is unblocked
        return True
    except (AttributeError, TypeError) as e:
        logger.warning(f"[DOC→REALTIME] generate_reply unavailable ({e}), using say()")
        try:
            asyncio.create_task(say_to_user(
                f"Document {filename} padh li. Kuch poochho.", limit=200
            ))
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error(f"[DOC→REALTIME] Failed: {e}")
        return False


def notify_realtime_doc_upload_thread(filename: str) -> None:
    """
    Fire-and-forget thread-safe bridge for document upload voice ack.
    Returns immediately — never blocks the HTTP handler.
    """
    global _session_loop, _session_ref
    if not _session_ref or not _session_loop or not _session_loop.is_running():
        logger.info("[DOC→REALTIME] No active session — skipping voice ack")
        return
    try:
        # run_coroutine_threadsafe schedules it; we do NOT call .result() —
        # that's what makes this non-blocking.
        asyncio.run_coroutine_threadsafe(
            notify_realtime_doc_upload(filename), _session_loop
        )
    except Exception as e:
        logger.warning(f"[DOC→REALTIME] Schedule failed: {e}")


def ask_realtime_from_text_thread(text: str) -> bool:
    """Thread-safe bridge for /send_text to the active realtime voice session."""
    global _session_loop, _session_ref
    if not text.strip() or not _session_ref:
        return False
    try:
        if _session_loop and _session_loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(ask_realtime_from_text(text), _session_loop)
            submit_timeout = float(os.getenv("VANI_TEXT_REALTIME_SUBMIT_TIMEOUT", "3.0"))
            try:
                return bool(fut.result(timeout=submit_timeout))
            except asyncio.TimeoutError:
                # Timed out waiting for submit — NOT a failure, Gemini is processing.
                # Return True so the caller doesn't also run the text path.
                logger.warning("[TEXT→REALTIME] Submit timed out — Gemini still processing (voice reply incoming)")
                return True
        # No running loop: session exists but loop died — treat as not connected
        logger.warning("[TEXT→REALTIME] Session loop not running — falling back to text path")
        return False
    except Exception as e:
        logger.error(f"[TEXT→REALTIME] Queue failed: {e}")
        return False


def register_session(session):
    global _session_ref, _session_loop
    _session_ref = session
    try:
        _session_loop = asyncio.get_running_loop()
    except RuntimeError:
        _session_loop = None
    logger.info("[MESSAGING] Registered LiveKit session reference ✅")


# ── Public entry point ────────────────────────────────────────────────────────

async def thinking_capability(query: str) -> str:
    """
    Instantly queues task for Qwen2.5:3b background worker.

    Uses Last-Write-Wins: if the user fires another instruction before this
    one executes, this future gets resolved with the STALE sentinel and we
    return immediately with a lightweight ack — no stale reply ever reaches
    the user.

    Vanni never blocks — she can keep talking while the task runs.
    """
    _ensure_worker()

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    await _get_task_queue().put((query, future))

    logger.info(f"[Vani] Task queued (LWQ): '{query}' — Vani is free!")

    try:
        result = await asyncio.wait_for(
            asyncio.shield(future),
            timeout=float(os.getenv("VANI_TOOL_SYNC_TIMEOUT", "2.0"))
        )

        # STALE sentinel — this instruction was superseded by a newer one
        if result is LatestWinsQueue._STALE:
            logger.info(f"[Vani] ⏭ Stale instruction ignored: '{query}'")
            return ""   # silent — user already moved on

        if result:
            return result[:300]

        return "✅ Ho gaya!"

    except asyncio.TimeoutError:
        future._timed_out = True
        return "Kar rahi hoon, tu bol."

    except asyncio.CancelledError:
        logger.info(f"[Vani] Task cancelled (new instruction): '{query}'")
        return ""   # silent drop — user already gave a new command

    except Exception as e:
        return f"Kuch issue: {e}"


_livekit_thinking_tool = None


def get_thinking_capability_tool():
    """Create the LiveKit FunctionTool lazily so text-only imports stay fast."""
    global _livekit_thinking_tool
    if _livekit_thinking_tool is None:
        from livekit.agents import function_tool
        _livekit_thinking_tool = function_tool(
            name="thinking_capability",
            description=_THINKING_DESCRIPTION,
        )(thinking_capability)
    return _livekit_thinking_tool