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

- [ ] Criar a instância ARM, instalar Docker e clonar o repositório.
- [ ] Criar o `.env` a partir de `.env.example` com `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY` e as chaves do R2.

## 5. Armazenamento (Cloudflare R2)

- [ ] Criar o bucket e um token de API com leitura e escrita nele.
- [ ] Preencher `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` e `R2_BUCKET` na Vercel e na VPS.

## 6. Reddit (Buscador)

- [ ] Criar o app em reddit.com/prefs/apps e anotar ID e segredo (variáveis entram com a Task 5).
- [ ] Listar as comunidades com autorização de uso registrada.
- [ ] Se o canal for monetizado, verificar o acordo de uso comercial da API.

## 7. YouTube (Postador)

- [ ] Projeto no Google Cloud com a YouTube Data API v3 ativa e cliente OAuth (variáveis entram com a Task 19).
- [ ] Pedir a auditoria do projeto: sem ela os vídeos saem privados.
