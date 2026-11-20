# Guia de início

O código está pronto e publicado na Vercel. O que falta só pode ser feito por você, porque exige a sua conta, o aceite de termos de uma plataforma ou o seu clique de "Permitir". Siga na ordem.

Onde cada coisa entra:

- **Vercel**: já está tudo configurado (banco, endereço, chaves).
- **Tela Acessos** da ferramenta: chaves do R2, Reddit, X, Google, TikTok e Instagram, e o login de cada conta. Ficam criptografadas no banco e valem na hora para a interface e para os workers.
- **VPS**: um comando gerado na tela Acessos instala tudo. Não é preciso copiar nenhuma chave.

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

## 1 · Banco ✓

Feito: o Neon está conectado ao projeto e a Vercel gravou `DATABASE_URL` e `DATABASE_URL_UNPOOLED`.

## 2 · Login da ferramenta (1 clique)

1. Abra `https://fea-rho.vercel.app/login`, logado no GitHub como **Heey-Delta**.
2. Clique em **Configurar login com GitHub** e depois em **Criar o app de login no GitHub**. A ferramenta cria as tabelas do banco nesse passo.
3. No GitHub, confira o nome do app e clique em **Create GitHub App**. Você volta para a ferramenta com "Login configurado".
4. Clique em **Entrar com GitHub** e depois em **Authorize**. Só a sua conta (ID 84813286) entra.

## 3 · Tela Acessos (dentro da ferramenta)

1. **Banco de dados**: já deve aparecer "Conectado e atualizado". Se pedir, clique em **Aplicar migrações**.
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
2. Na ferramenta, abra Acessos → **Workers (VPS)** → **Gerar comando de instalação**. O comando vale 30 minutos e uma única vez, e já traz o banco e a chave de criptografia.
3. Entre na VPS por SSH e cole o comando.
4. O instalador mostra uma chave pública. Em GitHub → `Heey-Delta/fea` → Settings → **Deploy keys** → *Add deploy key*, cole a chave com "Allow write access" desmarcado e tecle Enter no terminal.
5. Em cerca de 1 minuto, o card **Workers (VPS)** mostra 4/4 no ar. Para atualizar depois, rode `bash <(curl -fsSL https://fea-rho.vercel.app/static/instalar-vps.sh)` na VPS.

Backup: um dump por dia fica em `~/fea/deploy/backups/` por 14 dias. Para restaurar: `gunzip -c arquivo.sql.gz | psql "$DATABASE_URL"`.

## 5 · Primeira operação

Operações → dê um nome → **Nova operação**. No editor, clique nos nós Busca, Edição e Publicação e configure cada um no painel da direita. Depois: **Salvar** → **Ativar operação** → **Executar**.

## Decisões que continuam com você

- Quais comunidades do Reddit ou contas do X têm autorização de uso.
- O plano da Vercel: Hobby é só para uso não comercial.
- Os limites do Neon Free (1 GB e 100 horas de computação por mês), acompanhando conforme o volume crescer.
