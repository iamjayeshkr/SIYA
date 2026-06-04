"""
src/vani/services/mentor_service.py
═══════════════════════════════════════════════════════════════════════════════
Core Service for Deep Document Mentor Mode.
Manages progressive parsing, adaptive learning loops, dynamic AI explanation,
concept mastery checks, checkpoints, and final markdown report generation.
"""

import re
import os
import json
import time
import asyncio
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from vani.config import PROJECT_ROOT
from vani.memory.human_memory import DB_PATH
import vani.memory.mentor_memory as mentor_db
from vani.ui.teach_bridge import send_teach_visual

logger = logging.getLogger("vani.services.mentor_service")

# ── LLM helper ───────────────────────────────────────────────────────────────

def _call_llm(prompt: str, timeout: int = 45) -> str:
    """Helper to query Gemini API (via HTTP) or fallback to local Ollama."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    if api_key:
        try:
            import requests
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            for model in ("gemini-2.5-flash", "gemini-2.0-flash"):
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                resp = requests.post(url, json=payload, timeout=timeout)
                if resp.status_code == 429:
                    continue
                resp.raise_for_status()
                data = resp.json()
                text = (data.get("candidates", [{}])[0]
                            .get("content", {})
                            .get("parts", [{}])[0]
                            .get("text", ""))
                if text.strip():
                    return text.strip()
        except Exception as e:
            logger.warning(f"[MENTOR_LLM] Gemini request failed: {e}")

    # Fallback to Ollama
    try:
        import requests
        model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        logger.error(f"[MENTOR_LLM] Ollama fallback failed: {e}")
        return ""


# ── Ingestion & Background Processing ────────────────────────────────────────

def _parse_outline_instantly(text: str) -> List[Dict[str, str]]:
    """Parse structure immediately to build a fast roadmap (Pass 1)."""
    headings = []
    lines = text.splitlines()
    chapter_re = re.compile(r"^(?:chapter|unit|module|section|part)\s+([\w.-]+)(?:\s*[:.-]\s*|\s+)(.+)$", re.I)
    numbered_re = re.compile(r"^(\d+(?:\.\d+){0,2})\s+([\w].{4,100})$")
    
    current_chapter = "Intro"
    for line in lines:
        line = line.strip()
        if not line or len(line) < 6 or len(line) > 120:
            continue
        
        m_chap = chapter_re.match(line)
        if m_chap:
            chap_num = m_chap.group(1).strip()
            chap_title = m_chap.group(2).strip()
            current_chapter = f"Chapter {chap_num}: {chap_title}"
            headings.append({"type": "chapter", "name": current_chapter, "parent": ""})
            continue
            
        m_num = numbered_re.match(line)
        if m_num:
            sec_num = m_num.group(1)
            sec_title = m_num.group(2).strip()
            # If sec_num has dots, it's a sub-section
            if "." in sec_num:
                headings.append({"type": "section", "name": f"{sec_num} {sec_title}", "parent": current_chapter})
            else:
                current_chapter = f"Section {sec_num}: {sec_title}"
                headings.append({"type": "chapter", "name": current_chapter, "parent": ""})
                
    # Fallback if no matching structure
    if not headings:
        headings.append({"type": "chapter", "name": "Chapter 1: Core Concepts", "parent": ""})
        headings.append({"type": "section", "name": "1.1 Introduction", "parent": "Chapter 1: Core Concepts"})
        headings.append({"type": "section", "name": "1.2 Core Details", "parent": "Chapter 1: Core Concepts"})
        
    return headings


def _run_background_indexing(document_id: str, text: str):
    """Async background parser to extract tables, math equations, code blocks (Phase 2)."""
    logger.info(f"[MENTOR] Background crawling starting for {document_id}")
    try:
        # 1. Crawl tables
        tables = re.findall(r"(\|.*?\|\r?\n\|[-:| ]*?\|\r?\n(?:\|.*?\|\r?\n)+)", text)
        for i, tbl in enumerate(tables):
            mentor_db.add_coverage_item(document_id, "table", f"Table {i+1}", "Index")
            
        # 2. Crawl code blocks
        code_blocks = re.findall(r"```[a-zA-Z]*\n([\s\S]*?)\n```", text)
        for i, code in enumerate(code_blocks):
            # Extract language or first line to name
            mentor_db.add_coverage_item(document_id, "code_block", f"Code Block {i+1}", "Index")
            
        # 3. Crawl math formulas
        formulas = re.findall(r"(\$\$[\s\S]*?\$\$|\$.*?\$)", text)
        for i, form in enumerate(formulas):
            if len(form) > 10:
                mentor_db.add_coverage_item(document_id, "formula", f"Formula {i+1}", "Index")
                
        # 4. Crawl diagrams
        diagrams = re.findall(r"(?:flowchart|sequenceDiagram|classDiagram|gantt|stateDiagram|erDiagram)[\s\S]*?(?=\n\n|\Z)", text, re.I)
        for i, diag in enumerate(diagrams):
            mentor_db.add_coverage_item(document_id, "diagram", f"Diagram {i+1}", "Index")
            
        # Mark background crawling complete by changing status to 'ready'
        mentor_db.update_session(document_id, status="ready")
        logger.info(f"[MENTOR] Background crawling finished for {document_id}. Total checklist items indexed.")
    except Exception as e:
        logger.exception(f"[MENTOR] Background crawling failed: {e}")
        mentor_db.update_session(document_id, status="error")


# ── Knowledge Graph Integration (Pass 1 & Phase 2) ───────────────────────────

def _register_concepts_in_kg(document_id: str, headings: List[Dict[str, str]]) -> List[str]:
    """Register extracted headings as Concepts and dependencies inside central KG tables."""
    concept_ids = []
    prev_ent_id = None
    
    with sqlite3.connect(DB_PATH) as conn:
        for heading in headings:
            name = heading["name"]
            parent = heading["parent"]
            h_type = heading["type"]
            
            ent_id = f"mentor_ent_{document_id}_{name.lower().replace(' ', '_')}"
            ent_id = re.sub(r"[^\w_-]", "", ent_id)[:64]
            concept_ids.append(ent_id)
            
            # Create entity in central kg_entities
            conn.execute(
                """
                INSERT OR REPLACE INTO kg_entities (id, name, type, description, embedding)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ent_id, name, "MentorConcept", f"{h_type.capitalize()} in {document_id}", "[]"),
            )
            
            # Setup prerequisites and relationships
            if parent:
                parent_id = f"mentor_ent_{document_id}_{parent.lower().replace(' ', '_')}"
                parent_id = re.sub(r"[^\w_-]", "", parent_id)[:64]
                # Inbound relation: Parent -> child (belongs_to)
                rel_id = f"rel_{parent_id}_{ent_id}_child"
                conn.execute(
                    """
                    INSERT OR REPLACE INTO kg_relations (id, source_id, target_id, relation_type, confidence)
                    VALUES (?, ?, ?, 'child', 1.0)
                    """,
                    (rel_id, parent_id, ent_id),
                )
                
            if prev_ent_id:
                # Sequential dependency: absolute predecessor is prerequisite for current concept
                rel_dep_id = f"rel_{prev_ent_id}_{ent_id}_prerequisite"
                conn.execute(
                    """
                    INSERT OR REPLACE INTO kg_relations (id, source_id, target_id, relation_type, confidence)
                    VALUES (?, ?, ?, 'prerequisite', 1.0)
                    """,
                    (rel_dep_id, prev_ent_id, ent_id),
                )
            prev_ent_id = ent_id
        conn.commit()
    return concept_ids


def get_concept_details(concept_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve concept from central kg_entities with dynamically computed attempts."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM kg_entities WHERE id = ?", (concept_id,)).fetchone()
        if row:
            d = dict(row)
            # Count quiz attempts from retention items
            att_row = conn.execute(
                "SELECT COUNT(*) FROM mentor_retention_items WHERE concept_id = ?",
                (concept_id,)
            ).fetchone()
            d["attempts"] = att_row[0] if att_row else 0
            return d
    return None


def get_concept_prerequisites(concept_id: str) -> List[str]:
    """Retrieve list of prerequisite concept IDs for a concept."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT source_id FROM kg_relations
            WHERE target_id = ? AND relation_type = 'prerequisite'
            """,
            (concept_id,),
        ).fetchall()
        return [r["source_id"] for r in rows]


def is_concept_mastered(concept_id: str) -> bool:
    """Check if concept has a high-confidence mastery relation."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT confidence FROM kg_relations
            WHERE target_id = ? AND relation_type = 'mastered' AND source_id = 'user'
            """,
            (concept_id,),
        ).fetchone()
        if row and row["confidence"] >= 0.8:
            return True
    return False


def set_concept_mastered(concept_id: str, confidence: float = 1.0) -> None:
    """Set concept mastery relation in the central KG database."""
    rel_id = f"rel_user_{concept_id}_mastered"
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO kg_relations (id, source_id, target_id, relation_type, confidence)
            VALUES (?, 'user', ?, 'mastered', ?)
            """,
            (rel_id, concept_id, float(confidence)),
        )
        conn.commit()


# ── Start Mentor Session API ─────────────────────────────────────────────────

def start_mentor_session(filename: str, text: str, roast_mode: str = "Off", mode_type: str = "document") -> Dict[str, Any]:
    """Ingest a document/repo, build structure map immediately, and spin background indexing."""
    import hashlib
    document_id = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    
    # Check if session exists
    session = mentor_db.get_session(document_id)
    if session:
        # Re-activate and update roast mode
        roast_int = {"Off": 0, "Light": 1, "Medium": 2, "Savage": 3}.get(roast_mode, 0)
        mentor_db.update_session(document_id, roast_mode=roast_int, created_at=int(time.time()))
        return mentor_db.get_session(document_id)
        
    # Phase 2: Instantly parse outline & build roadmap
    headings = _parse_outline_instantly(text)
    
    # Store session
    roast_int = {"Off": 0, "Light": 1, "Medium": 2, "Savage": 3}.get(roast_mode, 0)
    session_data = mentor_db.create_session(document_id, filename, mode_type=mode_type)
    mentor_db.update_session(document_id, roast_mode=roast_int)
    
    # Register in central Knowledge Graph
    concept_ids = _register_concepts_in_kg(document_id, headings)
    
    # Populate checklist for outline coverage
    for heading in headings:
        mentor_db.add_coverage_item(document_id, "section" if heading["parent"] else "chapter", heading["name"], heading["parent"])
        
    # Update active session pointer
    if concept_ids:
        mentor_db.update_session(document_id, current_concept_id=concept_ids[0])
        
    # Start background crawling (Phase 2 & 9)
    t = threading.Thread(target=_run_background_indexing, args=(document_id, text), name=f"mentor-crawler-{document_id}", daemon=True)
    t.start()
    
    return mentor_db.get_session(document_id)


# ── Adaptive Learning State Machine & Dynamic Prompts (Phase 3 & 5) ──────────

TEACHING_STRATEGIES = [
    "Analogy",
    "Real-world example",
    "Code example",
    "Visual explanation",
    "Story",
    "Mental model",
    "Mathematical explanation",
    "Step-by-step breakdown"
]

def select_next_concept(document_id: str) -> Optional[str]:
    """Select the next concept to teach, satisfying prerequisite dependencies (Phase 5)."""
    # Fetch all concept IDs linked to this document
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id FROM kg_entities WHERE type = 'MentorConcept' AND id LIKE ?",
            (f"mentor_ent_{document_id}_%",),
        ).fetchall()
        concept_ids = [r["id"] for r in rows]
        
    # Find first unmastered concept whose prerequisites are completed
    for cid in concept_ids:
        if is_concept_mastered(cid):
            continue
        prereqs = get_concept_prerequisites(cid)
        if all(is_concept_mastered(pid) for pid in prereqs):
            return cid
            
    # Fallback to first unmastered if loop misses
    for cid in concept_ids:
        if not is_concept_mastered(cid):
            return cid
            
    return None


def get_roast_prompt(level: int) -> str:
    """Return specific prompt instructions based on roast intensity level (Phase 4)."""
    if level == 1:
        return "Light Roast Mode active: Tease the user gently about lazy logic, like a funny senior developer."
    elif level == 2:
        return "Medium Roast Mode active: Be witty, point out mistakes with sarcasm, and push them to explain better, but keep it constructive."
    elif level == 3:
        return "Savage Roast Mode active: Roast their answer, misconceptions, or shortcuts hilariously. Compare their lazy response to something funny. DO NOT be abusive or use bad words, just be savage and educational."
    return "Roast Mode is Off. Be extremely supportive, friendly, and warm."


# Cache references for dynamic generation
_explanations_cache: Dict[str, Dict[str, str]] = {}

def generate_concept_explanation(concept_id: str, strategy: str, level: str = "Beginner") -> Tuple[str, str]:
    """
    Generate dynamic narration and a visual Mermaid diagram for a concept (Phase 3 & 4).
    Explanations are generated progressively on demand and cached.
    """
    cache_key = f"{concept_id}_{strategy}_{level}"
    if cache_key in _explanations_cache:
        return _explanations_cache[cache_key]["narration"], _explanations_cache[cache_key]["mermaid"]
        
    concept = get_concept_details(concept_id)
    if not concept:
        return "Concept details not found.", "flowchart TD\n    A[Error] --> B[Concept Not Found]"
        
    concept_name = concept["name"]
    session = mentor_db.get_active_session()
    roast_level = session["roast_mode"] if session else 0
    roast_instruction = get_roast_prompt(roast_level)
    
    # Check if this is a chapter checkpoint
    doc_id = session["document_id"] if session else ""
    is_chap = False
    if doc_id:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT item_type FROM mentor_coverage_items WHERE document_id = ? AND item_name = ?",
                (doc_id, concept_name)
            ).fetchone()
            is_chap = row and row[0] == "chapter"
            
    if is_chap:
        # Prompt for chapter checkpoint review
        prompt = f"""You are Vani, Rudra's study partner, mentor, and witty senior engineer.
Rudra has completed all sections under the chapter: "{concept_name}".
This is a Chapter Checkpoint review!
Provide a summary of the key takeaways of this chapter, point out common misconceptions, and prepare them for a synthesis challenge.
Tone instructions: {roast_instruction}
Answer in natural Hinglish by default. Keep it highly engaging, conversational, energetic, and simple.
Return a valid JSON object matching this schema:
{{
  "narration": "the written checkpoint summary and warning about the upcoming challenge",
  "mermaid_code": "a summary mindmap/flowchart of the chapter's concepts"
}}
Do not wrap JSON inside ```json...``` blocks, output ONLY raw JSON.
"""
    else:
        # Progressive AI generation prompt
        prompt = f"""You are Vani, Rudra's study partner, mentor, and witty senior engineer.
Explain the concept: "{concept_name}"

Strategy to use: {strategy}
Understanding Level: {level} (Explain logically for a {level})
Tone instructions: {roast_instruction}

Answer in natural Hinglish by default. Keep it highly engaging, conversational, energetic, and simple.
Return a valid JSON object matching this schema:
{{
  "narration": "the written explanation to be read out loud",
  "mermaid_code": "a valid mermaid.js diagram/flowchart illustrating the concept"
}}
Ensure the Mermaid code is structurally correct, uses brackets correctly, and matches theme settings.
Do not wrap JSON inside ```json...``` blocks, output ONLY raw JSON.
"""
    reply = _call_llm(prompt)
    try:
        # Strip code formatting if LLM ignores instruction
        reply_clean = re.sub(r"^```json\s*|\s*```$", "", reply.strip(), flags=re.I)
        data = json.loads(reply_clean)
        narration = data.get("narration", "")
        mermaid = data.get("mermaid_code", "")
        
        # Cache explanation
        _explanations_cache[cache_key] = {"narration": narration, "mermaid": mermaid}
        return narration, mermaid
    except Exception:
        # Default fallback narration if JSON parsing crashes
        fallback_narration = f"Theek hai, let's learn {concept_name} using {strategy} style! {reply[:1200]}"
        fallback_mermaid = f"flowchart TD\n    Concept[📖 {concept_name}] --> Str[{strategy}]"
        return fallback_narration, fallback_mermaid


# ── Concept Mastery Evaluation (Phase 5) ─────────────────────────────────────

def generate_mastery_quiz(concept_id: str) -> Dict[str, Any]:
    """Progressively generate a quiz question on demand for the active concept."""
    concept = get_concept_details(concept_id)
    concept_name = concept["name"] if concept else "Concept"
    
    session = mentor_db.get_active_session()
    doc_id = session["document_id"] if session else ""
    is_chap = False
    if doc_id:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT item_type FROM mentor_coverage_items WHERE document_id = ? AND item_name = ?",
                (doc_id, concept_name)
            ).fetchone()
            is_chap = row and row[0] == "chapter"
            
    if is_chap:
        # Synthesis challenge question
        prompt = f"""Generate a Chapter Checkpoint synthesis quiz question in Hinglish for chapter: "{concept_name}".
This should be a challenging scenario-based or active recall question that tests how the concepts in this chapter connect together.
Return a valid JSON object with the following schema:
{{
  "id": "checkpoint_123",
  "question": "The synthesis checkpoint question text",
  "type": "active_recall",
  "options": [],
  "answer": "The expected explanation of the connection / correct system behavior"
}}
Do not write ```json tags, output raw JSON only.
"""
    else:
        prompt = f"""Generate a study quiz question in Hinglish for concept: "{concept_name}".
Make it an active recall question or a multiple choice quiz (MCQ).
Return a valid JSON object with the following schema:
{{
  "id": "quiz_123",
  "question": "The question text",
  "type": "active_recall" or "quiz",
  "options": ["Option A", "Option B", "Option C", "Option D"], -- empty array if active recall
  "answer": "The correct answer key or description"
}}
Do not write ```json tags, output raw JSON only.
"""
    reply = _call_llm(prompt)
    try:
        reply_clean = re.sub(r"^```json\s*|\s*```$", "", reply.strip(), flags=re.I)
        data = json.loads(reply_clean)
        
        # Save to database
        item_id = f"quiz_{concept_id}_{int(time.time())}"
        mentor_db.add_retention_item(
            item_id,
            concept_id,
            data.get("type", "quiz"),
            data.get("question", ""),
            data.get("answer", ""),
            data.get("options", []),
        )
        return {
            "id": item_id,
            "question": data.get("question", ""),
            "options": data.get("options", []),
            "type": data.get("type", "quiz"),
        }
    except Exception:
        # Fallback question
        item_id = f"quiz_{concept_id}_fallback"
        question = f"Describe what you understand about {concept_name} in your own words."
        mentor_db.add_retention_item(item_id, concept_id, "active_recall", question, "Concept description")
        return {"id": item_id, "question": question, "options": [], "type": "active_recall"}


def evaluate_quiz_answer(item_id: str, user_answer: str) -> Tuple[bool, str, float]:
    """
    Evaluate user response, return (passed, review_feedback, confidence_score).
    Provides wittily educational comments matching Roast Mode.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        item = conn.execute("SELECT * FROM mentor_retention_items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            return False, "Exercise item not found.", 0.0
            
    concept_id = item["concept_id"]
    concept = get_concept_details(concept_id)
    concept_name = concept["name"] if concept else "Concept"
    
    session = mentor_db.get_active_session()
    roast_level = session["roast_mode"] if session else 0
    roast_instruction = get_roast_prompt(roast_level)
    
    prompt = f"""You are Vani, Rudra's study partner.
Evaluate his answer to the question about "{concept_name}".

Question: {item["question"]}
Expected Answer: {item["answer"]}
Rudra's Answer: {user_answer}

Roast level context: {roast_instruction}

Decide if the answer shows real understanding.
Return a valid JSON object matching this schema:
{{
  "passed": true or false,
  "confidence_score": 0.0 to 1.0, -- user's mastery level
  "feedback": "A short, witty, Hinglish response evaluating their answer. Mention errors or roast them constructively if passed is false and Roast Mode is active."
}}
Do not write ```json tags, output raw JSON only.
"""
    reply = _call_llm(prompt)
    try:
        reply_clean = re.sub(r"^```json\s*|\s*```$", "", reply.strip(), flags=re.I)
        data = json.loads(reply_clean)
        
        passed = data.get("passed", False)
        conf = data.get("confidence_score", 0.0)
        feedback = data.get("feedback", "Review checked.")
        
        # Save results in SQLite
        mentor_db.update_retention_response(item_id, user_answer, passed)
        
        # Update concept confidence and mastery status
        if passed and conf >= 0.7:
            set_concept_mastered(concept_id, confidence=conf)
            # Mark concept coverage as completed
            if session:
                mentor_db.mark_coverage_processed(session["document_id"], concept_name, "section")
                # Update overall mastery score (percentage of mastered concepts)
                _recalc_mastery_score(session["document_id"])
        
        return passed, feedback, conf
    except Exception as e:
        logger.warning(f"Failed to parse grading evaluation: {e}")
        return False, "Answer checking system limit. Retry.", 0.0


def _recalc_mastery_score(document_id: str) -> float:
    """Calculate percentage of mastered concepts against total concepts in session."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        # Total concepts
        tot_row = conn.execute(
            "SELECT COUNT(*) FROM kg_entities WHERE type = 'MentorConcept' AND id LIKE ?",
            (f"mentor_ent_{document_id}_%",),
        ).fetchone()
        
        # Mastered concepts
        mas_row = conn.execute(
            """
            SELECT COUNT(DISTINCT target_id) FROM kg_relations
            WHERE relation_type = 'mastered' AND source_id = 'user' AND target_id LIKE ?
            """,
            (f"mentor_ent_{document_id}_%",),
        ).fetchone()
        
        total = tot_row[0] or 0
        mastered = mas_row[0] or 0
        score = (mastered / total) * 100.0 if total > 0 else 0.0
        
        conn.execute(
            "UPDATE mentor_sessions SET mastery_score = ? WHERE document_id = ?",
            (score, document_id),
        )
        conn.commit()
    return score


# ── Final Output Report (Phase 5) ────────────────────────────────────────────

def compile_final_mastery_report(document_id: str) -> str:
    """Compile the final markdown understanding summary (Phase 5)."""
    session = mentor_db.get_session(document_id)
    if not session:
        return "Session details not found."
        
    # Get all concepts
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        concepts = conn.execute(
            "SELECT name, id FROM kg_entities WHERE type = 'MentorConcept' AND id LIKE ?",
            (f"mentor_ent_{document_id}_%",),
        ).fetchall()
        
    roadmap = []
    weak_areas = []
    for c in concepts:
        mastered = is_concept_mastered(c["id"])
        status_symbol = "✅ Mastered" if mastered else "❌ Needs Review"
        roadmap.append(f"- **{c['name']}**: {status_symbol}")
        if not mastered:
            weak_areas.append(f"- {c['name']}")
            
    weak_block = "\n".join(weak_areas) if weak_areas else "None! Sab master kar liya tune! 🎓"
    
    report = f"""# Vani Study Mentor Report: {session["filename"]}
═══════════════════════════════════════════════════════════════════════════════

## Summary Status
* **Document Name**: {session["filename"]}
* **Coverage Score**: {session["coverage_score"]:.1f}%
* **Mastery Score**: {session["mastery_score"]:.1f}%
* **Time Compiled**: {time.strftime('%Y-%m-%d %H:%M:%S')}

## Concept Roadmap Progress
{chr(10).join(roadmap)}

## Concept Dependency Graph
All concepts are linked sequentially. Finish prerequisites before moving forward.

## Weak Areas / Needs Review
{weak_block}

## Flashcards & Quizzes Review
Flashcards and active recall items are saved in the console for your periodic revision.
Great job! Keep practicing active recall to keep these concepts sharp in your memory.
"""
    return report


# ── Specialized Domain Handlers (Phase 3) ────────────────────────────────────

def generate_repository_architecture_report(document_id: str) -> str:
    """Generate high-level architectural overview for Repository Mode (Phase 3)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT item_name FROM mentor_coverage_items WHERE document_id = ? AND item_type = 'section'",
            (document_id,),
        ).fetchall()
        files = [r["item_name"] for r in rows]

    session = mentor_db.get_session(document_id)
    filename = session["filename"] if session else "Repo"
    
    files_list_str = "\n".join(f"- {f}" for f in files[:40])
    if len(files) > 40:
        files_list_str += f"\n- ... and {len(files)-40} more files."

    prompt = f"""You are Vani, a senior software architect. Generate an architectural map and project explanation for: "{filename}".
Identify:
1. System Architecture Pattern (MVC, microservices, monolithic, multi-agent, etc.)
2. Core Components & Folder Responsibilities
3. Service Relationships & Dependencies
4. Event Bus / Messaging flows & Request paths
5. Data flow paths

List of files:
{files_list_str}

Return a structured markdown explanation in natural Hinglish. Keep it highly practical and direct.
"""
    return _call_llm(prompt)


def explain_code_block(code_content: str, detail_level: str = "line-by-line") -> str:
    """Explain a source code snippet with complexity details (Phase 3)."""
    prompt = f"""Explain this code block:
```
{code_content}
```

Format of explanation: {detail_level}
Include:
1. What it does & why it exists
2. How it works
3. Time complexity & space complexity
4. Alternative approaches or patterns
5. Potential bugs, edge cases, and real-world use cases

Output in friendly Hinglish markdown.
"""
    return _call_llm(prompt)


def explain_diagram(diagram_content: str) -> str:
    """Analyze and describe visual illustrations, charts, or flowcharts (Phase 3)."""
    prompt = f"""You are Vani. Analyze this diagram content:
```
{diagram_content}
```
Explain:
1. Core components or nodes
2. Directed relationships and connections
3. Overall meaning and process sequence
4. Real-world importance

Provide a friendly, conversational Hinglish markdown explanation.
"""
    return _call_llm(prompt)


def explain_research_paper(paper_content: str, target_audience: str = "ELI10") -> str:
    """Analyze a research paper with target-audience levels (ELI10, College, Engineer, Researcher)."""
    audience_prompts = {
        "ELI10": "Explain like I'm 10 (extremely simple, analogies, no complex math).",
        "college": "Explain like a college student (focus on concepts, simple logic).",
        "engineer": "Explain like an engineer (focus on implementation, algorithms, practical design).",
        "researcher": "Explain like a researcher (focus on methodology, dataset, limitations, future work)."
    }
    aud_desc = audience_prompts.get(target_audience.lower(), audience_prompts["ELI10"])
    
    prompt = f"""You are Vani. Analyze this research paper excerpt:
```
{paper_content[:15000]}
```

Provide target translation: {aud_desc}
Structure:
- Problem Statement & Objective
- Methodology & Dataset
- Experiments & Results
- Key Limitations & Future Work

Format in beautiful Hinglish markdown.
"""
    return _call_llm(prompt)

