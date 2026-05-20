FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl ca-certificates xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev || uv sync --no-dev
RUN uv run playwright install --with-deps chromium

COPY . .

ENV PATH="/app/.venv/bin:$PATH"
