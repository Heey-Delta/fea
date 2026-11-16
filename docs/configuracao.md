# O que você precisa preencher

O código fica pronto; estes valores só você pode criar. Nada aqui vai para o repositório: tudo entra como variável de ambiente na Vercel (interface) ou no `.env` da VPS (workers).

Status: `[ ]` falta · `[x]` feito.

## 1. Login com GitHub (interface)

- [ ] Criar um **OAuth App** em GitHub → Settings → Developer settings → OAuth Apps → New OAuth App.
  - Homepage URL: o endereço da interface (ex.: `https://fea-oh-alla.vercel.app`).
  - Authorization callback URL: `<endereço>/auth/github/callback`.
- [ ] Na Vercel (projeto `fea` → Settings → Environment Variables), criar:
  - `GITHUB_CLIENT_ID` (texto) e `GITHUB_CLIENT_SECRET` (sensível), do OAuth App.
  - `PUBLIC_BASE_URL` com o mesmo endereço da Homepage URL.
- [x] `GITHUB_ALLOWED_ID=84813286` (conta Heey-Delta), já configurado na Vercel.

Sem `GITHUB_CLIENT_ID` e `GITHUB_CLIENT_SECRET` a interface sobe, mas o login fica desativado e a página explica o que falta.

## 2. Segredos já gerados

- [x] `SECRET_KEY` e `TOKEN_ENCRYPTION_KEY` na Vercel (sensíveis).
- [ ] Copiar o mesmo `TOKEN_ENCRYPTION_KEY` para o `.env` da VPS quando ela existir. Como ele é sensível na Vercel e não pode ser lido de volta, a alternativa é gerar um novo par com `uv run python -m core.security new-keys` e gravar o mesmo valor nos dois lugares.
- [ ] Apagar `APP_USER` e `APP_PASSWORD_HASH` da Vercel: eram do login por senha, que foi substituído pelo GitHub.

## 3. Banco (Neon)

- [ ] Na Vercel, Storage → Create → Neon (ou Marketplace → Neon), ligado ao projeto `fea`. Isso cria `DATABASE_URL` sozinho.
- [ ] Copiar a mesma `DATABASE_URL` para o `.env` da VPS.
- [ ] Aplicar as migrações: `DATABASE_URL=... uv run alembic upgrade head`.

## 4. VPS dos workers (Oracle Always Free)

- [ ] Criar a instância (Ampere A1, Ubuntu 24.04, até 4 OCPUs e 24 GB). Abrir só a porta 22: os workers não recebem conexões.
- [ ] Instalar Docker: `curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER` (sair e entrar de novo).
- [ ] `git clone` do repositório e `cp .env.example deploy/.env`. Preencher em `deploy/.env`: `APP_ENV=production`, `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`, R2, Reddit e Google (os mesmos valores da Vercel).
- [ ] `cd deploy && docker compose -f docker-compose.vps.yml run --rm migrar` (migrações) e depois `docker compose -f docker-compose.vps.yml up -d --build`.
- [ ] Conferir: `docker compose -f docker-compose.vps.yml ps` mostra os 4 workers `healthy`; `logs -f editor` mostra os renders.
- [ ] Backup: o serviço `backup` grava um dump por dia em `deploy/backups/` (14 dias). Para restaurar: `gunzip -c arquivo.sql.gz | psql "$DATABASE_URL"`.
- [ ] Atualizar depois de mudanças: `git pull && docker compose -f docker-compose.vps.yml run --rm migrar && docker compose -f docker-compose.vps.yml up -d --build`.

## 5. Armazenamento (Cloudflare R2)

- [ ] Criar o bucket e um token de API com leitura e escrita nele.
- [ ] Preencher `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` e `R2_BUCKET` na Vercel e na VPS.
- [ ] No bucket, em Settings → CORS policy, liberar o envio direto do navegador (upload manual):

```json
[{"AllowedOrigins": ["https://fea-oh-alla.vercel.app"], "AllowedMethods": ["PUT", "GET"], "AllowedHeaders": ["Content-Type"], "MaxAgeSeconds": 3600}]
```

  Troque a origem pelo endereço real da interface (o mesmo de `PUBLIC_BASE_URL`).

## 6. Reddit (Buscador)

- [ ] Criar o app em reddit.com/prefs/apps (tipo "script") e preencher na VPS e na Vercel:
  `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` e `REDDIT_USER_AGENT` (ex.: `fea/0.1 (by u/seu_usuario)`).
- [ ] Depois de criar a fonte no canvas, usar "Testar conexão" na aba Fontes da operação.
- [ ] Listar as comunidades com autorização de uso registrada.
- [ ] Se o canal for monetizado, verificar o acordo de uso comercial da API.

## 6b. Automação da operação (canvas → Configuração)

- [ ] Em `automation` no fluxo: `daily_play_at` (ex.: `"06:00"`, no fuso do bloco Postagem), `daily_target` (vídeos por dia), `stock_enabled` e `stock_min_days` (recomendado 3 a 7).

## 7. YouTube (Postador)

- [ ] Google Cloud: criar um projeto e ativar a **YouTube Data API v3**.
- [ ] Tela de consentimento OAuth: tipo "Externo", com o seu e-mail como usuário de teste enquanto o app não for publicado.
- [ ] Credenciais → Criar ID do cliente OAuth → "Aplicativo da Web". Em "URIs de redirecionamento autorizados": `{PUBLIC_BASE_URL}/contas/youtube/retorno` (ex.: `https://fea-oh-alla.vercel.app/contas/youtube/retorno`).
- [ ] Variáveis na **Vercel e na VPS**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` e `TOKEN_ENCRYPTION_KEY` (a mesma chave nos dois lados; gere com `python -m core.security new-keys`). Opcional: `YOUTUBE_DAILY_UPLOAD_LIMIT` (padrão 100).
- [ ] Na interface, **Contas → Conectar canal do YouTube** para cada canal; depois ligue cada conta à operação com um bloco Conta no canvas. Ajuste o limite diário (padrão 3) e o fuso.
- [ ] Pedir a auditoria do projeto ("YouTube API Services – Audit and Quota Extension"): sem ela os vídeos enviados pela API ficam **privados**.
- [ ] No bloco Postagem do canvas: `automatic` (distribuição automática), `mode` (`rotation` ou `all`), `interval_min`, `window`, `privacy` e `titles` (corpus, templates, palavras bloqueadas, hashtags, modelo de descrição).
- [ ] Na VPS, rodar também `python -m worker postador` e `python -m worker limpeza` (a Limpeza apaga os arquivos `retention.delete_after_minutes` minutos após a última publicação; padrão 30).
