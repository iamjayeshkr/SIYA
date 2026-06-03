"""
patch_vani.py
Run from your project root:  python patch_vani.py
Patches 3 files + creates teach_bridge.py
"""
import pathlib, sys

ROOT = pathlib.Path(__file__).parent

# ─── 1. router.py ────────────────────────────────────────────────────────────
router = ROOT / "src/vani/reasoning/router.py"
txt = router.read_text()

# 1a. Add _TEACH_RE before _STUDY_START_RE
TEACH_RE_BLOCK = '''_TEACH_RE = __import__("re").compile(
    r"(?:(?:teach|explain|describe|define)\\s+(?:me\\s+)?(?:about\\s+)?"
    r"|(?:samjhao|samjha|padha|padh|sikha|bata|batao)\\s+(?:mujhe\\s+)?"
    r"|(?:what\\s+is|what\\s+are|how\\s+does|how\\s+do|why\\s+is)\\s+"
    r"|(?:kya\\s+hai|kya\\s+hota|kaise\\s+kaam)\\s+"
    r"|(?:diagram|flowchart|mindmap)\\s+(?:of|for|banao)\\s+"
    r"|(?:concept\\s+of|meaning\\s+of|definition\\s+of)\\s+)",
    __import__("re").IGNORECASE,
)

'''
STUDY_ANCHOR = '_STUDY_START_RE = __import__("re").compile('
if '_TEACH_RE' not in txt:
    txt = txt.replace(STUDY_ANCHOR, TEACH_RE_BLOCK + STUDY_ANCHOR)
    print("✅ router.py — _TEACH_RE added")
else:
    print("⏭️  router.py — _TEACH_RE already present")

# 1b. Add TEACH check before final return None, None
TEACH_CHECK = '''    if _TEACH_RE.search(q):
        return "TEACH", {"query": q}

    return None, None'''
if '"TEACH"' not in txt:
    txt = txt.replace("    return None, None", TEACH_CHECK, 1)
    print("✅ router.py — TEACH intent check added")
else:
    print("⏭️  router.py — TEACH check already present")

# 1c. Add TEACH dispatch handler after INSTAGRAM_PROFILE block
TEACH_HANDLER = '''        return f"❌ Instagram profile nahi khula: {result}"

    elif intent == "TEACH":
        from vani.reasoning.teaching_tool import TeachingEngine, build_visual_lesson
        engine = TeachingEngine()
        query = data.get("query", "") if isinstance(data, dict) else str(data)
        lesson = build_visual_lesson(engine, query)
        try:
            from vani.ui.teach_bridge import send_teach_visual
            await send_teach_visual(lesson)
        except Exception:
            pass
        return lesson.get("spoken_response", f"{query} ke baare mein samjhate hain!")'''

IG_TAIL = '        return f"❌ Instagram profile nahi khula: {result}"'
if 'build_visual_lesson' not in txt:
    txt = txt.replace(IG_TAIL, TEACH_HANDLER, 1)
    print("✅ router.py — TEACH dispatch handler added")
else:
    print("⏭️  router.py — TEACH handler already present")

router.write_text(txt)

# ─── 2. teaching_tool.py ─────────────────────────────────────────────────────
tt = ROOT / "src/vani/reasoning/teaching_tool.py"
txt2 = tt.read_text()

BUILD_VISUAL_BLOCK = '''
# ── build_visual_lesson — called by TEACH intent in router.py ─────────────
import json as _json, pathlib as _pathlib, re as _re

_MEMORY_PATHS = [
    _pathlib.Path(__file__).resolve().parents[4] / "vani_working_memory.json",
    _pathlib.Path.cwd() / "vani_working_memory.json",
]

def _load_working_memory() -> dict:
    for p in _MEMORY_PATHS:
        try:
            if p.exists():
                return _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _extract_concept(q: str) -> str:
    c = _re.sub(
        r"^(?:teach\\s+me|explain|samjhao|padha|sikha|bata|batao|"
        r"what\\s+is|what\\s+are|how\\s+does|how\\s+do|kya\\s+hai|"
        r"kya\\s+hota|diagram\\s+of|flowchart\\s+of|concept\\s+of|"
        r"mujhe\\s+|about\\s+|me\\s+|the\\s+)",
        "", q.strip(), flags=_re.IGNORECASE,
    ).strip(" ?!.,")
    c = _re.sub(r"\\s+(kya|hai|hota|samajhna|batao|please)\\s*$", "", c, flags=_re.IGNORECASE)
    return c.strip() or q.strip()

def _infer_visual(q: str) -> str:
    if _re.search(r"\\b(history|timeline|kab|when|chronology|evolution)\\b", q, _re.I):
        return "timeline"
    if _re.search(r"\\b(difference|vs|compare|versus|farak|alag)\\b", q, _re.I):
        return "comparison"
    if _re.search(r"\\b(flow|process|steps?|kaise|cycle|loop)\\b", q, _re.I):
        return "flowchart"
    return "diagram"

_DIAGS = {
    "photosynthesis": (
        "flowchart TD\\n"
        "    Sun[Sunlight] --> Chl[Chlorophyll]\\n"
        "    CO2[CO2 from Air] --> Chl\\n"
        "    Water[Water from Roots] --> Chl\\n"
        "    Chl --> Glucose\\n"
        "    Chl --> O2[Oxygen Released]"
    ),
    "water cycle": (
        "flowchart LR\\n"
        "    Ocean -->|Evaporation| Vapor[Water Vapor]\\n"
        "    Vapor -->|Condensation| Cloud\\n"
        "    Cloud -->|Precipitation| Rain\\n"
        "    Rain --> Ocean"
    ),
    "heart": (
        "flowchart LR\\n"
        "    Body -->|Deoxygenated| RA[Right Atrium]\\n"
        "    RA --> RV[Right Ventricle]\\n"
        "    RV --> Lungs\\n"
        "    Lungs -->|Oxygenated| LA[Left Atrium]\\n"
        "    LA --> LV[Left Ventricle]\\n"
        "    LV --> Body"
    ),
    "democracy": (
        "flowchart TD\\n"
        "    People -->|Vote| Election\\n"
        "    Election --> Govt[Government]\\n"
        "    Govt --> Executive\\n"
        "    Govt --> Legislature\\n"
        "    Govt --> Judiciary"
    ),
    "newton": (
        "flowchart TD\\n"
        "    Newton --> N1[1st Law: Inertia]\\n"
        "    Newton --> N2[2nd Law: F = ma]\\n"
        "    Newton --> N3[3rd Law: Action-Reaction]"
    ),
    "dna": (
        "flowchart TD\\n"
        "    DNA --> Gene[Gene: Segment of DNA]\\n"
        "    Gene -->|Transcription| mRNA\\n"
        "    mRNA -->|Translation| Protein\\n"
        "    Protein --> Trait[Physical Trait]"
    ),
    "cell division": (
        "flowchart TD\\n"
        "    Parent[Parent Cell] --> Prophase\\n"
        "    Prophase --> Metaphase --> Anaphase --> Telophase\\n"
        "    Telophase --> D1[Daughter Cell 1] & D2[Daughter Cell 2]"
    ),
    "digestive system": (
        "flowchart TD\\n"
        "    Food --> Mouth --> Esophagus --> Stomach\\n"
        "    Stomach --> SmallInt[Small Intestine]\\n"
        "    SmallInt --> LargeInt[Large Intestine]\\n"
        "    LargeInt --> Rectum --> Waste[Excretion]"
    ),
}

def build_visual_lesson(engine: "TeachingEngine", query: str) -> dict:
    mem = _load_working_memory()
    active = [
        t.get("text", "").lower()
        for t in mem.get("active_topics", []) + mem.get("pending_reminders", [])
        if t.get("text")
    ]
    concept = _extract_concept(query)
    vtype   = _infer_visual(query)
    lesson  = engine.explain(concept, style="humor")
    c       = concept.lower()
    mcode   = next(
        (v for k, v in _DIAGS.items() if k in c or c in k),
        (
            f"flowchart TD\\n"
            f"    A[{concept}] --> B[What it is]\\n"
            f"    A --> C[How it works]\\n"
            f"    A --> D[Why it matters]"
        ),
    )
    ctx     = (active[0] + " — ") if active else ""
    spoken  = (
        f"{ctx}{concept} ke baare mein samjhate hain! "
        f"Diagram aa raha hai screen pe. "
        f"{lesson.example[:80]}..."
    )
    return {
        "concept":         concept,
        "visual_type":     vtype,
        "mermaid_code":    mcode,
        "spoken_response": spoken,
        "narration":       lesson.narration,
        "memory_context":  active,
        "category":        lesson.category,
        "subject":         lesson.subject,
    }

'''

MAIN_ANCHOR = 'if __name__ == "__main__":'
if 'build_visual_lesson' not in txt2:
    txt2 = txt2.replace(MAIN_ANCHOR, BUILD_VISUAL_BLOCK + MAIN_ANCHOR, 1)
    print("✅ teaching_tool.py — build_visual_lesson() added")
else:
    print("⏭️  teaching_tool.py — build_visual_lesson already present")

tt.write_text(txt2)

# ─── 3. teach_bridge.py (new file) ───────────────────────────────────────────
bridge = ROOT / "src/vani/ui/teach_bridge.py"
if not bridge.exists():
    bridge.write_text('''\
"""
vani/ui/teach_bridge.py
Writes teach_signal.json so ui.html can poll and render the diagram.
"""
import json, time, asyncio, logging, pathlib

logger = logging.getLogger("vani.ui.teach_bridge")
_STATIC_DIR = pathlib.Path(__file__).resolve().parent
TEACH_SIGNAL_PATH = _STATIC_DIR / "teach_signal.json"

async def send_teach_visual(lesson: dict) -> None:
    payload = {
        "ts":             time.time(),
        "concept":        lesson.get("concept", ""),
        "visual_type":    lesson.get("visual_type", "diagram"),
        "mermaid_code":   lesson.get("mermaid_code", ""),
        "narration":      lesson.get("narration", ""),
        "category":       lesson.get("category", ""),
        "subject":        lesson.get("subject", ""),
        "memory_context": lesson.get("memory_context", []),
    }
    def _write():
        try:
            tmp = TEACH_SIGNAL_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(TEACH_SIGNAL_PATH)
        except Exception as e:
            logger.warning("TEACH_BRIDGE write failed: %s", e)
    await asyncio.get_event_loop().run_in_executor(None, _write)
''')
    print("✅ teach_bridge.py — created")
else:
    print("⏭️  teach_bridge.py — already exists")

print("\n✅ All patches applied. Run ./start.sh")
