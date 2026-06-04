import io
import zipfile
import time
import sqlite3
import pytest
from pathlib import Path

from vani.services import document_service
from vani.services import mentor_service
from vani.memory import mentor_memory as mentor_db
from vani.memory import human_memory


def _use_temp_db(tmp_path, monkeypatch):
    # Route all DB calls to the test DB
    test_db_path = tmp_path / "vani_human_memory.sqlite3"
    monkeypatch.setattr(human_memory, "DB_PATH", test_db_path)
    monkeypatch.setattr(mentor_service, "DB_PATH", test_db_path)
    monkeypatch.setattr(mentor_db, "DB_PATH", test_db_path)
    
    # Initialize schema
    conn = sqlite3.connect(test_db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kg_entities (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            type TEXT,
            description TEXT,
            embedding TEXT
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kg_relations (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT,
            confidence REAL DEFAULT 1.0,
            FOREIGN KEY(source_id) REFERENCES kg_entities(id),
            FOREIGN KEY(target_id) REFERENCES kg_entities(id)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kg_citations (
            id TEXT PRIMARY KEY,
            source_url TEXT,
            content_chunk TEXT,
            confidence_score REAL DEFAULT 1.0
        );
        """
    )
    conn.commit()
    conn.close()


# ── Ingestion Parsers Verification (Phase 1) ─────────────────────────────────

def test_extract_epub():
    # Build mock EPUB byte stream
    epub_bio = io.BytesIO()
    with zipfile.ZipFile(epub_bio, "w") as z:
        z.writestr("OEBPS/chapter1.xhtml", "<html><body><h1>Chapter 1</h1><p>EPUB content test</p></body></html>")
        z.writestr("OEBPS/chapter2.html", "<html><body><style>p {color: red;}</style><p>Second page</p></body></html>")
        z.writestr("META-INF/container.xml", "<container></container>") # Ignored
    
    epub_bytes = epub_bio.getvalue()
    extracted = document_service._extract_epub(epub_bytes)
    
    assert "Chapter 1" in extracted
    assert "EPUB content test" in extracted
    assert "Second page" in extracted
    assert "style" not in extracted


def test_extract_pptx():
    # Build mock PPTX byte stream
    pptx_bio = io.BytesIO()
    with zipfile.ZipFile(pptx_bio, "w") as z:
        z.writestr("ppt/slides/slide1.xml", "<p:sld><a:t>Slide 1 Intro</a:t><a:t>Welcome to Vani</a:t></p:sld>")
        z.writestr("ppt/slides/slide2.xml", "<p:sld><a:t>Complexity analysis</a:t></p:sld>")
    
    pptx_bytes = pptx_bio.getvalue()
    extracted = document_service._extract_pptx(pptx_bytes)
    
    assert "=== Slide1 ===" in extracted
    assert "Slide 1 Intro" in extracted
    assert "Welcome to Vani" in extracted
    assert "=== Slide2 ===" in extracted
    assert "Complexity analysis" in extracted


def test_extract_repository():
    # Build mock repository ZIP stream
    repo_bio = io.BytesIO()
    with zipfile.ZipFile(repo_bio, "w") as z:
        z.writestr("src/main.py", "def main():\n    print('hello vani')")
        z.writestr("src/helpers.js", "function run() { return true; }")
        z.writestr(".git/config", "git config core") # Ignored
        z.writestr("node_modules/index.js", "module.exports = {}") # Ignored
        z.writestr("dist/bundle.js", "console.log('build')") # Ignored
        z.writestr("__pycache__/main.pyc", "compiled bytes") # Ignored
    
    repo_bytes = repo_bio.getvalue()
    extracted = document_service._extract_repository(repo_bytes)
    
    assert "=== FILE: src/main.py ===" in extracted
    assert "def main():" in extracted
    assert "=== FILE: src/helpers.js ===" in extracted
    assert "function run()" in extracted
    assert ".git/config" not in extracted
    assert "node_modules" not in extracted
    assert "dist/bundle.js" not in extracted
    assert "__pycache__" not in extracted


# ── Concept Graph & Prerequisite Verification (Phase 2 & 5) ──────────────────

def test_concept_registration_linear_dependencies(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    
    headings = [
        {"type": "chapter", "name": "Chapter 1: Intro", "parent": ""},
        {"type": "section", "name": "1.1 Basics", "parent": "Chapter 1: Intro"},
        {"type": "section", "name": "1.2 Setup", "parent": "Chapter 1: Intro"},
        {"type": "chapter", "name": "Chapter 2: Advanced", "parent": ""}
    ]
    
    concept_ids = mentor_service._register_concepts_in_kg("doc_test", headings)
    
    assert len(concept_ids) == 4
    
    # Verify linear dependency links
    # Concept 0 has no prerequisite
    prereqs_0 = mentor_service.get_concept_prerequisites(concept_ids[0])
    assert len(prereqs_0) == 0
    
    # Concept 1's prerequisite is Concept 0
    prereqs_1 = mentor_service.get_concept_prerequisites(concept_ids[1])
    assert len(prereqs_1) == 1
    assert prereqs_1[0] == concept_ids[0]
    
    # Concept 2's prerequisite is Concept 1
    prereqs_2 = mentor_service.get_concept_prerequisites(concept_ids[2])
    assert len(prereqs_2) == 1
    assert prereqs_2[0] == concept_ids[1]
    
    # Concept 3's prerequisite is Concept 2
    prereqs_3 = mentor_service.get_concept_prerequisites(concept_ids[3])
    assert len(prereqs_3) == 1
    assert prereqs_3[0] == concept_ids[2]


# ── Progressive Processing Ingestion Verification (Phase 2) ──────────────────

def test_progressive_parsing_and_status(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    
    # Mock LLM calls to avoid API dependency
    monkeypatch.setattr(mentor_service, "_call_llm", lambda prompt: "")
    
    doc_text = """Chapter 1: Foundations
1.1 Basic principles of operating systems.
| Table 1: OS properties |
|---|
| CPU | Memory |

```python
def scheduler(): pass
```

flowchart TD
    A[Start] --> B[Run]

$$ E = mc^2 $$
"""
    
    session = mentor_service.start_mentor_session("test.txt", doc_text, roast_mode="Off", mode_type="document")
    doc_id = session["document_id"]
    
    assert session["status"] == "processing"
    assert session["filename"] == "test.txt"
    assert session["coverage_score"] == 0.0
    
    # Wait for background crawler thread to complete
    for _ in range(30):
        time.sleep(0.1)
        sess = mentor_db.get_session(doc_id)
        if sess and sess["status"] in ("ready", "error"):
            break
            
    sess = mentor_db.get_session(doc_id)
    assert sess["status"] == "ready"
    
    # Verify checklist table was populated
    checklist = mentor_db.get_coverage_items(doc_id)
    types = [item["item_type"] for item in checklist]
    
    assert "chapter" in types
    assert "section" in types
    assert "table" in types
    assert "code_block" in types
    assert "diagram" in types
    assert "formula" in types


# ── Adaptive Strategy Switching Verification (Phase 5) ───────────────────────

def test_adaptive_strategy_switching_on_quiz_failures(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    
    # Mock explanation generator response
    narration_mock = "Explanation Text Narration"
    mermaid_mock = "flowchart TD\\nA-->B"
    
    def mock_call_llm(prompt):
        if "quiz" in prompt or "question" in prompt:
            return '{"id": "quiz_1", "question": "What is memory?", "type": "quiz", "options": ["A", "B"], "answer": "A"}'
        if "Evaluate" in prompt:
            return '{"passed": false, "confidence_score": 0.2, "feedback": "Retry, you missed the core concept."}'
        # Else explanation
        return f'{{"narration": "{narration_mock}", "mermaid_code": "{mermaid_mock}"}}'
        
    monkeypatch.setattr(mentor_service, "_call_llm", mock_call_llm)
    
    headings = [{"type": "section", "name": "Concept 1", "parent": ""}]
    session = mentor_service.start_mentor_session("test.txt", "Concept 1 content here", roast_mode="Off")
    doc_id = session["document_id"]
    
    # Wait for crawler thread to complete
    for _ in range(10):
        time.sleep(0.1)
        if mentor_db.get_session(doc_id)["status"] == "ready":
            break
            
    concept_id = mentor_db.get_active_session()["current_concept_id"]
    
    # Attempt 1: First explanation (should be Analogy strategy)
    concept = mentor_service.get_concept_details(concept_id)
    assert concept["attempts"] == 0
    strategy_1 = mentor_service.TEACHING_STRATEGIES[0]
    assert strategy_1 == "Analogy"
    
    # Generate quiz and answer wrong
    quiz = mentor_service.generate_mastery_quiz(concept_id)
    passed, feedback, conf = mentor_service.evaluate_quiz_answer(quiz["id"], "Incorrect Answer")
    assert passed is False
    
    # Concept attempts should now be 1 because we have 1 retention quiz item in database
    concept = mentor_service.get_concept_details(concept_id)
    assert concept["attempts"] == 1
    
    # Attempt 2: Next explanation should switch strategy
    strategy_2 = mentor_service.TEACHING_STRATEGIES[concept["attempts"] % len(mentor_service.TEACHING_STRATEGIES)]
    assert strategy_2 == "Real-world example"
    
    narration, mermaid = mentor_service.generate_concept_explanation(concept_id, strategy_2)
    assert narration == narration_mock


# ── Chapter Checkpoint Verification (Phase 5) ────────────────────────────────

def test_chapter_checkpoint_generation(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    
    checkpoint_narr = "Reviewing this entire chapter summary now."
    checkpoint_q = "Checkpoint connection synthesis query?"
    
    def mock_call_llm(prompt):
        if "Checkpoint review" in prompt or "Chapter Checkpoint review" in prompt:
            return f'{{"narration": "{checkpoint_narr}", "mermaid_code": "flowchart TD\\nChap-->Review"}}'
        if "Checkpoint synthesis" in prompt or "Chapter Checkpoint synthesis" in prompt:
            return f'{{"id": "chk_1", "question": "{checkpoint_q}", "type": "active_recall", "options": [], "answer": "Answer"}}'
        return '{"narration": "Normal", "mermaid_code": "Mindmap"}'
        
    monkeypatch.setattr(mentor_service, "_call_llm", mock_call_llm)
    
    # Register chapter concept
    headings = [{"type": "chapter", "name": "Chapter 1: Core", "parent": ""}]
    session = mentor_service.start_mentor_session("test.txt", "Chapter 1 content", roast_mode="Light")
    doc_id = session["document_id"]
    
    # Wait for background indexing
    for _ in range(10):
        time.sleep(0.1)
        if mentor_db.get_session(doc_id)["status"] == "ready":
            break
            
    concept_id = session["current_concept_id"]
    
    # Generate explanation for the chapter concept itself - should trigger checkpoint review
    narr, m_code = mentor_service.generate_concept_explanation(concept_id, "Analogy")
    assert narr == checkpoint_narr
    
    # Generate quiz for the chapter concept itself - should trigger checkpoint synthesis challenge
    quiz = mentor_service.generate_mastery_quiz(concept_id)
    assert quiz["question"] == checkpoint_q


# ── Final Output Report Compile Verification (Phase 5) ───────────────────────

def test_report_compiles_successfully(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(mentor_service, "_call_llm", lambda prompt: "")
    
    session = mentor_service.start_mentor_session("test.txt", "Chapter 1 Intro\n1.1 Topic\n", roast_mode="Off")
    doc_id = session["document_id"]
    
    # Mock mastery and coverage progress
    mentor_db.update_session(doc_id, coverage_score=100.0, mastery_score=85.0)
    
    report = mentor_service.compile_final_mastery_report(doc_id)
    
    assert "Vani Study Mentor Report: test.txt" in report
    assert "Coverage Score**: 100.0%" in report
    assert "Mastery Score**: 85.0%" in report
    assert "Concept Roadmap Progress" in report
