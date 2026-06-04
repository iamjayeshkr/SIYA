# Vani: The Autonomous Voice AI Agent OS
## Complete End-to-End Capabilities & Features Guide

Vani is a local-first, low-latency, voice-activated autonomous Agent Operating System (OS). It combines always-on voice recognition, local semantic memory, real-time tool orchestration, and cross-platform desktop automation to act as a production-grade personal assistant.

Here is the complete end-to-end directory of everything Vani can do:

---

## 🎙️ Always-On Activation & Voice Verification

### 1. 24/7 Siri-Style Wake Listener
* **Offline Vosk Keyword Spotter**: Listens for `"Vani"`, `"Hey Vani"`, or `"Okay Vani"` using a lightweight local voice model (~50ms latency, zero internet requirement).
* **Mac Speech Fallback**: Automatically falls back to native macOS `NSSpeechRecognizer` if Vosk models are not loaded.
* **Double-Clap Wake Trigger**: A zero-dependency acoustic clap-detector energy tracker. Wakes up the assistant if two sharp energy peaks are detected within `0.8` seconds (even with music playing).

### 2. Biometric Speaker Verification
* **Voiceprint Enrollment**: Enrolls the owner's voice and saves a persistent signature (`voiceprint.npy`).
* **Active Verification Gate**: Processes microphone frames in a rolling buffer. Verifies that the speaker matches the enrolled voiceprint before executing commands.
* **Security Lockdown**: Restricts operations and voices warnings if an unauthorized voice attempts to speak to Vani.

---

## 🧠 Memory & Semantic Knowledge Engine

### 1. Completely Local Semantic Vector Memory
* **Local Embeddings**: Integrates with local Ollama embeddings (`nomic-embed-text`) to generate text vectors.
* **SQLite Vector Store**: Maintains a local vector database in SQLite with cosine-similarity scoring.
* **Mem0 Fact Extraction**: Asynchronously extracts new facts about the user's habits, favorites, and preferences from normal conversation and saves them.

### 2. Centralized Knowledge Graph
* **Dynamic Entity Mapping**: Maps entities, categories, and directed relationship paths in SQLite.
* **Verifications & Citations**: Allows verifying pathways (e.g. checking facts) and records source citation links.

### 3. Persistent Working Memory
* **JSON State Memory**: Saves pending reminders, active topics, recent working files, and frequent queries to `vani_working_memory.json`.
* **Startup Memory Brief**: Speaks a quick summary of pending tasks and the last active topic upon booting.
* **Automatic memory purges**: Erases conversation history, temporary files, working memories, and semantic vectors dynamically when the wake word is detected or the server launches.

---

## 📂 Document Ingestion & Reading

### 1. Document Reading & Outline Extraction
* **Universal Formats**: Ingests PDFs, Word Documents (`.docx`), Markdown, text files, and code.
* **Outline Generator**: Extracts main headers and compiles table-of-contents lists.

### 2. Gemini Files API & Injected Prompts
* **Context Injections**: Injects up to 18,000 characters of the document text directly into the Gemini Realtime system instructions for instant Q&As.
* **Files API Background Uploads**: Uploads files to the Gemini Files API in the background, giving the LLM 48-hour access to the native document contents.
* **Voice-Activated Deletion**: Purges document caches instantly when the user says `"remove docx knowledge"` or `"clear document memory"`.

---

## 🖥️ Cross-Platform App Automation

### 1. Desktop Application Openers
* **App Controls**: Opens, runs, and brings targeted applications to the foreground on macOS (via AppleScript) and Windows.

### 2. Typing Simulation & Clipboard Integration
* **Clipboard Typing**: Pastes text content dynamically using clipboard overrides—enabling rapid typing of long code or text blocks into active applications without delays.
* **WhatsApp & Telegram Messaging**: Automatically focuses inputs and writes messages directly into messaging clients.
* **Notes & Notepad Writing**: Appends conversation logs or idea lists as formatted notes into Apple Notes (via structured AppleScript templates) or Windows Notepad.

---

## 🔍 Web Exploration & Market Checks

### 1. Boilerplate-Free Web Crawler
* **Content Extractor**: Downloads web pages, strips headers, style sheets, scripts, and navigation links, returning clean Github-Flavored Markdown.
* **Semantic Chunker**: Slices pages into overlapping vector chunks for targeted query matching.

### 2. Real-Time Finance Checker
* **Keyless Stock Quotations**: Checks live equity details (TCS, Reliance, Apple, etc.) directly using Yahoo Finance API wrappers.
* **Ticker Suffix Mapping**: Auto-appends exchange suffixes (e.g. `.NS` for Indian equities on NSE) and maps company names to tickers.

---

## 🛠️ Developer & Enterprise Expertise

### 1. Dynamic Domain Experts Registry
* **Software Engineering**: Performs repository analysis, executes edits, compiles source files, and offers refactoring recommendations.
* **Cybersecurity**: Evaluates system security postures, does threat modeling, and identifies log vulnerabilities.
* **Business Intelligence**: Compiles tradeoff grids, SWOT sheets, and market sizing briefs.
* **Education**: Outlines lesson plans, creates quizzes, and identifies learning gaps.

### 2. Project Tracker OS
* **Checklist & Milestones**: Maintains tasks, checklists, and dependency flows in `projects.json`.
* **Blocker Warnings**: Highlights tasks blocked by incomplete prerequisites.

### 3. Background Automation Platform
* **Task Scheduler**: Executes cron jobs and interval timers in background threads.
* **Tool Security Gate**: Restricts scheduled tasks from calling hazardous commands without manual overrides.

---

## 📊 Operations & Security Controls

### 1. Sandboxed Tool Execution
* **Tool Permissions**: Categorizes tools into `SAFE`, `CONFIRM_REQUIRED`, and `SANDBOXED` access levels.
* **PII Redaction**: Recursively scrubs secrets, tokens, passwords, and environment keys from audit files.
* **Structured Audit Logging**: Writes all agent runs, variables, and states to `conversations/audit_log.jsonl`.

### 2. Local Cache Managers
* **Thread-Safe LRU Cache**: Avoids duplicate API hits by caching searches, crawls, and quotes.
* **Token Pruning**: Calls the local LLM to summarize intermediate outputs when logs exceed context limits, saving tokens.

### 3. Observability Dashboard
* **Usage & Cost Metrics**: Tracks task latency, successes, and virtual token expenditure in USD.
