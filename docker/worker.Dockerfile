# Imagem dos workers da VPS: Buscador, Editor, Postador e Limpeza (Task 1.8).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr fonts-dejavu-core fonts-inter \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv

WORKDIR /srv/fea
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra worker

COPY core ./core
COPY networks ./networks
COPY worker ./worker
COPY migrations ./migrations
COPY alembic.ini ./

CMD ["python", "-m", "worker", "check"]
