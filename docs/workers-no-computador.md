# Workers no seu computador (sem VPS)

Os workers (Buscador, Editor, Postador e Limpeza) são o que busca, edita, publica e limpa. Eles podem rodar no seu computador com o Docker Desktop, sem VPS e sem CNPJ. A interface continua na Vercel, o banco no Neon e os arquivos no R2.

Limitação: os workers só trabalham com o computador **ligado e acordado**. Dá para testar, gravar a demonstração da auditoria e operar no dia a dia. Para rodar 24 horas, use uma VPS depois (ver `docs/rumos.md`).

## O que precisa
- Windows 10/11, macOS ou Linux, com pelo menos 8 GB de memória.
- Uns 10 GB livres no disco.

## 1 · Instalar o Docker Desktop (10 min)
1. Baixe em **docker.com/products/docker-desktop** e instale.
2. No Windows, se pedir, aceite instalar o **WSL 2** e reinicie o computador.
3. Abra o Docker Desktop e espere aparecer "Engine running".
4. Em Settings → General, marque **Start Docker Desktop when you sign in**, para os workers voltarem sozinhos depois de reiniciar.

## 2 · Baixar o código (2 min)
1. Logado no GitHub como Heey-Delta, abra `github.com/Heey-Delta/fea`.
2. Toque em **Code → Download ZIP**.
3. Extraia o ZIP. Vai sair uma pasta `fea-main`. Exemplo no Windows: `C:\Users\SEU_USUARIO\fea-main`.

## 3 · Baixar o arquivo de configuração (1 min)
1. Na ferramenta, vá em **Acessos → Workers** e toque em **Baixar .env (meu computador)**.
2. Vai baixar `fea-workers.env`. Ele dá acesso ao banco: não envie para ninguém.
3. Mova o arquivo para a pasta `deploy` do código, com o nome **`.env`**. O jeito mais seguro é pelo terminal (passo 4).

## 4 · Ligar os workers (5 a 10 min na primeira vez)

**Windows (PowerShell):**
```powershell
cd $HOME\fea-main\deploy
Move-Item $HOME\Downloads\fea-workers.env .env
docker compose -f docker-compose.vps.yml run --rm migrar
docker compose -f docker-compose.vps.yml up -d --build buscador editor postador limpeza
```

**Mac ou Linux (Terminal):**
```bash
cd ~/fea-main/deploy
mv ~/Downloads/fea-workers.env .env
docker compose -f docker-compose.vps.yml run --rm migrar
docker compose -f docker-compose.vps.yml up -d --build buscador editor postador limpeza
```

Ajuste os caminhos se você extraiu a pasta em outro lugar. A primeira vez demora, porque o Docker monta a imagem com o FFmpeg.

## 5 · Conferir
Em cerca de 1 minuto, **Acessos → Workers** mostra **4/4 no ar**. Se não chegar lá:
```
docker compose -f docker-compose.vps.yml ps
docker compose -f docker-compose.vps.yml logs --tail=40
```
Mande a saída para o Claude, sem as linhas que mostrem `DATABASE_URL` ou chaves.

## Dia a dia
- **Parar:** `docker compose -f docker-compose.vps.yml stop`
- **Voltar:** `docker compose -f docker-compose.vps.yml start`
- **Atualizar o código:**
  1. Baixe o ZIP de novo e extraia por cima.
  2. Mantenha o arquivo `deploy/.env`.
  3. Rode de novo as duas últimas linhas do passo 4.
- **Computador lento?** No arquivo `docker-compose.vps.yml`, troque `WORKER_CONCURRENCY: "2"` do editor por `"1"`.
- **Não deixe o computador dormir** enquanto houver operação rodando. No Windows, ajuste em Configurações → Sistema → Energia.

O backup diário do banco (serviço `backup`) ficou de fora de propósito: no computador, ele lotaria o disco. O Neon já guarda o histórico do banco.
