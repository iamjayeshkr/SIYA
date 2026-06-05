# Vani Docker Setup Guide — Kokoro TTS Service

Vani uses **Kokoro-82M (ONNX)** for high-quality, local Text-to-Speech (TTS) synthesis. Instead of installing heavy C-dependencies (`portaudio`, `ffmpeg`), Python packages (`scipy`, `numpy`, `kokoro-onnx`), and downloading 350MB+ weights directly onto your macOS host, you can run the Kokoro TTS engine inside a lightweight Docker container.

This guide walks you through building, starting, verifying, and connecting the Dockerized Kokoro service to your Vani application.

---

## 🏗️ 1. Architecture Overview

Because Vani acts as an autonomous Desktop Assistant, it requires direct, low-level OS access:
* **UI/Screen Capture** (OCR & Spotlight scanning)
* **Keyboard/Mouse Input Emulation** (PyAutoGUI, pynput)
* **Sound Devices** (WebRTC voice capture)

Since Docker Desktop on macOS runs inside a sandboxed Linux VM, it cannot easily capture the Mac’s native screen or input events. Therefore:
1. **Vani Python Core** runs natively on the host Mac to capture keyboard/mouse, screen OCR, and capture microphone input.
2. **Kokoro TTS Server** runs in **Docker** as a backend HTTP API on port `8100`, handling text-to-audio synthesis and signal-processing enhancements.

```
┌─────────────────────────────────────────────────────────┐
│                       MAC HOST                          │
│                                                         │
│   ┌──────────────────┐           ┌──────────────────┐   │
│   │ Vani Python Core │──────────>│  Browser UI      │   │
│   │ (Port 5500/8081) │           │  (Port 5500)     │   │
│   └──────────────────┘           └──────────────────┘   │
│            │                                            │
│            │ POST /speak                                │
│            ▼                                            │
│   ┌─────────────────────────────────────────────────┐   │
│   │                   DOCKER VM                     │   │
│   │                                                 │   │
│   │   ┌──────────────────┐                          │   │
│   │   │ Kokoro TTS API   │                          │   │
│   │   │ (Port 8100)      │                          │   │
│   │   └──────────────────┘                          │   │
│   └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 🚀 2. Getting Started

### Step 1: Start Docker Desktop
Make sure Docker Desktop is open and running on your Mac. You can check this by running:
```bash
docker ps
```

### Step 2: Build & Start the Container
From the root of the `Vani` project directory, run Docker Compose. This will download the base python-slim image, install necessary system/audio libraries, fetch the official Kokoro ONNX model and voice assets (`~350MB`), and boot the FastAPI server:

```bash
docker compose up --build -d
```

* **`--build`**: Forces a fresh build of the Docker image.
* **`-d`**: Runs the container in the background (detached mode).

### Step 3: Verify Container Health
Once the container starts, query its health endpoint:
```bash
curl http://localhost:8100/health
```

**Expected Response:**
```json
{"status":"ok","voice":"af_heart","speed":0.95}
```

---

## ⚙️ 3. Configure Vani to Use Docker

To route speech synthesis queries to the Dockerized Kokoro server, update your `.env` configuration file.

1. Open `.env` (located at the project root).
2. Locate the `# ── Kokoro TTS ──` section.
3. Update the values to match the following configuration:

```env
# ── Kokoro TTS ────────────────────────────────────────────────────────────────
# Kokoro is the ONLY voice output for Vanni. Gemini runs in text mode.
# One consistent voice for all replies — short and long.
KOKORO_ENABLED=1               # Enable Kokoro TTS (1=on, 0=off/Gemini fallback)
KOKORO_VOICE=hf_beta           # hf_beta (Hindi female), af_heart (warm), af_bella, af_sarah, am_adam
KOKORO_SPEED=1.1               # 1.0=normal, 1.1=slightly faster conversational feel

KOKORO_HTTP_URL=http://localhost:8100  # Uncommented to point Vani to the Docker endpoint
```

### Step 4: Restart Vani
After updating `.env`, start or restart Vani using the launch script:
```bash
bin/run_vani.sh
```
Vani will now automatically detect `KOKORO_HTTP_URL` and send text payloads to Docker for speech generation, bypassing local synthesis.

---

## 🛠️ 4. Useful Docker CLI Commands

Here are common commands for managing the Kokoro service:

* **View Logs**: To inspect TTS synthesis activity or debugging errors:
  ```bash
  docker logs -f vani-kokoro-tts
  ```
* **Stop the Service**:
  ```bash
  docker compose down
  ```
* **Check Resources**:
  ```bash
  docker stats vani-kokoro-tts
  ```
