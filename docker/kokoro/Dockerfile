FROM python:3.11-slim

# System deps for sounddevice + ONNX
RUN apt-get update && apt-get install -y \
    libportaudio2 portaudio19-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir kokoro-onnx>=0.9.0 sounddevice numpy fastapi uvicorn

# Download model weights at build time (not runtime)
RUN python -c "from kokoro_onnx import Kokoro; Kokoro('kokoro-v1.9.onnx', 'voices-v1.0.bin')" || true

WORKDIR /app
COPY kokoro_server.py .

EXPOSE 8100
CMD ["uvicorn", "kokoro_server:app", "--host", "0.0.0.0", "--port", "8100"]
