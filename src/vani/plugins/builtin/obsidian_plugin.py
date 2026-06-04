"""
vani/plugins/builtin/obsidian_plugin.py

Obsidian Plugin — Vani's long-term memory via Obsidian vault.

What it does:
  • Saves conversation summaries as Obsidian notes (.md with YAML frontmatter)
  • Auto-links related notes using [[wikilinks]]
  • On "remember this" or "save our talk" → writes a note
  • On "what did we discuss about X" → searches the vault
  • At session end → auto-saves a dated note (if enabled)

Setup:
  User must set OBSIDIAN_VAULT_PATH in .env or via plugin settings.
"""

from __future__ import annotations
import os
import re
import json
import sys
import asyncio
import subprocess
import logging
import requests
from datetime import datetime
from pathlib import Path

from vani.plugins.registry import VaniPlugin, PluginResult, PluginContext

logger = logging.getLogger("vani.plugins.obsidian")

VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "")
VANI_FOLDER = "Vani Conversations"   # subfolder inside vault


class ObsidianPlugin(VaniPlugin):
    name = "obsidian"
    icon = "🧠"
    description = "Saves our conversations to your Obsidian vault so Vani never forgets."
    category = "memory"
    enabled = True
    triggers = [
        "obsidian mein save karo", "note banao", "yaad rakh", "remember this",
        "save our conversation", "save this to obsidian", "obsidian note",
        "hamare baat save karo", "note kar lo", "write this down",
        "vault mein save", "save to vault", "obsidian mein likh",
    ]

    def _discover_vault_path(self) -> Path:
        from vani.config import PROJECT_ROOT
        
        # 1. Try env variable
        env_val = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
        if env_val:
            return Path(env_val).expanduser()
            
        # 2. Try autodetect on macOS
        import sys
        if sys.platform == "darwin":
            config_path = Path.home() / "Library/Application Support/obsidian/obsidian.json"
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    vaults = data.get("vaults", {})
                    if vaults:
                        # Find open vault first
                        open_vaults = [v for v in vaults.values() if isinstance(v, dict) and v.get("open") and v.get("path")]
                        if open_vaults:
                            return Path(open_vaults[0]["path"])
                            
                        # Otherwise find recently used vault
                        sorted_vaults = sorted(
                            [v for v in vaults.values() if isinstance(v, dict) and v.get("path")],
                            key=lambda x: x.get("ts", 0),
                            reverse=True
                        )
                        if sorted_vaults:
                            return Path(sorted_vaults[0]["path"])
                except Exception as e:
                    logger.warning(f"Error autodetecting Obsidian vault path from config: {e}")
                    
        # 3. Fallback
        return PROJECT_ROOT / "obsidian_vault"

    def _vault(self) -> Path | None:
        p = self._discover_vault_path()
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            return None

    def _note_dir(self) -> Path | None:
        v = self._vault()
        if not v:
            return None
        d = v / VANI_FOLDER
        d.mkdir(exist_ok=True)
        return d

    def _build_note(
        self,
        title: str,
        content: str,
        messages: list[dict] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Build an Obsidian-flavoured Markdown note."""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")

        tags_str = "\n".join(f"  - {t}" for t in (tags or ["vani", "conversation"]))

        # Build conversation transcript block
        transcript = ""
        if messages:
            transcript = "\n## 💬 Conversation\n\n"
            for m in messages[-20:]:   # last 20 turns only
                role = "🧑 You" if m.get("role") == "user" else "🤖 Vani"
                transcript += f"**{role}**: {m.get('content', '')}\n\n"

        return f"""---
title: "{title}"
date: {date_str}
time: {time_str}
tags:
{tags_str}
source: Vani AI Assistant
---

# {title}

> 📅 *{now.strftime('%d %B %Y, %I:%M %p')}*

## 📝 Summary

{content}
{transcript}
---
*✨ Saved by Vani · Your Personal AI*
"""

    async def on_activate(self, query: str, context: PluginContext) -> PluginResult:
        note_dir = self._note_dir()
        if not note_dir:
            return PluginResult(
                success=False,
                message="Obsidian vault path nahi mila! Please set OBSIDIAN_VAULT_PATH in your .env file.",
                ui_payload={"needs_config": True, "config_key": "OBSIDIAN_VAULT_PATH"}
            )

        recent = context.recent_messages if context.recent_messages else []
        
        # 1. Fast determination of title/tags for instant placeholder file creation
        fallback_tags = self._extract_topics(recent)
        title = f"Vani Chat — {datetime.now().strftime('%d %b %Y %H:%M')}"
        if fallback_tags:
            title = f"Vani — {', '.join(fallback_tags[:2])} — {datetime.now().strftime('%d %b %Y')}"
            
        safe_title = re.sub(r'[^\w\s\-—]', '', title).strip()
        filepath = note_dir / f"{safe_title}.md"
        
        # 2. Write placeholder content immediately
        placeholder_content = self._build_note(
            title, 
            "📝 *Vani is compiling your notes in the background... Please wait a few seconds.*", 
            recent, 
            fallback_tags
        )
        filepath.write_text(placeholder_content, encoding="utf-8")
        
        # 3. Open in Obsidian immediately
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Obsidian", str(filepath)])
        except Exception:
            pass

        # 4. Define background task to fetch LLM summary and update note
        async def _generate_summary_bg():
            loop = asyncio.get_running_loop()
            llm_data = await loop.run_in_executor(None, self._generate_note_via_llm, recent, query)
            
            if llm_data and "title" in llm_data and "summary" in llm_data:
                final_title = llm_data["title"]
                final_summary = llm_data["summary"]
                final_tags = llm_data.get("tags", [])
                logger.info("Successfully generated Obsidian note summary using Ollama LLM in background.")
            else:
                logger.info("Ollama note generation failed or timed out in background. Using fallback.")
                final_title = title
                final_summary = self._summarize(recent, query)
                final_tags = fallback_tags
                
            final_content = self._build_note(final_title, final_summary, recent, final_tags)
            
            # Save and clean up file name
            new_safe_title = re.sub(r'[^\w\s\-—]', '', final_title).strip()
            new_filepath = note_dir / f"{new_safe_title}.md"
            if new_filepath != filepath:
                try:
                    new_filepath.write_text(final_content, encoding="utf-8")
                    filepath.unlink(missing_ok=True)
                    if sys.platform == "darwin":
                        subprocess.Popen(["open", "-a", "Obsidian", str(new_filepath)])
                    
                    from vani.plugins.registry import send_plugin_signal, PluginResult
                    new_res = PluginResult(
                        success=True,
                        message=f"✅ Obsidian mein note save ho gaya hai: '{new_safe_title}'!",
                        artifact_path=str(new_filepath),
                        artifact_type="markdown",
                        ui_payload={"note_title": new_safe_title, "vault_path": str(self._vault())}
                    )
                    await send_plugin_signal(self.name, new_res)
                except Exception as e:
                    logger.warning(f"Error renaming/reopening Obsidian note: {e}")
                    filepath.write_text(final_content, encoding="utf-8")
            else:
                try:
                    filepath.write_text(final_content, encoding="utf-8")
                    from vani.plugins.registry import send_plugin_signal, PluginResult
                    new_res = PluginResult(
                        success=True,
                        message=f"✅ Obsidian mein note save ho gaya hai: '{new_safe_title}'!",
                        artifact_path=str(filepath),
                        artifact_type="markdown",
                        ui_payload={"note_title": new_safe_title, "vault_path": str(self._vault())}
                    )
                    await send_plugin_signal(self.name, new_res)
                except Exception as e:
                    logger.warning(f"Error updating Obsidian note content: {e}")
            
        # Launch background task
        asyncio.create_task(_generate_summary_bg())

        return PluginResult(
            success=True,
            message=f"✅ Obsidian mein note ban gaya hai aur khul gaya hai. Likha jaa raha hai: '{safe_title}'!",
            artifact_path=str(filepath),
            artifact_type="markdown",
            ui_payload={"note_title": safe_title, "vault_path": str(self._vault())}
        )

    async def on_memory_save(self, messages: list[dict]) -> str | None:
        """Auto-save at session end if vault is configured."""
        note_dir = self._note_dir()
        if not note_dir or not messages:
            return None
            
        # Try LLM generation first
        llm_data = self._generate_note_via_llm(messages, "session_auto_save")
        if llm_data and "title" in llm_data and "summary" in llm_data:
            title = llm_data["title"]
            summary = llm_data["summary"]
            tags = llm_data.get("tags", [])
        else:
            tags = self._extract_topics(messages)
            title = f"Vani Session — {datetime.now().strftime('%d %b %Y')}"
            summary = "Auto-saved session transcript."
            
        note_content = self._build_note(title, summary, messages, tags)
        safe_title = re.sub(r'[^\w\s\-—]', '', title).strip()
        (note_dir / f"{safe_title}.md").write_text(note_content, encoding="utf-8")
        return f"🧠 Obsidian vault updated: {safe_title}"

    def _generate_note_via_llm(self, messages: list[dict], query: str) -> dict | None:
        import requests
        
        # Build conversation context from messages (last 8 turns only to keep prompt size small)
        conversation_context = ""
        for msg in messages[-8:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            conversation_context += f"{role.upper()}: {content}\n"
            
        system_prompt = (
            "You are a personal memory assistant. Your goal is to write a clear, concise Obsidian note summarizing a conversation.\n"
            "Rules:\n"
            "1. Output ONLY a valid JSON object. Do not output any explanation, markdown formatting (do not wrap in ```json), or extra words. Start directly with '{' and end with '}'.\n"
            "2. The JSON object MUST contain the following keys:\n"
            "   - \"title\": A concise, professional title for the note summarizing the main topic (e.g. \"Python Multiprocessing\", \"Trip to Mumbai Planning\").\n"
            "   - \"summary\": A rich markdown summary of the conversation. Use bullet points, bold text, or numbered lists to make it look professional and structured. Summarize what was discussed, key choices, and any action items.\n"
            "   - \"tags\": A list of 2 to 4 keywords/tags that represent the topics discussed (e.g. [\"python\", \"concurrency\"] or [\"travel\", \"mumbai\"]).\n"
            "3. Rely strictly on the actual conversation context."
        )
        
        user_prompt = (
            f"Conversation History:\n{conversation_context}\n"
            f"Triggering request: {query}\n\n"
            "Provide the note JSON object now:"
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
                        "num_predict": 300
                    }
                },
                timeout=12
            )
            r.raise_for_status()
            response_text = r.json().get("response", "").strip()
            if not response_text:
                return None
            
            # Clean up potential markdown wrapper code block
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL | re.IGNORECASE)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                first_brace = response_text.find('{')
                last_brace = response_text.rfind('}')
                if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                    json_str = response_text[first_brace:last_brace+1]
                else:
                    json_str = response_text
                    
            data = json.loads(json_str)
            if not isinstance(data, dict) or "title" not in data or "summary" not in data:
                return None
                
            # Basic validation/cleanup of tags
            if "tags" not in data or not isinstance(data["tags"], list):
                data["tags"] = ["vani", "conversation"]
            else:
                data["tags"] = [re.sub(r'[^\w\-]', '', str(t)).lower() for t in data["tags"] if t]
                
            return data
        except Exception as e:
            logger.warning(f"Failed to generate Obsidian note via Ollama: {e}")
            return None

    def _extract_topics(self, messages: list[dict]) -> list[str]:
        """Naive keyword extraction from conversation."""
        text = " ".join(m.get("content", "") for m in messages).lower()
        common = {"the", "is", "a", "and", "to", "of", "in", "it", "you", "i", "we", "that",
                  "me", "my", "this", "can", "vani", "ok", "yes", "no", "hi", "hello"}
        words = re.findall(r'\b[a-z]{4,}\b', text)
        freq: dict[str, int] = {}
        for w in words:
            if w not in common:
                freq[w] = freq.get(w, 0) + 1
        top = sorted(freq, key=lambda x: -freq[x])[:4]
        return [t.title() for t in top]

    def _summarize(self, messages: list[dict], trigger_query: str) -> str:
        """Build a simple summary without LLM (fast path)."""
        if not messages:
            return "Conversation saved from Vani session."
        topics = self._extract_topics(messages)
        topic_str = ", ".join(topics) if topics else "various topics"
        n = len(messages)
        return (
            f"This conversation covered {topic_str}. "
            f"Total {n} messages exchanged. "
            f"Saved on request: \"{trigger_query}\"."
        )
