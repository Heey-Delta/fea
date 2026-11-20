# Guia de início: o que você precisa fazer

O código está pronto. Os passos abaixo são os que só você pode fazer, porque exigem a sua conta, um aceite de termos ou um clique de autorização. Faça na ordem: cada etapa depende da anterior.

Onde cada valor entra:

- **Vercel** (projeto `fea` → Settings → Environment Variables): variáveis da interface.
- **VPS** (`deploy/.env`): variáveis dos workers. Os valores são os mesmos da Vercel.
- **Tela Acessos** (menu Acessos): chaves das redes de busca e de publicação, e o login de cada conta. Ficam criptografadas no banco e valem para a interface e para os workers ao mesmo tempo.

Nenhum segredo vai para o repositório nem para o chat.

## Dá para fazer tudo pelo código?

| Etapa | Automático pelo código? | Por quê |
|---|---|---|
| Criar os apps (GitHub, Google, TikTok, Meta, Reddit, X) | Não | Cada plataforma exige login, aceite de termos e às vezes 2FA no console dela. Não existe API pública para criar esses apps. |
| Login de cada canal ou conta | Uma vez, por clique | O login oficial (OAuth) pede o seu "Permitir" uma vez por conta. Depois disso a ferramenta renova o acesso sozinha. |
| Login com usuário e senha, ou navegador automatizado | Não, e não deve | Viola os termos das plataformas, esbarra em 2FA e captcha e costuma bloquear a conta. Por isso usamos só o OAuth oficial. |
| Renovação de tokens | Sim | YouTube: o refresh token não expira, se o app estiver "Em produção". TikTok: renova a cada envio (365 dias). Instagram: renova a cada 30 dias de uso (60 dias sem uso → conectar de novo). |
| Busca, edição, aprovação automática, agenda, publicação, métricas e limpeza | Sim | É o trabalho dos workers depois que tudo está conectado. |
| Auditoria do Google e do TikTok (vídeo público) | Não | É um formulário de revisão humana em cada plataforma. Leva dias ou semanas. |

---

## Etapa 1 · Chaves da ferramenta (5 min)

1. No seu computador, dentro do projeto: `uv run python -m core.security new-keys`. O comando imprime `SECRET_KEY` e `TOKEN_ENCRYPTION_KEY`.
2. Na Vercel, substitua `SECRET_KEY` e `TOKEN_ENCRYPTION_KEY` por esses valores (marque como *Sensitive*).
3. Guarde o `TOKEN_ENCRYPTION_KEY` num gerenciador de senhas: ele vai também para a VPS, e sem ele as chaves e os tokens salvos não abrem.
4. Na Vercel, apague `APP_USER` e `APP_PASSWORD_HASH`. Eram do login antigo por senha.

## Etapa 2 · Endereço e login da ferramenta (10 min)

1. Defina o endereço fixo da interface. Com a branch mesclada no `main`, a produção da Vercel fica em algo como `https://fea-rho.vercel.app`. Peça para eu abrir o PR quando quiser.
2. Na Vercel: `PUBLIC_BASE_URL` = esse endereço, sem barra no final.
3. GitHub → Settings → Developer settings → OAuth Apps → **New OAuth App**:
   - Homepage URL: o endereço da interface.
   - Authorization callback URL: `{endereço}/auth/github/callback`.
4. Na Vercel: `GITHUB_CLIENT_ID` e `GITHUB_CLIENT_SECRET` (sensível). `GITHUB_ALLOWED_ID=84813286` já está lá.
5. Redeploy e teste o botão "Entrar com GitHub". Só a sua conta entra.

## Etapa 3 · Banco (Neon) (10 min)

1. Vercel → projeto `fea` → Storage → Create → **Neon**, ligado ao projeto. Isso cria `DATABASE_URL` sozinho.
2. Copie a `DATABASE_URL` para o `deploy/.env` da VPS (Etapa 5).
3. As migrações rodam na VPS com o serviço `migrar` (Etapa 5).

## Etapa 4 · Arquivos (Cloudflare R2) (15 min)

1. Cloudflare → R2 → Create bucket (ex.: `fea`).
2. R2 → Manage API Tokens → token com **Object Read & Write** só nesse bucket.
3. Na Vercel e na VPS: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` e `R2_BUCKET`.
4. No bucket → Settings → CORS policy, troque a origem pelo seu endereço:

   ```json
   [{"AllowedOrigins": ["https://fea-rho.vercel.app"], "AllowedMethods": ["PUT", "GET"], "AllowedHeaders": ["Content-Type"], "MaxAgeSeconds": 3600}]
   ```

O R2 é obrigatório para o Instagram, que baixa o vídeo por uma URL pública temporária.

## Etapa 5 · VPS dos workers (Oracle Always Free) (40 min)

1. Oracle Cloud → Compute → Create instance: **Ampere A1** (ARM), Ubuntu 24.04, até 4 OCPUs e 24 GB. Deixe aberta só a porta 22.
2. Por SSH: `curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER`. Saia e entre de novo.
3. `git clone https://github.com/Heey-Delta/fea.git && cd fea && cp .env.example deploy/.env`.
4. Em `deploy/.env`, preencha: `APP_ENV=production`, `DATABASE_URL`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, as quatro do R2 e `PUBLIC_BASE_URL`. As chaves das redes podem ficar vazias aqui, porque entram pela tela Acessos.
5. `cd deploy && docker compose -f docker-compose.vps.yml run --rm migrar` aplica as migrações do banco.
6. `docker compose -f docker-compose.vps.yml up -d --build` sobe Buscador, Editor, Postador, Limpeza e o backup.
7. Confira com `docker compose -f docker-compose.vps.yml ps`: os 4 workers precisam aparecer como `healthy`.

Para atualizar depois: `git pull && docker compose -f docker-compose.vps.yml run --rm migrar && docker compose -f docker-compose.vps.yml up -d --build`.

Backup: um dump por dia fica em `deploy/backups/` por 14 dias. Para restaurar: `gunzip -c arquivo.sql.gz | psql "$DATABASE_URL"`.

Depois desta etapa, abra a ferramenta → **Acessos**. A seção "Ferramenta" deve mostrar tudo verde.

---

## Etapa 6 · Redes de busca (tela Acessos → Busca de conteúdo)

### Reddit (gratuito, uso não comercial) (10 min)

1. https://www.reddit.com/prefs/apps → **create another app** → tipo **script**. Redirect: `http://localhost:8080`; não é usado, mas o campo é obrigatório.
2. Em Acessos → Reddit: Client ID (o código abaixo do nome do app), Client secret e User-Agent (ex.: `fea/0.1 (by u/seu_usuario)`). Clique **Salvar chaves** e depois **Testar**.
3. Se o canal for monetizado, leia a política de uso comercial da API do Reddit antes.

### X (opcional, pago) (15 min)

1. https://developer.x.com → crie um projeto e um app. A busca recente exige o plano **Basic** ou superior.
2. Copie o **Bearer Token** para Acessos → X e clique **Testar**. O teste diz se o plano libera a busca.

---

## Etapa 7 · Redes de publicação (tela Acessos → Publicação)

As plataformas pedem páginas públicas ao cadastrar o app. A ferramenta já tem essas páginas, e a tela Acessos mostra os endereços prontos para copiar:

- Página inicial: `{endereço}/sobre`
- Política de privacidade: `{endereço}/privacidade`
- Termos de uso: `{endereço}/termos`
- Exclusão de dados (Meta): `{endereço}/exclusao-de-dados`

Opcional: defina `CONTACT_EMAIL` (e `OPERATOR_NAME`) na Vercel para o seu contato aparecer nessas páginas.

Para cada rede, faça nesta ordem: criar o app → cadastrar o **endereço de retorno** que a tela Acessos mostra → colar as chaves em Acessos → **Conectar conta** (um clique em "Permitir" por canal ou perfil).

### YouTube Shorts (30 min + auditoria)

1. https://console.cloud.google.com → novo projeto → APIs e serviços → Biblioteca → ative a **YouTube Data API v3**.
2. Tela de consentimento OAuth, tipo **Externo**. Preencha a página inicial, a política de privacidade e os termos com os endereços acima:
   - Adicione os escopos `youtube.upload` e `youtube.readonly`.
   - Depois **Publique o app** ("Em produção"). Em "Teste", o Google derruba o acesso a cada 7 dias.
   - Sem verificação, o login mostra "app não verificado": clique em Avançado → Continuar. Para uso próprio, com menos de 100 usuários, é aceito.
3. Credenciais → Criar ID do cliente OAuth → **Aplicativo da Web**. Em "URIs de redirecionamento autorizados", cole `{endereço}/contas/youtube/retorno`.
4. Em Acessos → YouTube Shorts: Client ID e Client secret → **Salvar chaves** → **Conectar conta YouTube**. Escolha o canal e clique "Permitir". Repita para cada canal.
5. Peça a auditoria ("YouTube API Services – Audit and Quota Extension Form"). Sem ela, os vídeos enviados pela API ficam **privados**. A cota padrão é de cerca de 100 envios por dia por projeto.

### TikTok (30 min + auditoria)

1. https://developers.tiktok.com → Manage apps → **Connect an app**. Em "Terms of Service URL" e "Privacy Policy URL", use `/termos` e `/privacidade`.
2. Adicione os produtos **Login Kit** e **Content Posting API** (ative "Direct Post").
3. Escopos: `user.info.basic`, `video.publish` e `video.list`.
4. Redirect URI: `{endereço}/contas/tiktok/retorno`. O TikTok pode pedir para verificar o domínio: siga a instrução do console.
5. Em Acessos → TikTok: Client key e Client secret → **Salvar chaves** → **Conectar conta TikTok**.
6. Envie o app para revisão. Até ser aprovado, os posts saem visíveis só para você (SELF_ONLY), e a ferramenta ajusta isso sozinha.

### Instagram Reels (30 min + revisão)

1. A conta do Instagram precisa ser **profissional**: Configurações → Tipo de conta → Criador ou Empresa.
2. https://developers.facebook.com → Criar app (tipo **Empresa**) → adicione o produto **Instagram** → "API setup with Instagram login".
3. Permissões: `instagram_business_basic` e `instagram_business_content_publish`. Cadastre o redirect `{endereço}/contas/instagram/retorno`. Em Configurações básicas do app, preencha a URL da política de privacidade (`/privacidade`) e a das instruções de exclusão de dados (`/exclusao-de-dados`).
4. Em modo de desenvolvimento, adicione a sua conta do Instagram como **testadora** (Funções do app) e aceite o convite no Instagram.
5. Em Acessos → Instagram Reels: o **Instagram App ID** e o **Instagram App Secret** (da tela do produto Instagram) → **Salvar chaves** → **Conectar conta Instagram**.
6. Para contas que não são testadoras, o app precisa passar pela revisão da Meta.

Na própria tela Acessos, ajuste em cada conta o **limite diário** (padrão 3) e o **fuso**.

---

## Etapa 8 · Primeira operação (15 min)

1. Operações → **Nova operação**.
2. **Fluxo** → clique em cada bloco:
   - **Pesca**: adicione as fontes (rede de busca, comunidade ou @, e a permissão de uso), as tags, a meta por Play e, se quiser, o Play diário automático.
   - **Motor Editor**: escolha a resolução e o enquadramento, e importe a máscara PNG (1080×1920 com transparência). Em "Textos, logo, áudio e Testar preset", configure o resto e rode um teste.
   - **Publicador**: marque as redes e as contas, a aprovação (manual ou automática), a distribuição e o modelo de título e hashtags.
3. **Salvar versão** e confira a "Validação do fluxo".
4. Na operação: **Ativar** → **▶ Play**.
5. Acompanhe em Fila → Aprovação → Publicações. O Dashboard mostra o resumo e os erros.

## Decisões que continuam com você

- Quais comunidades do Reddit ou contas do X têm autorização de uso registrada.
- O plano da Vercel: o Hobby é só para uso não comercial; para uso comercial, o Pro.
- Os limites gratuitos do Neon, que valem acompanhar no painel conforme o volume crescer.
