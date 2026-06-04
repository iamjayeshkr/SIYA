"""
tests/test_security.py — Security, Permission Gating, and Auditing Tests
"""

from __future__ import annotations

import os
import json
import pytest
from unittest import mock
from vani.security_state import (
    ToolPermissionGate,
    AuditLogger,
    scrub_secrets,
    validate_environment,
    activate_lockdown,
    deactivate_lockdown,
    is_locked_down
)
from vani.config import PROJECT_ROOT


def test_tool_classification():
    # SAFE tools
    assert ToolPermissionGate.classify_tool("google_search") == "SAFE"
    assert ToolPermissionGate.classify_tool("fetch_stock_price") == "SAFE"
    
    # CONFIRM_REQUIRED tools
    assert ToolPermissionGate.classify_tool("whatsapp_send") == "CONFIRM_REQUIRED"
    assert ToolPermissionGate.classify_tool("crawl_url") == "CONFIRM_REQUIRED"
    
    # SANDBOXED tools
    assert ToolPermissionGate.classify_tool("code_assist") == "SANDBOXED"
    assert ToolPermissionGate.classify_tool("folder_file") == "SANDBOXED"
    
    # Unrecognized default
    assert ToolPermissionGate.classify_tool("unknown_tool") == "CONFIRM_REQUIRED"


def test_permission_gate_flow():
    # Clear any leftover approvals
    ToolPermissionGate.clear_approvals()
    deactivate_lockdown()
    
    # 1. Safe tool should pass automatically
    permitted, action = ToolPermissionGate.check_permission("google_search", {})
    assert permitted is True
    assert action == "SAFE"
    
    # 2. Confirm required tool should fail without approval
    permitted, action = ToolPermissionGate.check_permission("whatsapp_send", {"message": "hello"})
    assert permitted is False
    assert action == "REQUIRES_CONFIRMATION_CONFIRM_REQUIRED"
    
    # 3. Confirm required tool should pass after approval
    ToolPermissionGate.approve_tool_execution("whatsapp_send", {"message": "hello"})
    permitted, action = ToolPermissionGate.check_permission("whatsapp_send", {"message": "hello"})
    assert permitted is True
    assert action == "APPROVED_CONFIRM_REQUIRED"
    
    # 4. Lockdown should reject everything
    activate_lockdown()
    permitted, action = ToolPermissionGate.check_permission("google_search", {})
    assert permitted is False
    assert action == "REJECTED_LOCKDOWN"
    deactivate_lockdown()


def test_secret_scrubbing():
    # Scrub keys in dict
    dirty_dict = {
        "user": "Rudra",
        "api_key": "secret_key_12345",
        "password": "my_secure_password",
        "nested": {
            "token": "bearer_98765",
            "safe_val": 42
        }
    }
    cleaned = scrub_secrets(dirty_dict)
    assert cleaned["user"] == "Rudra"
    assert cleaned["api_key"] == "[SCRUBBED]"
    assert cleaned["password"] == "[SCRUBBED]"
    assert cleaned["nested"]["token"] == "[SCRUBBED]"
    assert cleaned["nested"]["safe_val"] == 42
    
    # Scrub env variable values
    os.environ["TEST_MY_SECRET_PASSWORD"] = "extremely_private_data"
    test_str = "Connecting with extremely_private_data server"
    cleaned_str = scrub_secrets(test_str)
    assert "extremely_private_data" not in cleaned_str
    assert "[SCRUBBED]" in cleaned_str
    
    # Inline regex key-value scrubbing
    dirty_str = "url: 'http://localhost', api_key: 'abcdef12345'"
    cleaned_str = scrub_secrets(dirty_str)
    assert "abcdef12345" not in cleaned_str
    assert "[SCRUBBED]" in cleaned_str


def test_audit_logger():
    # Clean/delete audit log if exists
    log_file = PROJECT_ROOT / "conversations" / "audit_log.jsonl"
    if log_file.exists():
        try:
            log_file.unlink()
        except OSError:
            pass

    # Log a dummy entry with secrets
    args = {"query": "hello", "password": "super_secret"}
    AuditLogger.log_entry(
        agent="test_agent",
        action_type="tool",
        action_name="test_tool",
        args=args,
        status="success"
    )
    
    assert log_file.exists()
    
    # Read the entry
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    assert len(lines) == 1
    entry = json.loads(lines[0])
    
    assert entry["agent"] == "test_agent"
    assert entry["action_type"] == "tool"
    assert entry["action_name"] == "test_tool"
    assert entry["status"] == "success"
    # Arguments must be scrubbed
    assert entry["arguments"]["query"] == "hello"
    assert entry["arguments"]["password"] == "[SCRUBBED]"
    assert "timestamp" in entry


def test_environment_validation():
    # Valid environment check
    with mock.patch.dict(os.environ, {
        "OLLAMA_URL": "http://localhost:11434",
        "VANI_SPEAKER_THRESHOLD": "0.85",
        "VANI_SPEAKER_VERIFY": "1"
    }):
        issues = validate_environment()
        assert len(issues) == 0

    # Invalid URL formatting
    with mock.patch.dict(os.environ, {"OLLAMA_URL": "localhost:11434"}):
        issues = validate_environment()
        assert "OLLAMA_URL" in issues

    # Invalid threshold format
    with mock.patch.dict(os.environ, {"VANI_SPEAKER_THRESHOLD": "not_a_float"}):
        issues = validate_environment()
        assert "VANI_SPEAKER_THRESHOLD" in issues
        
    # Out of range threshold
    with mock.patch.dict(os.environ, {"VANI_SPEAKER_THRESHOLD": "1.5"}):
        issues = validate_environment()
        assert "VANI_SPEAKER_THRESHOLD" in issues
