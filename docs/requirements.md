# Vani Dependency Requirements Guide

This file provides a complete catalog of Vani's Python packages and external system libraries. Use it as a future-proof reference for installing and debugging the environment.

---

## 1. System-Level Prerequisites

Before installing the Python packages, ensure the following system dependencies are installed on your machine:

### macOS Installation
Vani requires native media controls, global hotkeys, and audio routing. Install the system binaries via [Homebrew](https://brew.sh):
```bash
# Install portaudio (required for sounddevice)
brew install portaudio

# Install git (required for version control)
brew install git
```

---

## 2. Python Virtual Environment Setup

It is highly recommended to run Vani inside a Python 3.11 virtual environment to isolate dependencies:

```bash
# Create virtual environment
python3.11 -m venv venv311

# Activate virtual environment
source venv311/bin/activate

# Upgrade pip, setuptools, and wheel
pip install --upgrade pip setuptools wheel
```

---

## 3. Core Dependencies & Packages

Below is a categorized catalog of Vani's dependencies. For rapid installation, utilize `requirements/mac.txt` directly.

| Category | Package | Purpose |
| :--- | :--- | :--- |
| **LiveKit Core** | `livekit==1.0.12` <br> `livekit-agents==1.2.1` <br> `livekit-api==1.0.3` <br> `livekit-protocol==1.0.4` | Connects Vani's audio/video pipelines to the LiveKit Server |
| **LiveKit Plugins** | `livekit-plugins-google==1.2.1` <br> `livekit-plugins-openai==1.2.1` <br> `livekit-plugins-silero==1.2.1` <br> `livekit-plugins-noise-cancellation==0.2.5` | Integrates STT/TTS models, voice activity detection (VAD), and background noise reduction |
| **LLM & Cognitive** | `google-genai>=2.5.0` <br> `langchain-core==0.3.71` <br> `langchain==0.3.26` <br> `langchain-community==0.3.27` | Manages the Gemini reasoning engines and structures tool definitions |
| **Audio Processing** | `sounddevice==0.5.2` <br> `numpy==2.3.1` | Records and plays raw audio streams through macOS CoreAudio |
| **GUI & Controls** | `PyAutoGUI==0.9.54` <br> `pynput==1.8.1` <br> `pyobjc==10.3` | Controls global hotkeys, scrolls pages, clicks, and manages windows on macOS |
| **Messaging Integration**| `telethon==1.36.0` | Automates Telegram messaging actions |
| **Utilities** | `python-dotenv==1.1.1` <br> `fuzzywuzzy==0.18.0` <br> `requests==2.32.4` | Handles configuration `.env` files, performs fuzzy matching of names, and fires weather API requests |

---

## 4. Maintenance & Environment Troubleshooting

### PortAudio / sounddevice issues
If `sounddevice` throws an error about not being able to open or find your audio devices:
1. Ensure your Mac terminal application has **Microphone Access** under *System Settings > Privacy & Security*.
2. Verify that PortAudio is properly symlinked:
   ```bash
   brew link portaudio
   ```

### PyObjC installation issues on macOS
If PyObjC fails to compile:
Ensure you are using the correct command line tools for your macOS version:
```bash
xcode-select --install
```

### Freezing environment versions
To freeze current stable versions for future portability:
```bash
pip freeze > requirements_mac_stable.txt
```
