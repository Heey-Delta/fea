# Guia de início

O código está pronto e publicado na Vercel. O que falta só pode ser feito por você, porque exige a sua conta, o aceite de termos de uma plataforma ou o seu clique de "Permitir". Siga na ordem.

Onde cada coisa entra:

- **Vercel** (projeto `fea` → Settings → Environment Variables): apenas o login do GitHub. O resto já está configurado.
- **Tela Acessos** da ferramenta: chaves do R2, Reddit, X, Google, TikTok e Instagram, e o login de cada conta. Ficam criptografadas no banco e valem na hora para a interface e para os workers.
- **VPS**: um instalador pergunta só duas coisas (`DATABASE_URL` e `TOKEN_ENCRYPTION_KEY`).

Nenhum segredo vai para o repositório nem para o chat.

## O que dá para fazer pelo código

| Etapa | Automático? | Por quê |
|---|---|---|
| Criar o banco, os apps e a VPS | Não | Cada serviço exige o seu login e o aceite de termos. Nenhum tem API para isso sem uma chave sua. |
| Migrações do banco | Sim | Botão "Aplicar migrações" na tela Acessos, ou o próprio instalador da VPS. |
| Login de cada canal ou conta | Um clique por conta | O OAuth oficial pede "Permitir" uma vez. Depois a ferramenta renova o acesso sozinha. |
| Login com usuário e senha, ou robô no navegador | Não | Viola os termos das plataformas e bloqueia contas. |
| Busca, edição, aprovação, agenda, publicação, métricas e limpeza | Sim | É o trabalho dos workers. |
| Auditorias do Google e do TikTok | Não | São revisões humanas, que levam dias. |

---

## 1 · Banco (1 min)

Na Vercel, abra o projeto `fea` → **Storage** → **Create Database** → **Neon** (plano Free) → conecte ao projeto `fea` nos ambientes Production e Preview. A Vercel cria `DATABASE_URL` sozinha.

## 2 · Login da ferramenta (5 min)

1. GitHub → Settings → Developer settings → OAuth Apps → **New OAuth App**:
   - Homepage URL: `https://fea-rho.vercel.app`
   - Authorization callback URL: `https://fea-rho.vercel.app/auth/github/callback`
2. Na Vercel, crie `GITHUB_CLIENT_ID` e `GITHUB_CLIENT_SECRET` (marque como *Sensitive*) com os valores do OAuth App. `GITHUB_ALLOWED_ID`, `PUBLIC_BASE_URL`, `SECRET_KEY` e `TOKEN_ENCRYPTION_KEY` já estão lá.
3. Vercel → Deployments → no último deploy de produção, **Redeploy**.
4. Abra `https://fea-rho.vercel.app` e clique em **Entrar com GitHub**.

## 3 · Tela Acessos (dentro da ferramenta)

1. **Banco de dados** → clique em **Aplicar migrações**.
2. **Cloudflare R2** (15 min):
   - Cloudflare → R2 → **Create bucket** (ex.: `fea`).
   - **Manage API Tokens** → crie um token com *Object Read & Write* só nesse bucket.
   - Cole na tela Acessos o Account ID, o Access Key ID, o Secret Access Key e o nome do bucket, e clique em **Testar**.
   - No bucket → Settings → CORS policy:

     ```json
     [{"AllowedOrigins": ["https://fea-rho.vercel.app"], "AllowedMethods": ["PUT", "GET"], "AllowedHeaders": ["Content-Type"], "MaxAgeSeconds": 3600}]
     ```

3. **Reddit** (gratuito, uso não comercial):
   - Em https://www.reddit.com/prefs/apps crie um app do tipo **script**. O redirect (`http://localhost:8080`) não é usado, mas é obrigatório.
   - Cole o Client ID, o Client secret e o User-Agent (ex.: `fea/0.1 (by u/seu_usuario)`) e clique em **Testar**.
4. **X** (opcional, pago): crie o app em https://developer.x.com (plano Basic ou superior), cole o Bearer Token e clique em **Testar**.

Os apps das redes de publicação pedem páginas públicas. Elas já existem:

- Página inicial: `https://fea-rho.vercel.app/sobre`
- Privacidade: `https://fea-rho.vercel.app/privacidade`
- Termos: `https://fea-rho.vercel.app/termos`
- Exclusão de dados: `https://fea-rho.vercel.app/exclusao-de-dados`

5. **YouTube Shorts**:
   - Google Cloud → novo projeto → ative a **YouTube Data API v3**.
   - Tela de consentimento OAuth do tipo **Externo**, com as páginas acima e os escopos `youtube.upload` e `youtube.readonly`. **Publique o app**: em modo "Teste" o acesso cai a cada 7 dias.
   - Credenciais → ID do cliente OAuth → **Aplicativo da Web**. Redirect: `https://fea-rho.vercel.app/contas/youtube/retorno`.
   - Cole o Client ID e o secret em Acessos → **Conectar conta YouTube**, uma vez por canal. Se aparecer "app não verificado": Avançado → Continuar.
   - Peça a auditoria ("YouTube API Services – Audit and Quota Extension"). Sem ela, os vídeos sobem privados.
6. **TikTok**:
   - https://developers.tiktok.com → Connect an app → produtos **Login Kit** e **Content Posting API** (Direct Post).
   - Escopos `user.info.basic`, `video.publish` e `video.list`. Termos e privacidade: as páginas acima. Redirect: `https://fea-rho.vercel.app/contas/tiktok/retorno`.
   - Cole o Client key e o secret em Acessos → **Conectar conta TikTok**.
   - Envie o app para revisão. Até ser aprovado, os posts ficam visíveis só para você.
7. **Instagram Reels**:
   - A conta precisa ser **profissional** (Criador ou Empresa).
   - https://developers.facebook.com → Criar app (tipo Empresa) → produto **Instagram** → "API setup with Instagram login".
   - Permissões `instagram_business_basic` e `instagram_business_content_publish`. Redirect: `https://fea-rho.vercel.app/contas/instagram/retorno`. Privacidade e exclusão de dados: as páginas acima.
   - Adicione a sua conta como **testadora** e aceite o convite no Instagram.
   - Cole o Instagram App ID e o secret em Acessos → **Conectar conta Instagram**.

## 4 · Workers na VPS (20 min)

1. Oracle Cloud → Compute → Create instance: **Ampere A1** (ARM), Ubuntu 24.04, até 4 OCPUs e 24 GB. Deixe aberta só a porta 22.
2. Entre por SSH e rode:

   ```bash
   bash <(curl -fsSL https://fea-rho.vercel.app/static/instalar-vps.sh)
   ```

3. O instalador mostra uma chave pública. Em GitHub → `Heey-Delta/fea` → Settings → **Deploy keys** → *Add deploy key*, cole a chave com "Allow write access" desmarcado e tecle Enter no terminal.
4. Ele pede `DATABASE_URL` e `TOKEN_ENCRYPTION_KEY`. Copie os dois da Vercel (Settings → Environment Variables → revelar o valor).
5. No fim, os 4 workers aparecem como `healthy`. Para atualizar depois, rode o mesmo comando de novo.

Backup: um dump por dia fica em `~/fea/deploy/backups/` por 14 dias. Para restaurar: `gunzip -c arquivo.sql.gz | psql "$DATABASE_URL"`.

## 5 · Primeira operação

Operações → dê um nome → **Nova operação**. No editor, clique nos nós Busca, Edição e Publicação e configure cada um no painel da direita. Depois: **Salvar** → **Ativar operação** → **Executar**.

## Decisões que continuam com você

- Quais comunidades do Reddit ou contas do X têm autorização de uso.
- O plano da Vercel: Hobby é só para uso não comercial.
- Os limites do Neon Free (1 GB e 100 horas de computação por mês), acompanhando conforme o volume crescer.
