"""
src/vani/services/automation.py — Automation Scheduler and Background Task runner
"""

from __future__ import annotations
import json
import logging
import time
import os
import threading
import asyncio
from typing import List, Dict, Any, Callable
from vani.config import PROJECT_ROOT

logger = logging.getLogger("vani.services.automation")
AUTOMATION_LOG = PROJECT_ROOT / "conversations" / "automation_log.jsonl"


class AutomationJob:
    def __init__(self, job_id: str, interval_seconds: int, tool_name: str, args: dict) -> None:
        self.id = job_id
        self.interval = interval_seconds
        self.tool_name = tool_name
        self.args = args
        self.last_run = 0.0
        self.status = "idle"  # idle, running, success, failed

    def is_due(self) -> bool:
        return time.time() - self.last_run >= self.interval


class AutomationScheduler:
    """Manages scheduled background automation tasks, verifying permission boundaries."""

    def __init__(self) -> None:
        self.jobs: Dict[str, AutomationJob] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def add_job(self, job_id: str, interval_seconds: int, tool_name: str, args: dict) -> None:
        self.jobs[job_id] = AutomationJob(job_id, interval_seconds, tool_name, args)
        logger.info(f"Scheduled automation job '{job_id}' (every {interval_seconds}s)")

    def remove_job(self, job_id: str) -> None:
        if job_id in self.jobs:
            del self.jobs[job_id]
            logger.info(f"Removed automation job '{job_id}'")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="vani-automation-scheduler")
        self._thread.start()
        logger.info("Automation scheduler background thread started.")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            logger.info("Automation scheduler stopped.")

    def _loop(self) -> None:
        while self._running:
            # Check for due jobs
            for job in list(self.jobs.values()):
                if job.is_due() and job.status != "running":
                    # Execute in a new thread or call run task
                    threading.Thread(target=self._execute_job, args=(job,), daemon=True).start()
            time.sleep(1)

    def _execute_job(self, job: AutomationJob) -> None:
        job.status = "running"
        job.last_run = time.time()
        logger.debug(f"Starting background automation job '{job.id}' calling '{job.tool_name}'")

        success = False
        error_msg = None
        result = ""

        # 1. Verify background permission gate
        from vani.security_state import ToolPermissionGate
        level = ToolPermissionGate.classify_tool(job.tool_name)
        
        # Background automations run unsupervised.
        # Allow SAFE tools automatically. Reject CONFIRM_REQUIRED or SANDBOXED unless config-enabled.
        allow_background = os.getenv("VANI_ALLOW_BACKGROUND_AUTOMATION_TOOLS", "0") == "1"
        
        if level in ("CONFIRM_REQUIRED", "SANDBOXED") and not allow_background:
            error_msg = f"Security: Background execution blocked. Tool {job.tool_name} classified as {level} requires human confirmation."
            logger.warning(f"[AUTOMATION] Job '{job.id}' blocked: {error_msg}")
        else:
            try:
                # Resolve tool and execute synchronously
                from vani.reasoning.registry import get_tool
                tool_fn = get_tool(job.tool_name)
                if not tool_fn:
                    error_msg = f"Tool '{job.tool_name}' not found in registry."
                else:
                    # Run synchronously using a temporary new event loop in this background thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    args = job.args or {}
                    if hasattr(tool_fn, "ainvoke"):
                        res = loop.run_until_complete(tool_fn.ainvoke(args))
                    elif hasattr(tool_fn, "invoke"):
                        res = tool_fn.invoke(args)
                    elif asyncio.iscoroutinefunction(tool_fn):
                        res = loop.run_until_complete(tool_fn(**args) if args else tool_fn())
                    else:
                        res = tool_fn(**args) if args else tool_fn()
                        
                    result = str(res)
                    success = True
                    loop.close()
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error running job '{job.id}': {e}")

        job.status = "success" if success else "failed"

        # 2. Write to automation execution logs
        self._log_execution(job, success, result, error_msg)

    def _log_execution(self, job: AutomationJob, success: bool, result: str, error: Optional[str] = None) -> None:
        try:
            AUTOMATION_LOG.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": time.time(),
                "job_id": job.id,
                "tool_name": job.tool_name,
                "arguments": job.args,
                "success": success,
                "result_preview": result[:150] if result else "",
                "error": error,
            }
            with open(AUTOMATION_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to write automation execution log: {e}")
