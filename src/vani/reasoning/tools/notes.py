"""
vani/reasoning/tools/notes.py
Note saving with Ollama-powered Markdown beautification.
"""

import os
import re
import subprocess
import asyncio
import logging
from langchain_core.tools import tool

from vani.reasoning.shared import (
    IS_MAC, IS_WINDOWS,
    logger,
    OLLAMA_URL, OLLAMA_MODEL,
    _safe_popen,
)


def _ollama_beautify(title: str, content: str) -> str:
    """
    Ask Qwen2.5:3b to rewrite the note as a beautiful Markdown file
    with emojis, proper headers, and clean formatting.
    Returns markdown string.
    """
    import requests

    prompt = f"""You are a creative note formatter.
Convert the following note into a beautiful, well-structured Markdown (.md) file.

Rules:
- Add a big emoji in the title that matches the topic
- Use ## for section headers with relevant emojis
- Format lists as proper markdown bullet points (-)
- Add a small motivational footer at the end
- Keep the language same as the input (Hindi/English/mixed)
- Do NOT add any explanation — output ONLY the markdown content

Title: {title}
Content: {content}"""

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception:
        from datetime import datetime
        lines = content.strip().split("\n")
        md_lines = [f"# 📝 {title}", "", f"*{datetime.now().strftime('%d %B %Y, %I:%M %p')}*", ""]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if re.match(r"^\d+[\.\)]\s+", line):
                line = re.sub(r"^\d+[\.\)]\s+", "- ", line)
            md_lines.append(line)
        md_lines += ["", "---", "*✨ by Vani · Your Personal AI*"]
        return "\n".join(md_lines)


@tool
async def save_note(title: str, content: str) -> str:
    """
    Notes, goals, plans, reminders, lists — beautifully formatted Markdown file
    ke roop mein Desktop pe save karta hai. Emojis, headers, clean formatting
    sab Qwen2.5:3b se automatically generate hota hai.
    title: note ka naam | content: jo likhna hai
    """
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    os.makedirs(desktop, exist_ok=True)
    safe = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-", "+", "#")).strip() or "Note"
    filepath = os.path.join(desktop, f"{safe}.md")

    loop = asyncio.get_running_loop()
    md_content = await loop.run_in_executor(
        None, _ollama_beautify, title, content
    )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md_content)

    try:
        if IS_MAC:
            r = subprocess.run(["which", "code"], capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                _safe_popen(["code", filepath])
            else:
                _safe_popen(["open", "-a", "Visual Studio Code", filepath])
        elif IS_WINDOWS:
            vscode = os.path.expandvars(
                r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe"
            )
            _safe_popen([vscode, filepath]) if os.path.exists(vscode) else os.startfile(filepath)
    except Exception:
        pass

    return f"✅ '{safe}.md' Desktop pe save ho gaya — emojis aur formatting ke saath! 🎉"
