FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    PARSERDOC_HOST=0.0.0.0 \
    PARSERDOC_PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        antiword \
        catdoc \
        libreoffice-writer \
        fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY docs/PROJECT_CONTEXT.md docs/PROJECT_CONTEXT.md
COPY app app
COPY serve.py serve.py

RUN python -m pip install --upgrade pip \
    && python -m pip install -e .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import json, urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)); raise SystemExit(0 if data.get('status') == 'ok' else 1)"

CMD ["sh", "-c", "uvicorn app.main:app --host ${PARSERDOC_HOST:-0.0.0.0} --port ${PARSERDOC_PORT:-8000}"]
