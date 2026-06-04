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
import subprocess
from datetime import datetime
from pathlib import Path

from vani.plugins.registry import VaniPlugin, PluginResult, PluginContext

logger = logging.getLogger("vani.plugins.diagram")


class DiagramPlugin(VaniPlugin):
    name = "diagram"
    icon = "🗺️"
    description = "Draws flowcharts, concept maps, and system diagrams in your browser."
    category = "visual"
    enabled = False
    triggers = [
        "diagram banao", "flowchart banao", "flowchart", "diagram",
        "draw this", "visually explain", "concept map", "mind map",
        "visually dikhao", "chart banao", "explain with diagram",
        "sequence diagram", "architecture diagram", "system diagram",
        "draw a flowchart", "draw a diagram", "dikhao visually",
    ]

    async def on_activate(self, query: str, context: PluginContext) -> PluginResult:
        # Build Mermaid diagram from context
        diagram_type, mermaid_code = self._build_diagram(query, context)
        title = self._extract_title(query, context)

        html = self._render_html(title, diagram_type, mermaid_code)

        desktop = Path.home() / "Desktop"
        desktop.mkdir(exist_ok=True)
        now = datetime.now().strftime("%d%b%Y_%H%M")
        safe_title = re.sub(r'[^\w]', '_', title)[:30]
        filename = f"Vani_Diagram_{safe_title}_{now}.html"
        filepath = desktop / filename
        filepath.write_text(html, encoding="utf-8")

        # Open in browser
        try:
            import sys
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(filepath)])
            elif sys.platform == "win32":
                os.startfile(str(filepath))
            else:
                subprocess.Popen(["xdg-open", str(filepath)])
        except Exception:
            pass

        return PluginResult(
            success=True,
            message=f"🗺️ Diagram ready! Browser mein '{title}' khul gaya hai.",
            artifact_path=str(filepath),
            artifact_type="html",
            ui_payload={
                "diagram_type": diagram_type,
                "title": title,
                "filename": filename,
                "mermaid_code": mermaid_code,
            }
        )

    def _extract_title(self, query: str, context: PluginContext) -> str:
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
        return "Concept Diagram"

    def _build_diagram(self, query: str, context: PluginContext) -> tuple[str, str]:
        """
        Detect diagram type and build Mermaid syntax from conversation context.
        Returns (diagram_type, mermaid_code).
        """
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
        escaped_mermaid = mermaid_code.replace('\\', '\\\\').replace('`', '\\`')
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
    navigator.clipboard.writeText(`{escaped_mermaid}`);
    alert('Mermaid code copied!');
  }}
</script>
</body>
</html>"""
