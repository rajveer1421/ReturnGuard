FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    U2NET_HOME=/app/.cache/u2net \
    PORT=7860

RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces runs containers as uid 1000
RUN useradd -m -u 1000 app
WORKDIR /app

COPY requirements.txt .
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1 \
    && pip install -r requirements.txt

COPY --chown=app:app . .
USER app

# Download DINOv2 and U2-Net at build time so the first request isn't a 300 MB download
RUN python -c "from returnguard import imaging, embeddings; imaging._rembg_session(); embeddings._model()"

EXPOSE 7860
# One worker: models live in memory and returns are processed by an in-process background thread.
CMD gunicorn --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:${PORT} app:app
