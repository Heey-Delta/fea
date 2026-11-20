#!/usr/bin/env bash
# Instala os workers da Ferramenta de Operações numa VPS Ubuntu (Oracle Always Free, ARM ou x86).
#
#   Gere o comando na tela Acessos → Workers (VPS) → "Gerar comando de instalação". Ele vale
#   30 minutos, uma vez, e já traz DATABASE_URL e TOKEN_ENCRYPTION_KEY.
#   Sem ele: bash <(curl -fsSL https://fea-rho.vercel.app/static/instalar-vps.sh) e cole as duas.
# As demais chaves (R2, Reddit, X, Google, TikTok, Instagram) os workers leem da tela Acessos.
# Pode rodar de novo a qualquer momento: atualiza o código e reinicia os workers.
set -euo pipefail

REPO="git@github.com:Heey-Delta/fea.git"
DIR="${FEA_DIR:-$HOME/fea}"
KEY="$HOME/.ssh/fea_deploy"
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# 1. Docker e git
if ! command -v git >/dev/null; then sudo apt-get update -y && sudo apt-get install -y git; fi
if ! command -v docker >/dev/null; then
  say "Instalando o Docker…"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi
DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

# 2. Código (repositório privado: chave de implantação só de leitura)
if [ ! -d "$DIR/.git" ]; then
  mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
  [ -f "$KEY" ] || ssh-keygen -t ed25519 -N "" -f "$KEY" -C "fea-vps" >/dev/null
  say "Cole a chave abaixo em GitHub → Heey-Delta/fea → Settings → Deploy keys → Add deploy key"
  say "(título: VPS; deixe \"Allow write access\" desmarcado):"
  cat "$KEY.pub"
  read -rp $'\nDepois de adicionar, tecle Enter para continuar… ' _
  GIT_SSH_COMMAND="ssh -i $KEY -o StrictHostKeyChecking=accept-new" git clone "$REPO" "$DIR"
  git -C "$DIR" config core.sshCommand "ssh -i $KEY -o StrictHostKeyChecking=accept-new"
else
  say "Atualizando o código…"
  git -C "$DIR" pull --ff-only
fi
cd "$DIR/deploy"

# 3. Variáveis (só na primeira vez)
DB_URL="${FEA_DATABASE_URL:-}"
ENC_KEY="${FEA_TOKEN_KEY:-}"
if [ -n "$DB_URL" ] || [ ! -f .env ]; then
  if [ -z "$DB_URL" ]; then
    say "Duas informações (ou use o comando gerado na tela Acessos, que já traz as duas):"
    read -rp "DATABASE_URL: " DB_URL
    read -rsp "TOKEN_ENCRYPTION_KEY (não aparece ao digitar): " ENC_KEY; echo
  fi
  umask 077
  printf 'APP_ENV=production\nDATABASE_URL=%s\nTOKEN_ENCRYPTION_KEY=%s\n' "$DB_URL" "$ENC_KEY" > .env
fi

# 4. Migrações e workers
say "Aplicando migrações do banco…"
$DOCKER compose -f docker-compose.vps.yml run --rm migrar
say "Subindo Buscador, Editor, Postador, Limpeza e backup…"
$DOCKER compose -f docker-compose.vps.yml up -d --build
$DOCKER compose -f docker-compose.vps.yml ps
say "Pronto. Em 1 minuto os workers aparecem como healthy. Logs: cd $DIR/deploy && $DOCKER compose -f docker-compose.vps.yml logs -f"
