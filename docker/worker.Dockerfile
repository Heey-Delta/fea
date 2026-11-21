# Imagem dos workers e do agente da plataforma (Tasks 1.8 e 33).
# A mesma imagem roda: os workers de cada operação, o núcleo e o agente (que precisa do
# cliente Docker para administrar os projetos Compose pelo socket local).
FROM docker:29-cli AS dockercli

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr fonts-dejavu-core fonts-inter \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.5.4
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

WORKDIR /srv/fea
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra worker

COPY core ./core
COPY networks ./networks
COPY worker ./worker
COPY agent ./agent
COPY migrations ./migrations
COPY alembic.ini ./

# Versão do código (commit) gravada na imagem: a tela Acessos compara com o site.
ARG FEA_VERSION=""
ENV FEA_VERSION=${FEA_VERSION}

CMD ["python", "-m", "worker", "check"]
