"""
tests/test_agent_os_extensions.py — Unit tests for Vanni OS Extensions (Phases 6.5–6.12)
"""

from __future__ import annotations

import os
import json
import time
import pytest
from unittest import mock
from pathlib import Path

@pytest.fixture
def anyio_backend():
    return "asyncio"

# Imports of new modules
from vani.domains.manager import DomainManager
from vani.core.self_improvement import (
    reflect_on_task,
    get_pending_suggestions,
    approve_suggestion,
    SUGGESTIONS_FILE,
    AUDIT_LOG_FILE,
    STRATEGIES_FILE,
)
from vani.memory.knowledge_engine import KnowledgeEngine
from vani.planner.project_os import ProjectOS
from vani.reasoning.decision_intelligence import DecisionIntelligence
from vani.core.multimodal import MultimodalOrchestrator
from vani.services.automation import AutomationScheduler
from vani.core.observability import ObservabilityTracker, OBSERVABILITY_LOG


# ── 1. Domain Framework Tests ────────────────────────────────────────────────

def test_domain_manager_loading():
    DomainManager.load_domains()
    domains = DomainManager.get_domains()
    
    # Assert core domains are loaded
    assert "software_engineering" in domains
    assert "cybersecurity" in domains
    assert "business_intelligence" in domains
    assert "education" in domains
    assert "productivity" in domains
    
    # Check that tools from domains were registered in the central registry
    from vani.reasoning.registry import get_tool
    assert get_tool("se_analyze_repository") is not None
    assert get_tool("sec_analyze_logs") is not None
    assert get_tool("bi_generate_swot") is not None
    assert get_tool("edu_generate_quiz") is not None
    assert get_tool("prod_extract_action_items") is not None


# ── 2. Self-Improvement System Tests ─────────────────────────────────────────

def test_self_reflection_and_human_approval_gate():
    # Clean files
    for f in (SUGGESTIONS_FILE, AUDIT_LOG_FILE):
        if f.exists():
            f.unlink()
            
    # Trigger reflection on failure (timeout error)
    reflect_on_task(
        agent_name="coding",
        request="write a script",
        messages=[{"role": "user", "content": "write a script"}, {"role": "system", "content": "Error: timeout occurred"}],
        success=False
    )
    
    # Verify suggestion is queued
    suggestions = get_pending_suggestions()
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s["agent"] == "coding"
    assert "timeout" in s["issue"]
    
    # Approve suggestion
    s_id = s["id"]
    approved = approve_suggestion(s_id)
    assert approved is True
    
    # Verify no more pending suggestions
    assert len(get_pending_suggestions()) == 0
    
    # Verify strategies JSON contains approved parameters
    with open(STRATEGIES_FILE, "r", encoding="utf-8") as f:
        strategies = json.load(f)
    assert "agent_timeout_override::coding" in strategies["approved_parameters"]


# ── 3. Knowledge Engine Tests ────────────────────────────────────────────────

@pytest.mark.anyio
async def test_knowledge_graph_engine(monkeypatch):
    # Mock embedding to avoid local Ollama network calls during tests
    async def mock_embedding(self, text):
        return [0.1, 0.2, 0.3]
    monkeypatch.setattr("vani.memory.vector_store.SQLiteVectorStore.get_embedding", mock_embedding)

    engine = KnowledgeEngine()
    
    # Add entity
    ent_id = await engine.add_entity("Vanni", "Agent OS", "Autonomous assistant operating system")
    assert ent_id == "ent_vanni"
    
    # Add relation
    await engine.add_relation("Vanni", "SQLite", "uses", 0.95)
    
    # Add citation
    await engine.add_citation("https://github.com/vanni", "Vanni code is open-source", 1.0)
    
    # Get relations
    rels = await engine.get_relations("Vanni")
    assert len(rels["outgoing"]) > 0
    assert rels["outgoing"][0]["target_name"] == "SQLite"
    assert rels["outgoing"][0]["relation_type"] == "uses"
    
    # Verify fact
    verification = await engine.verify_fact("Vanni", "uses", "SQLite")
    assert verification["verified"] is True
    assert verification["confidence"] == 0.95


# ── 4. Project OS Tests ──────────────────────────────────────────────────────

def test_project_operating_system():
    pos = ProjectOS()
    if pos.projects_file.exists():
        pos.projects_file.unlink()
        pos.projects.clear()
        
    # Create project
    proj = pos.create_project("Vanni OS", "Implement Phase 6 tasks")
    assert proj.status == "active"
    
    # Add milestone
    ms = pos.add_milestone(proj.id, "Domain Framework")
    assert ms is not None
    
    # Add task
    t1 = pos.add_task(proj.id, ms.id, "Create software_engineering domain", blockers=[])
    t2 = pos.add_task(proj.id, ms.id, "Register tools dynamically", blockers=[t1.id])
    assert t2.blockers == [t1.id]
    
    # Update status & check progress
    pos.update_task_status(proj.id, t1.id, "done")
    assert pos.get_progress(proj.id) == 50.0
    
    # Simulate a dependency blocker failure
    pos.update_task_status(proj.id, t1.id, "failed")
    risks = pos.identify_risks(proj.id)
    assert len(risks) > 0
    assert any("blocked by failed" in r for r in risks)


# ── 5. Decision Support Tests ───────────────────────────────────────────────

def test_decision_intelligence_matrices():
    di = DecisionIntelligence()
    
    options = [
        {"name": "Local Embeddings", "scores": {"cost": 10, "privacy": 10, "setup_speed": 6}},
        {"name": "Cloud Embeddings", "scores": {"cost": 4, "privacy": 3, "setup_speed": 9}},
    ]
    factors = ["cost", "privacy", "setup_speed"]
    weights = {"cost": 0.4, "privacy": 0.4, "setup_speed": 0.2}
    
    # Run scoring evaluation
    brief = di.generate_decision_brief(
        title="Vector Database Choice",
        goal="Select optimal embedding pipeline",
        options=options,
        factors=factors,
        weights=weights
    )
    
    assert "Local Embeddings" in brief
    assert "Cloud Embeddings" in brief
    assert "Weighted Decision Grid" in brief
    assert "We recommend executing" in brief


# ── 6. Multimodal Core Router Tests ──────────────────────────────────────────

def test_multimodal_orchestrator():
    orch = MultimodalOrchestrator()
    
    # Route Image
    img_res = orch.process_file("workspace.jpg")
    assert "workspace layout" in img_res
    
    # Route PDF
    pdf_res = orch.process_file("architecture.pdf")
    assert "architectural diagrams" in pdf_res
    
    # Route Video
    vid_res = orch.process_file("demo.mp4", action="transcribe")
    assert "action items assigned" in vid_res


# ── 7. Automation Platform Tests ─────────────────────────────────────────────

def test_automation_platform_permissions():
    scheduler = AutomationScheduler()
    
    # Safe tools should be allowed
    scheduler.add_job("check_weather", 10, "get_weather", {"city": "Mumbai"})
    job = scheduler.jobs["check_weather"]
    
    with mock.patch.dict(os.environ, {"VANI_ALLOW_BACKGROUND_AUTOMATION_TOOLS": "0"}):
        # We Mock execute_job's inner run_until_complete to avoid executing real network calls
        with mock.patch("vani.services.automation.AUTOMATION_LOG") as mock_log:
            scheduler._execute_job(job)
            assert job.status == "success"  # Because get_weather is in SAFE_TOOLS
            
    # Confirm required tools should be blocked in background by default
    scheduler.add_job("send_msg", 10, "whatsapp_send", {"contact": "Rudra", "message": "hello"})
    job2 = scheduler.jobs["send_msg"]
    
    with mock.patch.dict(os.environ, {"VANI_ALLOW_BACKGROUND_AUTOMATION_TOOLS": "0"}):
        scheduler._execute_job(job2)
        assert job2.status == "failed"  # Blocked due to safety clearance failure


# ── 8. Observability & Operations Tests ──────────────────────────────────────

def test_observability_tracing_and_reporting():
    if OBSERVABILITY_LOG.exists():
        OBSERVABILITY_LOG.unlink()
        
    # Start trace
    trace = ObservabilityTracker.start_trace("se_agent", "analyze_repo")
    
    # Simulate execution duration
    trace.start_time = time.time() - 1.5
    
    # End trace
    ObservabilityTracker.end_trace(trace, success=True, tokens_count=1000)
    
    # Generate reports
    health = ObservabilityTracker.generate_health_report()
    usage = ObservabilityTracker.generate_usage_report()
    failures = ObservabilityTracker.generate_failure_analysis()
    
    assert health["total_runs"] == 1
    assert health["success_rate_percent"] == 100.0
    assert health["mean_duration_s"] >= 1.5
    
    assert usage["total_tokens"] == 1000
    assert usage["total_cost_usd"] > 0.0
    assert usage["agent_tokens_breakdown"]["se_agent"] == 1000
    
    assert failures["total_failures"] == 0
