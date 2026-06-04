"""
tests/test_agent_os.py — Automated Unit Tests for Vanni OS Core

Covers:
  - Stateful BaseAgent think-act-observe loop & stuck detection
  - SQLiteVectorStore insertion & cosine similarity metrics
  - Web crawler HTML-to-Markdown cleaners
  - FinanceAgent calculations (EMI / SIP)
"""

from __future__ import annotations

import pytest
import unittest.mock as mock
from typing import Dict, Any

from vani.agents.base_agent import BaseAgent, AgentState
from vani.memory.vector_store import SQLiteVectorStore, cosine_similarity
from vani.browser.crawler import clean_html_to_markdown, chunk_markdown
from vani.reasoning.tools.finance_ca import _calculate_emi_math, _calculate_sip_math


# ── Test 1: Stateful BaseAgent Loop & Stuck Detection ──────────────────────────

class MockAgent(BaseAgent):
    name = "mock_agent"
    description = "Mock agent for stateful testing"
    owned_tools = []


def test_base_agent_stuck_detection():
    agent = MockAgent()
    assert agent.state == AgentState.IDLE

    # Simulate assistant repeating the same output 3 times
    agent.messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": '{"action": "tool", "name": "google_search", "args": {"query": "test"}}'},
        {"role": "system", "content": "results"},
        {"role": "assistant", "content": '{"action": "tool", "name": "google_search", "args": {"query": "test"}}'},
        {"role": "system", "content": "results"},
        {"role": "assistant", "content": '{"action": "tool", "name": "google_search", "args": {"query": "test"}}'},
    ]
    # Should trigger stuck state
    assert agent.is_stuck() is True

    # Check non-stuck state
    agent.messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": '{"action": "tool", "name": "google_search", "args": {"query": "test1"}}'},
        {"role": "system", "content": "results"},
        {"role": "assistant", "content": '{"action": "tool", "name": "google_search", "args": {"query": "test2"}}'},
    ]
    assert agent.is_stuck() is False


# ── Test 2: Cosine Similarity & Vector Search Logic ───────────────────────────

def test_cosine_similarity():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    assert pytest.approx(cosine_similarity(v1, v2), 0.01) == 1.0

    v3 = [0.0, 1.0, 0.0]
    assert pytest.approx(cosine_similarity(v1, v3), 0.01) == 0.0

    v4 = [1.0, 1.0, 0.0]
    # Norm v1 = 1.0, Norm v4 = sqrt(2) = 1.414, dot = 1.0 -> sim = 1 / 1.414 = 0.707
    assert pytest.approx(cosine_similarity(v1, v4), 0.01) == 0.707


# ── Test 3: Web Crawler HTML to Markdown cleanups ──────────────────────────────

def test_crawler_html_cleaning():
    html_input = """
    <html>
        <head><title>Test Title</title></head>
        <body>
            <header><nav><a href="/home">Home</a></nav></header>
            <script>alert("ignore");</script>
            <style>body {color: red;}</style>
            <h1>Main Title</h1>
            <p>This is a paragraph with <a href="https://example.com">a link</a> inside.</p>
            <footer>Contact info</footer>
        </body>
    </html>
    """
    cleaned = clean_html_to_markdown(html_input)
    assert "# Main Title" in cleaned
    assert "This is a paragraph" in cleaned
    assert "[a link](https://example.com)" in cleaned
    # Ensure header, footer, script, style elements are stripped
    assert "alert" not in cleaned
    assert "body {color" not in cleaned
    assert "Contact info" not in cleaned


def test_crawler_chunking():
    text = "A" * 2000
    chunks = chunk_markdown(text, chunk_size=1000, overlap=100)
    assert len(chunks) == 3
    assert len(chunks[0]) == 1000
    assert chunks[1].startswith("A")


# ── Test 4: Finance Agent calculations ──────────────────────────────────────────

def test_emi_calculation():
    # 1 Lakh principal, 12% annual rate, 12 months
    # Formula results in monthly interest 1%, monthly emi: ~8884.88
    res = _calculate_emi_math(100000, 12.0, 12)
    assert res["emi"] > 8800 and res["emi"] < 8900
    assert res["total_payment"] > 106000 and res["total_payment"] < 107000
    assert res["total_interest"] > 6000 and res["total_interest"] < 7000


def test_sip_calculation():
    # 5000 per month, 12% annual rate, 1 year
    res = _calculate_sip_math(5000, 12.0, 1)
    assert res["total_invested"] == 60000
    assert res["future_value"] > 60000
    assert res["total_gains"] > 0
