FROM python:3.11-slim

# System deps (added wget to download model weights during build)
RUN apt-get update && apt-get install -y \
    libportaudio2 portaudio19-dev ffmpeg wget \
    && rm -rf /var/lib/apt/lists/*

# Python deps — scipy added for audio enhancement pipeline
RUN pip install --no-cache-dir \
    kokoro-onnx>=0.9.0 \
    sounddevice \
    numpy \
    scipy \
    fastapi \
    uvicorn

WORKDIR /app

# Download model weights at build time so the image is self-contained
RUN wget -q -O kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx \
    && wget -q -O voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

# Pre-warm the cache / verify initialization works
RUN python -c "from kokoro_onnx import Kokoro; Kokoro('kokoro-v1.0.onnx', 'voices-v1.0.bin')"

COPY kokoro_server.py .

EXPOSE 8100
CMD ["uvicorn", "kokoro_server:app", "--host", "0.0.0.0", "--port", "8100"]
