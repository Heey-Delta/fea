# Ferramenta de Operações de Vídeo

Busca vídeos com permissão registrada, padroniza cada um com o preset da operação e publica em rodízio nos canais do YouTube Shorts.

O planejamento está em [`tasks.md`](tasks.md). A especificação e as decisões estão no artefato "Especificação da Ferramenta — v2.1" e em [`docs/`](docs/).

## Arquitetura

| Parte | Onde | Pasta |
|---|---|---|
| Interface | Vercel (FastAPI + Jinja2 + HTMX) | `web/`, `app.py` |
| Banco | Neon (Postgres) | `migrations/` |
| Processamento | VPS com Docker: Buscador, Editor, Postador e Limpeza | `worker/` |
| Arquivos | Cloudflare R2 | — |
| Motor genérico e perfis de rede | Compartilhado | `core/`, `networks/` |

## Rodar localmente

Requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/), FFmpeg e Postgres (ou Docker).

```bash
uv sync --all-extras
cp .env.example .env
uv run python -m core.security new-keys        # cole SECRET_KEY e TOKEN_ENCRYPTION_KEY no .env
uv run python -m core.security hash-password   # cole APP_PASSWORD_HASH no .env
uv run alembic upgrade head
uv run uvicorn app:app --reload                # interface em http://localhost:8000
uv run python -m worker check                  # confere FFmpeg, ffprobe e banco
```

Com Docker, `docker compose up` sobe o Postgres, a interface e o worker.

## Testes

```bash
uv run ruff check . && uv run ruff format --check .
TEST_DATABASE_URL=postgresql://fea:fea@localhost:5432/fea uv run pytest
```

Sem `TEST_DATABASE_URL`, os testes de migração são pulados. O CI roda tudo com um Postgres de serviço e também constrói as imagens Docker.

## Segredos

Senhas, tokens e chaves vão só nas variáveis de ambiente (Vercel e VPS), nunca no repositório. A `TOKEN_ENCRYPTION_KEY` precisa ser a mesma nos dois lugares. Os logs mascaram tokens e senhas automaticamente.

## Deploy da interface na Vercel

O projeto `fea` do time OHalla na Vercel está ligado a este repositório. Cada push gera um deploy: o `main` vai para produção e as outras branches viram preview, protegidos pelo login da Vercel.

Variáveis configuradas no projeto (produção e preview): `APP_ENV`, `APP_USER`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY` e `APP_PASSWORD_HASH`. Os três últimos são do tipo sensível e não aparecem no painel.

Para trocar a senha de acesso:

```bash
uv run python -m core.security hash-password
```

Depois substitua o valor de `APP_PASSWORD_HASH` em Settings → Environment Variables e faça um novo deploy.

`DATABASE_URL` entra quando o banco Neon for criado (Task 2 / Task 27.2).
