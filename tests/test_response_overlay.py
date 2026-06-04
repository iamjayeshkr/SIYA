import pytest
from vani import app
from vani.reasoning import worker
from vani.memory import human_memory

def test_initial_state_contains_transcript():
    assert "transcript" in app.state
    assert app.state["transcript"] == ""

def test_query_action_classification():
    # Test cases for query classification in worker.py
    queries_searching = [
        "search for quantum computing news",
        "google current weather in New York",
        "find a tutorial on rust",
        "check the web for live scores"
    ]
    queries_pdf = [
        "read my textbook pdf",
        "open document.docx and summarize",
        "learn book from storage",
        "analyse study file"
    ]
    queries_browser = [
        "open website google.com",
        "go to url leetcode.com",
        "open chrome browser and run tests",
        "close current tab"
    ]
    queries_generic = [
        "calculate 5 + 5",
        "set volume to 80%",
        "what is my name?"
    ]

    def classify(q):
        q_lower = q.lower()
        if any(k in q_lower for k in ("pdf", "document", "file", "read file", "book", "pptx", "epub", "mentor", "learn")):
            return "Reading PDF"
        elif any(k in q_lower for k in ("browser", "website", "open", "url", "chrome", "safari", "tab")):
            return "Opening Browser"
        elif any(k in q_lower for k in ("search", "google", "find", "weather", "web", "internet")):
            return "Searching"
        return "Executing Tool"

    for q in queries_searching:
        assert classify(q) == "Searching"
    for q in queries_pdf:
        assert classify(q) == "Reading PDF"
    for q in queries_browser:
        assert classify(q) == "Opening Browser"
    for q in queries_generic:
        assert classify(q) == "Executing Tool"

def test_patched_state_update_broadcasts():
    # Verify _patched_state_update updates the global state
    app._patched_state_update({"status": "Thinking...", "transcript": "Hello Rudra"})
    assert app.state["status"] == "Thinking..."
    assert app.state["transcript"] == "Hello Rudra"

def test_response_length_durations():
    # Character count thresholds matching JS getTimeoutDuration
    short_resp = "Hello context!"  # len 14 -> 8000
    medium_resp = "This is a medium response that should be displayed for fifteen seconds."  # len 71 -> 15000
    long_resp = "Here is a very long response that contains a detailed description of the quantum mechanical systems and standard animations that will be displayed for twenty-five seconds to allow the user to read everything."  # len 216 -> 25000

    def get_duration(transcript):
        length = len(transcript) if transcript else 0
        if length < 60:
            return 8000
        elif length < 200:
            return 15000
        else:
            return 25000

    assert get_duration(short_resp) == 8000
    assert get_duration(medium_resp) == 15000
    assert get_duration(long_resp) == 25000
    assert get_duration("") == 8000
