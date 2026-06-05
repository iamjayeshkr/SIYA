import json, time, asyncio, logging, pathlib
logger = logging.getLogger("vani.ui.teach_bridge")
_STATIC_DIR = pathlib.Path(__file__).resolve().parent
TEACH_SIGNAL_PATH = _STATIC_DIR / "teach_signal.json"

async def send_teach_visual(lesson: dict) -> None:
    payload = {"ts": time.time(), "concept": lesson.get("concept",""), "visual_type": lesson.get("visual_type","diagram"), "mermaid_code": lesson.get("mermaid_code",""), "narration": lesson.get("narration",""), "category": lesson.get("category",""), "subject": lesson.get("subject",""), "memory_context": lesson.get("memory_context",[])}
    def _write():
        try:
            tmp = TEACH_SIGNAL_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(TEACH_SIGNAL_PATH)
        except Exception as e:
            logger.warning("TEACH_BRIDGE write failed: %s", e)
    await asyncio.get_event_loop().run_in_executor(None, _write)


def clear_teach_visual() -> None:
    try:
        if TEACH_SIGNAL_PATH.exists():
            TEACH_SIGNAL_PATH.unlink()
            logger.info("Cleared teach signal file successfully.")
    except Exception as e:
        logger.warning("Failed to clear teach signal file: %s", e)
