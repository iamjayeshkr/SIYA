"""
vani/agents/base_agent.py — Evolved Stateful Base Agent Core

Abstract base class for every VANI specialized agent.
Implements the autonomous think-act-observe-evaluate step loop.
"""

from __future__ import annotations

import logging
import time
import json
import re
import asyncio
from abc import ABC, abstractmethod
from typing import Any, List, Dict, Optional
from enum import Enum


class AgentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"


class BaseAgent(ABC):
    """
    Superclass for all VANI domain agents.
    Implements a stateful Think-Act-Observe-Reflect step loop.
    """

    #: Short slug — used in logging and the AGENT_REGISTRY key.
    name: str = "base"

    #: Human-readable description of what this agent handles.
    description: str = ""

    #: Tool names this agent is responsible for.
    owned_tools: list[str] = []

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"vani.agents.{self.name}")
        self.state = AgentState.IDLE
        self.messages: List[Dict[str, str]] = []
        self.max_steps = 10
        self.current_step = 0

    # ── Stateful step execution loop ──────────────────────────────────────────

    async def run(self, request: str, context: Dict[str, Any] | None = None) -> str:
        """
        Execute the agent's step-based loop to satisfy the user request.
        """
        self.state = AgentState.RUNNING
        self.current_step = 0
        self.messages = [
            {"role": "user", "content": request}
        ]

        self.logger.info(f"[{self.name.upper()}] Starting task execution: '{request}'")

        # Log agent run start
        try:
            from vani.security_state import AuditLogger
            AuditLogger.log_entry(
                agent=self.name,
                action_type="agent_run",
                action_name="start",
                args={"request": request, "context": context},
                status="success"
            )
        except Exception as e:
            self.logger.warning(f"Failed to write start audit log: {e}")

        try:
            while self.current_step < self.max_steps:
                self.current_step += 1
                self.logger.info(f"[{self.name.upper()}] Step {self.current_step}/{self.max_steps}")

                # Prune history if it exceeds context limits
                await self._prune_history()

                # Step 1: Think (construct prompt and invoke Qwen/Gemini)
                prompt = self._build_think_prompt(request, context)
                llm_response = await self._call_llm(prompt)
                self.logger.debug(f"[{self.name.upper()}] Think output: {llm_response}")

                # Parse LLM response into a structured action dict
                action = self._parse_llm_action(llm_response)
                action_type = action.get("action")

                # Step 2: Act & Step 3: Observe
                if action_type == "finish":
                    self.messages.append({"role": "assistant", "content": llm_response})
                    self.state = AgentState.FINISHED
                    response_text = action.get("response", "✅ Task complete.")
                    self.logger.info(f"[{self.name.upper()}] Task finished: {response_text}")
                    
                    # Log agent run finish
                    try:
                        AuditLogger.log_entry(
                            agent=self.name,
                            action_type="agent_run",
                            action_name="finish",
                            args={"response": response_text},
                            status="success"
                        )
                    except Exception:
                        pass

                    # Trigger reflection
                    try:
                        from vani.core.self_improvement import reflect_on_task
                        reflect_on_task(self.name, request, self.messages, success=True)
                    except Exception:
                        pass
                    return response_text

                elif action_type == "tool":
                    tool_name = action.get("name")
                    tool_args = action.get("args", {})
                    self.logger.info(f"[{self.name.upper()}] Act: Calling tool '{tool_name}' with {tool_args}")
                    
                    self.messages.append({"role": "assistant", "content": f"Calling tool {tool_name} with {tool_args}"})

                    # Stuck / loop detection
                    if self.is_stuck():
                        stuck_msg = "Warning: Stuck state detected (repetitive tool calls). Adjusting strategy..."
                        self.logger.warning(f"[{self.name.upper()}] {stuck_msg}")
                        self.messages.append({"role": "system", "content": stuck_msg})
                        continue

                    # Execute tool
                    tool_result = await self._execute_tool(tool_name, tool_args)
                    self.logger.debug(f"[{self.name.upper()}] Observe: Tool result length {len(tool_result)}")
                    self.messages.append({"role": "system", "content": f"Observation from {tool_name}: {tool_result}"})

                elif action_type == "delegate":
                    subagent_name = action.get("name")
                    subagent_query = action.get("query", "")
                    self.logger.info(f"[{self.name.upper()}] Act: Delegating task '{subagent_query}' to agent '{subagent_name}'")
                    
                    self.messages.append({"role": "assistant", "content": f"Delegating '{subagent_query}' to {subagent_name}"})

                    # Log delegation
                    try:
                        AuditLogger.log_entry(
                            agent=self.name,
                            action_type="delegate",
                            action_name=subagent_name,
                            args={"query": subagent_query},
                            status="success"
                        )
                    except Exception:
                        pass

                    # Execute subagent delegation
                    subagent_result = await self._delegate_to_subagent(subagent_name, subagent_query)
                    self.logger.debug(f"[{self.name.upper()}] Observe: Subagent response length {len(subagent_result)}")
                    self.messages.append({"role": "system", "content": f"Observation from sub-agent {subagent_name}: {subagent_result}"})

                else:
                    # Malformed or unparseable JSON action
                    self.logger.warning(f"[{self.name.upper()}] Malformed response format: {llm_response}")
                    
                    # Fallback to direct routing for backward compatibility
                    from vani.reasoning.router import _router_classify
                    intent, data = _router_classify(request)
                    if intent:
                        self.logger.info(f"[{self.name.upper()}] Fallback: Direct routing match for intent '{intent}'")
                        from vani.reasoning.router import _dispatch_intent
                        tool_result = await _dispatch_intent(intent, data, request)
                        self.state = AgentState.FINISHED
                        
                        # Log fallback
                        try:
                            AuditLogger.log_entry(
                                agent=self.name,
                                action_type="agent_run",
                                action_name="fallback",
                                args={"intent": intent},
                                status="success"
                            )
                        except Exception:
                            pass

                        # Trigger reflection
                        try:
                            from vani.core.self_improvement import reflect_on_task
                            reflect_on_task(self.name, request, self.messages, success=True)
                        except Exception:
                            pass
                        return tool_result

                    self.messages.append({"role": "system", "content": "Error: Action format was invalid. Return valid action JSON."})

            self.state = AgentState.FINISHED
            term_msg = f"Terminated: Reached step limit ({self.max_steps}). Final summary: {self.messages[-1].get('content')}"
            try:
                AuditLogger.log_entry(
                    agent=self.name,
                    action_type="agent_run",
                    action_name="limit_reached",
                    args={},
                    status="success"
                )
            except Exception:
                pass

            # Trigger reflection
            try:
                from vani.core.self_improvement import reflect_on_task
                reflect_on_task(self.name, request, self.messages, success=False)
            except Exception:
                pass
            return term_msg

        except Exception as e:
            self.state = AgentState.ERROR
            self.logger.error(f"[{self.name.upper()}] Execution crashed: {e}")
            try:
                AuditLogger.log_entry(
                    agent=self.name,
                    action_type="agent_run",
                    action_name="error",
                    args={},
                    status="failed",
                    error=str(e)
                )
            except Exception:
                pass

            # Trigger reflection
            try:
                from vani.core.self_improvement import reflect_on_task
                reflect_on_task(self.name, request, self.messages, success=False)
            except Exception:
                pass
            raise

    # ── LLM invocation & parsing helpers ──────────────────────────────────────

    async def _call_llm(self, prompt: str) -> str:
        """Call Ollama local generate API asynchronously."""
        url = "http://localhost:11434/api/generate"
        model = "qwen2.5:3b"
        try:
            from vani.reasoning.shared import OLLAMA_URL, OLLAMA_MODEL
            url = OLLAMA_URL
            model = OLLAMA_MODEL
        except ImportError:
            pass

        def _sync_post():
            import requests
            try:
                r = requests.post(url, json={"model": model, "prompt": prompt, "stream": False}, timeout=30)
                if r.status_code == 200:
                    return r.json().get("response", "").strip()
            except Exception as e:
                self.logger.error(f"Ollama connection error: {e}")
            return "{}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_post)

    def _estimate_tokens(self, text: str) -> int:
        """Approximate token count (4 chars ~ 1 token)."""
        return len(text) // 4

    async def _prune_history(self) -> None:
        """
        Summarize/prune message history if it exceeds the target token limit.
        Keeps the initial request, compiles intermediate tool/system responses into
        a concise summary, and retains the last 2 messages.
        """
        total_text = "".join(m.get("content", "") for m in self.messages)
        estimated_tokens = self._estimate_tokens(total_text)
        
        # Limit history to ~3000 estimated tokens (approx 12000 chars) before pruning
        if estimated_tokens < 3000 or len(self.messages) <= 4:
            return

        self.logger.info(f"[{self.name.upper()}] Message history size ({estimated_tokens} tokens) exceeds limit. Summarizing history...")
        
        user_request = self.messages[0]
        recent_messages = self.messages[-2:]
        intermediate_messages = self.messages[1:-2]
        
        intermediate_text = ""
        for idx, m in enumerate(intermediate_messages):
            intermediate_text += f"Step {idx+1} [{m['role'].upper()}]: {m['content']}\n"
            
        summary_prompt = f"""You are a helper for Vanni Agent '{self.name}'.
Summarize the following intermediate execution steps into a single, concise assistant message.
Focus on:
1. What tools were called and what their outcomes were.
2. What subtasks were completed.
Keep the summary under 300 words.

Intermediate Steps:
{intermediate_text}

Summary:"""
        
        summary_response = await self._call_llm(summary_prompt)
        
        self.messages = [
            user_request,
            {"role": "system", "content": f"Summary of previous actions and observations: {summary_response}"},
            *recent_messages
        ]
        self.logger.info(f"[{self.name.upper()}] History successfully pruned and summarized.")

    def _build_think_prompt(self, user_query: str, context: Dict[str, Any] | None = None) -> str:
        """Construct the LLM system prompt injected with tools, subagents, and history."""
        from vani.reasoning.registry import get_tools_for_agent
        tools = get_tools_for_agent(self.name)
        tool_desc = ""
        for name, fn in tools.items():
            doc = fn.__doc__ or ""
            doc = " ".join(doc.strip().split())
            tool_desc += f"- {name}: {doc}\n"

        from vani.agents import list_agents
        subagents_desc = ", ".join(list_agents())

        context_str = ""
        if context:
            context_str = "\nShared State Context (previous steps' results):\n"
            for k, v in context.items():
                val_preview = str(v)[:400] + "..." if len(str(v)) > 400 else str(v)
                context_str += f"- Step {k} Output: {val_preview}\n"

        history_str = ""
        for msg in self.messages:
            history_str += f"[{msg['role'].upper()}]: {msg['content']}\n"

        prompt = f"""You are the Vanni Agent '{self.name}'. {self.description}.
Your goal is to satisfy the user request: '{user_query}'
{context_str}
Available Tools:
{tool_desc}

Available Sub-agents to delegate tasks to:
{subagents_desc}

Current step: {self.current_step}/{self.max_steps}
Execution history:
{history_str}

Decide your next action. Respond ONLY with valid JSON (no markdown fences, no explanation).
Format:
1. To call a tool:
{{"action": "tool", "name": "tool_name", "args": {{"param": "value"}}}}
2. To delegate to a sub-agent:
{{"action": "delegate", "name": "subagent_name", "query": "subtask prompt"}}
3. To finish executing:
{{"action": "finish", "response": "Summary of actions taken and final result"}}

Response:"""
        return prompt

    def _parse_llm_action(self, text: str) -> Dict[str, Any]:
        """Robustly parse the JSON response from the LLM, handling markdown fences."""
        cleaned = text.strip()
        for fence in ["```json", "```"]:
            cleaned = cleaned.replace(fence, "")
        cleaned = cleaned.strip()

        # Try to locate the JSON bounds
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            self.logger.warning(f"Failed to parse LLM action: {text}")
            if "finish" in cleaned.lower():
                return {"action": "finish", "response": text}
            return {"action": "invalid"}

    # ── Act executor helpers ──────────────────────────────────────────────────

    async def _execute_tool(self, name: str, args: dict) -> str:
        """Fetch and execute a registered tool callable after verification and security gating."""
        from vani.reasoning.registry import get_tool
        tool_fn = get_tool(name)
        if not tool_fn:
            err_msg = f"Error: Tool '{name}' not found."
            try:
                from vani.security_state import AuditLogger
                AuditLogger.log_entry(
                    agent=self.name,
                    action_type="tool",
                    action_name=name,
                    args=args,
                    status="failed",
                    error=err_msg
                )
            except Exception:
                pass
            return err_msg

        # Check permissions via the ToolPermissionGate
        try:
            from vani.security_state import ToolPermissionGate, AuditLogger
            permitted, action_desc = ToolPermissionGate.check_permission(name, args)
            if not permitted:
                status = "blocked" if action_desc == "REJECTED_LOCKDOWN" else "requires_confirm"
                AuditLogger.log_entry(
                    agent=self.name,
                    action_type="tool",
                    action_name=name,
                    args=args,
                    status=status,
                    error=f"Permission check returned: {action_desc}"
                )
                return f"Error: Tool execution blocked. Security level: {action_desc}"
        except Exception as e:
            self.logger.error(f"Permission check crashed: {e}")
            return f"Error executing security check: {e}"

        try:
            if hasattr(tool_fn, "ainvoke"):
                result = await tool_fn.ainvoke(args or {})
            elif hasattr(tool_fn, "invoke"):
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: tool_fn.invoke(args or {}))
            elif asyncio.iscoroutinefunction(tool_fn):
                result = await tool_fn(**args) if args else await tool_fn()
            else:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: tool_fn(**args) if args else tool_fn())
            
            result_str = str(result)
            try:
                AuditLogger.log_entry(
                    agent=self.name,
                    action_type="tool",
                    action_name=name,
                    args=args,
                    status="success"
                )
            except Exception:
                pass
            return result_str
        except Exception as e:
            self.logger.error(f"Tool {name} failed: {e}")
            err_str = f"Error executing tool {name}: {e}"
            try:
                AuditLogger.log_entry(
                    agent=self.name,
                    action_type="tool",
                    action_name=name,
                    args=args,
                    status="failed",
                    error=err_str
                )
            except Exception:
                pass
            return err_str

    async def _delegate_to_subagent(self, name: str, query: str) -> str:
        """Call a subagent to execute a subtask."""
        from vani.agents import get_agent
        agent = get_agent(name)
        if not agent:
            return f"Error: Sub-agent '{name}' not found."
        try:
            result = await agent.run(query)
            return result
        except Exception as e:
            self.logger.error(f"Delegation to subagent {name} failed: {e}")
            return f"Error calling subagent {name}: {e}"

    # ── Stuck and loop detection ──────────────────────────────────────────────

    def is_stuck(self) -> bool:
        """Check if the agent is stuck in a repetitive loop."""
        if len(self.messages) < 4:
            return False
        actions = [m for m in self.messages if m["role"] == "assistant"]
        if len(actions) < 3:
            return False
        last_action = actions[-1]["content"]
        duplicates = sum(1 for m in actions[:-1] if m["content"] == last_action)
        return duplicates >= 2

    # ── Legacy/Compatibility Handler ──────────────────────────────────────────

    async def handle(self, intent: str, data: Any, query: str) -> str:
        """
        Execute the task described by (intent, data, query).
        For backward compatibility with raw dispatcher calls.
        """
        from vani.reasoning.router import _dispatch_intent
        return await _dispatch_intent(intent, data, query)

    async def safe_handle(self, intent: str, data: Any, query: str) -> str:
        """
        Wraps handle() with timing and error logging.
        """
        t0 = time.perf_counter()
        try:
            result = await self.handle(intent, data, query)
            elapsed = (time.perf_counter() - t0) * 1000
            self.logger.debug(
                f"[{self.name.upper()}] {intent} → done in {elapsed:.1f}ms"
            )
            return result
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self.logger.error(
                f"[{self.name.upper()}] {intent} failed after {elapsed:.1f}ms: {exc}"
            )
            raise

    # ── Utility ───────────────────────────────────────────────────────────────

    def summary(self) -> str:
        """One-line summary for debugging."""
        tools = ", ".join(self.owned_tools) if self.owned_tools else "direct API"
        return f"{self.name}: {self.description} [{tools}]"

    def __repr__(self) -> str:
        return f"<Agent:{self.name}>"
