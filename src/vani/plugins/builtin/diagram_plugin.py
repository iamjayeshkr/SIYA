"""
vani/plugins/builtin/diagram_plugin.py

Diagram Plugin — Vani draws flowcharts, concept maps, and system diagrams.

What it does:
  • Converts conversation concepts to visual diagrams (HTML/SVG with Mermaid)
  • Opens in browser automatically
  • Supports: flowcharts, mind maps, sequence diagrams, concept trees

Triggers: "diagram banao", "flowchart", "explain visually", "draw this"
"""

from __future__ import annotations
import os
import re
import json
import logging
import sys
import asyncio
import subprocess
import requests
from datetime import datetime
from pathlib import Path

from vani.plugins.registry import VaniPlugin, PluginResult, PluginContext

logger = logging.getLogger("vani.plugins.diagram")


class DiagramPlugin(VaniPlugin):
    name = "diagram"
    icon = "🗺️"
    description = "Draws flowcharts, concept maps, and system diagrams in your browser."
    category = "visual"
    enabled = True
    triggers = [
        "diagram banao", "flowchart banao", "flowchart", "diagram",
        "draw this", "visually explain", "concept map", "mind map",
        "visually dikhao", "chart banao", "explain with diagram",
        "sequence diagram", "architecture diagram", "system diagram",
        "draw a flowchart", "draw a diagram", "dikhao visually",
    ]

    async def on_activate(self, query: str, context: PluginContext) -> PluginResult:
        title = self._extract_title(query, context)

        desktop = Path.home() / "Desktop"
        desktop.mkdir(exist_ok=True)
        now = datetime.now().strftime("%d%b%Y_%H%M")
        safe_title = re.sub(r'[^\w]', '_', title)[:30]
        filename = f"Vani_Diagram_{safe_title}_{now}.html"
        filepath = desktop / filename

        # Write placeholder HTML immediately (with spinner and auto-refresh)
        placeholder_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vani Diagram — Generating...</title>
<style>
  body {{
    background: #0f0a1e; color: #e2e8f0; font-family: sans-serif;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    height: 100vh; margin: 0;
  }}
  .spinner {{
    border: 4px solid rgba(255,255,255,0.1); width: 50px; height: 50px;
    border-radius: 50%; border-left-color: #7c3aed;
    animation: spin 1s linear infinite;
  }}
  @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
</style>
<script>
  setTimeout(function() {{ window.location.reload(); }}, 1500);
</script>
</head>
<body>
  <div class="spinner"></div>
  <h2 style="margin-top: 20px;">🗺️ Vani is drawing your diagram...</h2>
  <p style="color: #64748b;">Please wait, generating custom Mermaid flowchart in background.</p>
</body>
</html>"""
        filepath.write_text(placeholder_html, encoding="utf-8")

        # Open in browser immediately
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(filepath)])
            elif sys.platform == "win32":
                os.startfile(str(filepath))
            else:
                subprocess.Popen(["xdg-open", str(filepath)])
        except Exception:
            pass

        # Define background task to run diagram building and update file
        async def _generate_diagram_bg():
            loop = asyncio.get_running_loop()
            diag_type, mermaid_code = await loop.run_in_executor(None, self._build_diagram, query, context)
            final_html = self._render_html(title, diag_type, mermaid_code)
            filepath.write_text(final_html, encoding="utf-8")

        # Launch background task
        asyncio.create_task(_generate_diagram_bg())

        return PluginResult(
            success=True,
            message=f"🗺️ Diagram ready ho raha hai! Browser mein '{title}' khul gaya hai.",
            artifact_path=str(filepath),
            artifact_type="html",
            ui_payload={
                "diagram_type": "flowchart",
                "title": title,
                "filename": filename,
                "mermaid_code": "Generating...",
            }
        )

    def _extract_title(self, query: str, context: PluginContext) -> str:
        # Check if query contains Save_Note or is a Python tool call string
        if len(query) > 100 or "Save_Note" in query or "{" in query:
            match = re.search(r"Title=['\"](.*?)['\"]", query, re.IGNORECASE)
            if match:
                extracted = match.group(1).strip()
                if extracted:
                    return extracted
            
            recent_text = " ".join(m.get("content", "") for m in context.recent_messages[-3:]).lower()
            if "two pointer" in recent_text:
                return "Two Pointer Flowchart"
            if "three sum" in recent_text:
                return "Three Sum Flowchart"
            if "procedural" in recent_text:
                return "Procedural Flowchart"
            return "Concept Diagram"

        # Look for topic in last few messages
        recent_text = " ".join(
            m.get("content", "") for m in context.recent_messages[-4:]
        )
        for pattern in [
            r'(?:about|for|of|explain|regarding)\s+([A-Z][a-zA-Z\s]{3,30})',
            r'([A-Z][a-zA-Z\s]{4,25})\s+(?:kya hai|explain|diagram)',
        ]:
            m = re.search(pattern, recent_text)
            if m:
                return m.group(1).strip()
        
        # Clean up query triggers to get a nicer fallback title
        q = query
        for trigger in self.triggers:
            if trigger in q.lower():
                q = re.sub(re.escape(trigger), "", q, flags=re.IGNORECASE)
        # Strip leading verbs, request phrases and articles
        q = re.sub(r"^(?:make|create|draw|design|write|show|generate|build|give|save)\s+(?:me\s+)?(?:a\s+|an\s+)?", "", q, flags=re.IGNORECASE)
        # Clean up double spaces or leading/trailing prepositions
        q = re.sub(r"^\s*(?:for|of|about|to)\s+", "", q, flags=re.IGNORECASE)
        q = re.sub(r"\s+", " ", q)
        q = q.strip().title()
        if len(q) > 3:
            return q
        return "Concept Diagram"

    def _generate_mermaid_via_llm(self, query: str, context: PluginContext) -> tuple[str, str] | None:
        # Build prompt using recent messages
        recent = context.recent_messages[-6:] if context.recent_messages else []
        conversation_context = ""
        for msg in recent:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            conversation_context += f"{role.upper()}: {content}\n"
            
        system_prompt = (
            "You are an expert Mermaid diagram designer.\n"
            "Generate a highly detailed and visually appealing Mermaid diagram based on the user request and conversation history.\n"
            "Rules:\n"
            "1. Output ONLY the Mermaid diagram code. Do not write any explanations, notes, or normal text.\n"
            "2. Wrap your output in a markdown block starting with ```mermaid and ending with ```. If you cannot do a block, just output the raw Mermaid diagram text.\n"
            "3. Support standard diagrams like flowchart (flowchart TD / flowchart LR), mindmap (mindmap), or sequence diagram (sequenceDiagram).\n"
            "4. Do NOT use any backslashes inside node labels.\n"
            "5. Make it rich, detailed, and directly answering the user's specific context.\n"
            "6. Make sure the nodes have proper styles if relevant (e.g. style A fill:#7c3aed,color:#fff)."
        )
        
        user_prompt = (
            f"Conversation History:\n{conversation_context}\n"
            f"User request: {query}\n\n"
            "Provide the Mermaid diagram code now:"
        )
        
        try:
            model_name = self._get_best_ollama_model()
            full_prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
            r = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model_name,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 500
                    }
                },
                timeout=12
            )
            r.raise_for_status()
            response_text = r.json().get("response", "").strip()
            if not response_text:
                return None
            
            # Extract Mermaid code
            mermaid_code = response_text
            # Try to extract code between ```mermaid and ```
            mermaid_match = re.search(r'```mermaid\s*(.*?)\s*```', response_text, re.DOTALL | re.IGNORECASE)
            if mermaid_match:
                mermaid_code = mermaid_match.group(1).strip()
            else:
                generic_match = re.search(r'```\s*(.*?)\s*```', response_text, re.DOTALL)
                if generic_match:
                    mermaid_code = generic_match.group(1).strip()
            
            # Sanity check
            lower_code = mermaid_code.lower()
            if not any(x in lower_code for x in ["flowchart", "graph", "sequenceboard", "sequencediagram", "mindmap", "classdiagram", "gantt", "pie"]):
                return None
                
            # Classify diagram type
            diagram_type = "flowchart"
            if "mindmap" in lower_code:
                diagram_type = "mindmap"
            elif "sequence" in lower_code:
                diagram_type = "sequence"
                
            return diagram_type, mermaid_code
        except Exception as e:
            logger.warning(f"Failed to generate Mermaid via Ollama: {e}")
            return None

    def _build_diagram(self, query: str, context: PluginContext) -> tuple[str, str]:
        """
        Detect diagram type and build Mermaid syntax from conversation context.
        Returns (diagram_type, mermaid_code).
        """
        llm_result = self._generate_mermaid_via_llm(query, context)
        if llm_result:
            logger.info("Successfully generated diagram using Ollama LLM.")
            return llm_result

        logger.info("Ollama generation failed or returned invalid Mermaid. Falling back to templates.")
        q = query.lower()
        recent = context.recent_messages[-6:]
        all_text = " ".join(m.get("content", "") for m in recent)

        if any(x in q for x in ["sequence", "flow", "step", "process", "steps"]):
            return "flowchart", self._flowchart_from_text(all_text, query)
        if any(x in q for x in ["mind map", "concept map", "topic"]):
            return "mindmap", self._mindmap_from_text(all_text, query)
        if any(x in q for x in ["sequence diagram", "api", "service", "request", "response"]):
            return "sequence", self._sequence_from_text(all_text, query)
        return "flowchart", self._flowchart_from_text(all_text, query)

    def _flowchart_from_text(self, text: str, query: str) -> str:
        """Build a generic flowchart. Tries to extract steps, falls back to template."""
        q = (query + " " + text).lower()
        
        if "two pointer" in q or "two-pointer" in q:
            return """flowchart TD
    A([🚀 Two Pointer Approach]) --> B[Initialize: Left = 0, Right = N-1]
    B --> C{Loop: While Left < Right}
    C -- Yes --> D{Compare elements at Left & Right}
    D -- Condition Met --> E[Update result / Return]
    D -- Value too small/large --> F[Move Left pointer right OR Right pointer left]
    F --> C
    C -- No --> G([🎯 End / Result Not Found])
    style A fill:#7c3aed,color:#fff
    style G fill:#16a34a,color:#fff
    style C fill:#0369a1,color:#fff"""

        if "procedural" in q:
            return """flowchart TD
    A([🚀 Procedural Approach]) --> B[Step 1: Get Inputs / Parameters]
    B --> C[Step 2: Execute Sequential Function Calls]
    C --> D[Step 3: Modify Global/Local States]
    D --> E[Step 4: Output / Return Results]
    E --> F([🎯 End])
    style A fill:#7c3aed,color:#fff
    style F fill:#16a34a,color:#fff
    style C fill:#0369a1,color:#fff"""
            
        if "sliding window" in q:
            return """flowchart TD
    A([🚀 Sliding Window]) --> B[Initialize: Start = 0, End = 0]
    B --> C{Loop: While End < Array Length}
    C -- Yes --> D[Expand window: include element at End]
    D --> E{Is window valid?}
    E -- No --> F[Contract window: increment Start]
    F --> E
    E -- Yes --> G[Update max/min result]
    G --> H[Increment End]
    H --> C
    C -- No --> I([🎯 End / Return result])
    style A fill:#7c3aed,color:#fff
    style I fill:#16a34a,color:#fff
    style C fill:#0369a1,color:#fff"""

        steps = re.findall(r'\d+[\.\)]\s+(.+?)(?=\d+[\.\)]|$)', text, re.DOTALL)
        steps = [s.strip()[:40] for s in steps if len(s.strip()) > 3][:8]

        if steps:
            lines = ["flowchart TD", '    A([🚀 Start]) --> B']
            prev = "B"
            for i, step in enumerate(steps):
                node = chr(67 + i)
                lines.append(f'    {prev}["{step}"] --> {node}')
                prev = node
            lines.append(f'    {prev}([🎯 End])')
            lines.append("    style A fill:#7c3aed,color:#fff")
            return "\n".join(lines)

        # Generic concept flowchart template
        return """flowchart TD
    A([🧠 Concept]) --> B[Understand]
    B --> C[Break it Down]
    C --> D[Key Components]
    D --> E1[Part 1]
    D --> E2[Part 2]
    D --> E3[Part 3]
    E1 --> F[Apply]
    E2 --> F
    E3 --> F
    F --> G([✅ Master It])
    style A fill:#7c3aed,color:#fff
    style G fill:#16a34a,color:#fff
    style D fill:#0369a1,color:#fff"""

    def _mindmap_from_text(self, text: str, query: str) -> str:
        words = re.findall(r'\b[A-Z][a-z]{3,15}\b', text)
        unique = list(dict.fromkeys(words))[:6]
        center = unique[0] if unique else "Topic"
        branches = unique[1:6] if len(unique) > 1 else ["Concept A", "Concept B", "Concept C"]
        lines = ["mindmap", f"  root(({center}))"]
        for b in branches:
            lines.append(f"    {b}")
        return "\n".join(lines)

    def _sequence_from_text(self, text: str, query: str) -> str:
        return """sequenceDiagram
    participant U as 👤 User
    participant A as 🤖 Vani
    participant S as ⚡ Service
    U->>A: Request
    A->>S: Process
    S-->>A: Response
    A-->>U: Answer"""

    def _render_html(self, title: str, diagram_type: str, mermaid_code: str) -> str:
        safe_mermaid_code = mermaid_code.replace('`', '\\`')
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vani Diagram — {title}</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;600;700&display=swap');
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Space Grotesk', sans-serif;
    background: #0f0a1e;
    min-height: 100vh;
    color: #e2e8f0;
    display: flex; flex-direction: column; align-items: center;
    padding: 2rem 1rem;
  }}
  .header {{
    text-align: center; margin-bottom: 2rem;
  }}
  .badge {{
    display: inline-block;
    background: linear-gradient(135deg, #7c3aed, #4f46e5);
    color: white; font-size: 0.75rem; font-weight: 600;
    padding: 0.25rem 0.75rem; border-radius: 999px;
    letter-spacing: 0.08em; text-transform: uppercase;
    margin-bottom: 0.75rem;
  }}
  h1 {{
    font-size: clamp(1.5rem, 5vw, 2.5rem);
    font-weight: 700;
    background: linear-gradient(135deg, #c47eff, #818cf8);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin-bottom: 0.5rem;
  }}
  .subtitle {{
    color: #64748b; font-size: 0.9rem;
  }}
  .card {{
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(196,126,255,0.15);
    border-radius: 1.5rem;
    padding: 2.5rem;
    width: 100%; max-width: 900px;
    box-shadow: 0 0 60px rgba(124,58,237,0.15);
  }}
  .mermaid {{
    display: flex; justify-content: center; align-items: center;
    min-height: 300px;
  }}
  .mermaid svg {{
    max-width: 100% !important;
    height: auto !important;
  }}
  .footer {{
    margin-top: 2rem; color: #334155; font-size: 0.8rem; text-align: center;
  }}
  .toolbar {{
    display: flex; gap: 0.75rem; justify-content: flex-end;
    margin-bottom: 1rem;
  }}
  button {{
    background: rgba(124,58,237,0.2);
    border: 1px solid rgba(196,126,255,0.3);
    color: #c47eff; border-radius: 0.5rem;
    padding: 0.4rem 1rem; font-size: 0.85rem; cursor: pointer;
    transition: all 0.2s;
  }}
  button:hover {{ background: rgba(124,58,237,0.4); }}
</style>
</head>
<body>
<div class="header">
  <div class="badge">🗺️ Vani Diagram Plugin</div>
  <h1>{title}</h1>
  <div class="subtitle">Generated {datetime.now().strftime('%d %B %Y, %I:%M %p')}</div>
</div>
<div class="card">
  <div class="toolbar">
    <button onclick="window.print()">🖨️ Print</button>
    <button onclick="copyCode()">📋 Copy Code</button>
  </div>
  <div class="mermaid">
{mermaid_code}
  </div>
</div>
<div class="footer">✨ Created by Vani AI Plugin System · Open in browser to interact</div>
<script>
  mermaid.initialize({{
    startOnLoad: true,
    theme: 'dark',
    themeVariables: {{
      primaryColor: '#7c3aed',
      primaryTextColor: '#fff',
      primaryBorderColor: '#c47eff',
      lineColor: '#818cf8',
      secondaryColor: '#1e1b4b',
      tertiaryColor: '#0f0a1e',
      background: '#0f0a1e',
    }},
    flowchart: {{ curve: 'basis' }},
  }});
  function copyCode() {{
    navigator.clipboard.writeText(`{safe_mermaid_code}`);
    alert('Mermaid code copied!');
  }}
</script>
</body>
</html>"""
