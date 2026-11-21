#!/usr/bin/env bash
# Instala a plataforma da Ferramenta de Operações numa VPS (Tasks 33 e 35, docs/plataforma.md).
#
#   Um ambiente Docker Compose isolado por operação + o núcleo (agenda e limpeza), administrados
#   por um agente que lê o estado desejado do painel. Nenhuma porta fica aberta além do SSH.
#
#   Gere o comando na tela Acessos → Workers → "Gerar comando de instalação (VPS)". Ele vale
#   30 minutos, uma vez, e já traz DATABASE_URL e TOKEN_ENCRYPTION_KEY.
#
# Idempotente: rodar de novo atualiza o código e a imagem, sem apagar dados nem duplicar nada.
# Depois de instalado, o comando `fea` administra a máquina: fea status | atualizar | logs | painel.
set -euo pipefail

REPO="${FEA_REPO:-git@github.com:Heey-Delta/fea.git}"  # FEA_REPO: outra origem (ex.: cópia local)
HOME_DIR="${FEA_HOME:-/opt/fea}"
APP="$HOME_DIR/app"
KEY="$HOME_DIR/secrets/deploy_key"
PANEL="https://fea-rho.vercel.app"
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m%s\033[0m\n' "$*" >&2; exit 1; }
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"

# 1. Distribuição, arquitetura e recursos ---------------------------------------------------
[ -r /etc/os-release ] || die "Sistema sem /etc/os-release: use Ubuntu 22.04+ ou Debian 12+."
. /etc/os-release
case "${ID:-}" in ubuntu|debian) ;; *) die "Distribuição $ID não suportada: use Ubuntu ou Debian." ;; esac
ARCH="$(uname -m)"
case "$ARCH" in x86_64|aarch64|arm64) ;; *) die "Arquitetura $ARCH não suportada." ;; esac
MEM_MB=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 ))
DISK_GB=$(( $(df -Pk / | awk 'NR==2 {print $4}') / 1024 / 1024 ))
say "Máquina: $PRETTY_NAME, $ARCH, ${MEM_MB} MB de memória, ${DISK_GB} GB livres."
[ "$MEM_MB" -ge 1800 ] || say "Atenção: menos de 2 GB de memória. Cabe 1 operação pequena."
[ "$DISK_GB" -ge 8 ] || die "Menos de 8 GB livres em disco: libere espaço antes."

# 2. Docker Engine + Compose pelo repositório oficial (chave assinada, sem curl | sh) --------
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  say "Instalando o Docker pelo repositório oficial…"
  $SUDO apt-get update -y
  $SUDO apt-get install -y ca-certificates curl git
  $SUDO install -m 0755 -d /etc/apt/keyrings
  $SUDO curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
  $SUDO chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID ${VERSION_CODENAME} stable" \
    | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
  $SUDO apt-get update -y
  $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
command -v git >/dev/null || $SUDO apt-get install -y git
$SUDO systemctl enable --now docker >/dev/null 2>&1 || true
DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="$SUDO docker"

# 3. Firewall: só o SSH entra (liberado ANTES de ativar, para não trancar você do lado de fora)
if command -v ufw >/dev/null || $SUDO apt-get install -y ufw >/dev/null 2>&1; then
  SSH_PORT="$({ $SUDO sshd -T 2>/dev/null || true; } | awk '/^port /{print $2; exit}')"
  SSH_PORT="${SSH_PORT:-22}"
  if $SUDO ufw allow "$SSH_PORT/tcp" >/dev/null 2>&1 \
    && $SUDO ufw default deny incoming >/dev/null 2>&1 \
    && $SUDO ufw default allow outgoing >/dev/null 2>&1 \
    && $SUDO ufw --force enable >/dev/null 2>&1; then
    say "Firewall ativo: entrada só pela porta $SSH_PORT (SSH)."
  else
    say "Atenção: não consegui ativar o firewall aqui. No painel da VPS, deixe aberta só a porta $SSH_PORT."
  fi
else
  say "Atenção: ufw indisponível. No painel da VPS, deixe aberta só a porta do SSH."
fi

# 4. Pastas e permissões ------------------------------------------------------------------
$SUDO install -d -m 0750 "$HOME_DIR" "$HOME_DIR/operations" "$HOME_DIR/nucleo" "$HOME_DIR/backups"
$SUDO install -d -m 0700 "$HOME_DIR/secrets"

# 5. Segredos: só gravados quando vêm no comando (ou na primeira vez) ------------------------
ENV_FILE="$HOME_DIR/secrets/worker.env"
DB_URL="${FEA_DATABASE_URL:-}"
ENC_KEY="${FEA_TOKEN_KEY:-}"
if [ -n "$DB_URL" ] || ! $SUDO test -f "$ENV_FILE"; then
  if [ -z "$DB_URL" ]; then
    say "Duas informações (o comando gerado na tela Acessos já traz as duas):"
    read -rp "DATABASE_URL: " DB_URL
    read -rsp "TOKEN_ENCRYPTION_KEY (não aparece ao digitar): " ENC_KEY; echo
  fi
  printf 'APP_ENV=production\nDATABASE_URL=%s\nTOKEN_ENCRYPTION_KEY=%s\n' "$DB_URL" "$ENC_KEY" \
    | $SUDO tee "$ENV_FILE" >/dev/null
fi
$SUDO chmod 600 "$ENV_FILE"

# 6. Código (repositório privado: chave de implantação só de leitura) ------------------------
GIT_SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new"
if [ ! -d "$APP/.git" ]; then
  if [[ "$REPO" == git@* ]]; then
    $SUDO test -f "$KEY" || $SUDO ssh-keygen -t ed25519 -N "" -f "$KEY" -C "fea-vps" >/dev/null
    say "Cole a chave abaixo em GitHub → Heey-Delta/fea → Settings → Deploy keys → Add deploy key"
    say "(título: VPS; deixe \"Allow write access\" desmarcado):"
    $SUDO cat "$KEY.pub"
    read -rp $'\nDepois de adicionar, tecle Enter para continuar… ' _
    $SUDO env GIT_SSH_COMMAND="$GIT_SSH" git clone "$REPO" "$APP"
    $SUDO git -C "$APP" config core.sshCommand "$GIT_SSH"
  else
    $SUDO git clone "$REPO" "$APP"
  fi
else
  say "Atualizando o código…"
  $SUDO git -C "$APP" pull --ff-only
fi
VERSION="$($SUDO git -C "$APP" rev-parse --short=7 HEAD)"

# Instalação antiga (um Compose só, em ~/fea/deploy): para, a plataforma assume.
for OLD in "$HOME/fea/deploy" "/root/fea/deploy"; do
  if [ -f "$OLD/docker-compose.vps.yml" ]; then
    $DOCKER compose -f "$OLD/docker-compose.vps.yml" down >/dev/null 2>&1 || true
    say "Instalação antiga em $OLD parada: a plataforma assume."
  fi
done

# 7. Imagem versionada (fea-worker:<commit>); as anteriores ficam para rollback ---------------
if [ -n "${FEA_IMAGE:-}" ]; then
  # Imagem já pronta (ex.: VPS com pouca memória para compilar): só usa a tag informada.
  VERSION="$FEA_IMAGE"
  $DOCKER image inspect "fea-worker:$VERSION" >/dev/null 2>&1 || die "Imagem fea-worker:$VERSION não existe."
  say "Usando a imagem pronta fea-worker:$VERSION."
else
  say "Construindo a imagem fea-worker:$VERSION (a primeira vez demora alguns minutos)…"
  $DOCKER build -f "$APP/docker/worker.Dockerfile" --build-arg FEA_VERSION="$VERSION" \
    -t "fea-worker:$VERSION" -t fea-worker:latest "$APP"
fi

# 8. Migrações do banco ----------------------------------------------------------------------
say "Aplicando migrações do banco…"
$DOCKER run --rm --env-file "$ENV_FILE" "fea-worker:$VERSION" alembic upgrade head

# 9. Agente da plataforma (socket do Docker só local; nenhuma porta publicada) ---------------
say "Subindo o agente da plataforma…"
$DOCKER rm -f fea-agente >/dev/null 2>&1 || true
$DOCKER run -d --name fea-agente --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock -v "$HOME_DIR:$HOME_DIR" \
  -e FEA_HOME="$HOME_DIR" -e FEA_SERVER_NAME="$(hostname)" --env-file "$ENV_FILE" \
  --log-opt max-size=10m --log-opt max-file=3 \
  "fea-worker:$VERSION" python -m agent >/dev/null

# 10. Comando `fea` para administrar a máquina -----------------------------------------------
$SUDO tee /usr/local/bin/fea >/dev/null <<EOF
#!/usr/bin/env bash
# Administração da plataforma na VPS. O controle de cada operação fica no painel (aba Ambiente).
set -euo pipefail
D="docker"; docker info >/dev/null 2>&1 || D="sudo docker"
case "\${1:-status}" in
  status)    \$D compose ls -a | grep -E 'NAME|fea-' ; echo; \$D ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'NAMES|fea-' ;;
  atualizar) bash <(curl -fsSL $PANEL/static/instalar-vps.sh) ;;
  logs)      if [ -n "\${2:-}" ]; then \$D compose -p "fea-op-\$2" logs -f --tail 50; else \$D logs -f --tail 50 fea-agente; fi ;;
  painel)    dir="$HOME_DIR/nucleo/status"; [ -n "\${2:-}" ] && dir="$HOME_DIR/operations/op-\$2/status"
             python3 "$APP/worker/painel.py" --dir "\$dir" ;;
  *) echo "uso: fea status | atualizar | logs [operação] | painel [operação]" ;;
esac
EOF
$SUDO chmod 755 /usr/local/bin/fea

# 11. Verificação de saúde ------------------------------------------------------------------
say "Verificando (até 2 minutos)…"
for _ in $(seq 1 24); do
  if $DOCKER compose ls 2>/dev/null | grep -q '^fea-nucleo .*running'; then break; fi
  sleep 5
done
$DOCKER compose ls -a | grep -E 'NAME|fea-' || true
if $DOCKER compose ls 2>/dev/null | grep -q '^fea-nucleo .*running'; then
  say "Pronto. Plataforma no ar (versão $VERSION).
  Painel:  $PANEL/contas#vps   (cada operação: aba Ambiente)
  Na VPS:  fea status · fea logs <operação> · fea painel <operação> · fea atualizar
Os workers do celular param sozinhos em até 1 minuto."
else
  say "O agente subiu, mas o núcleo ainda não. Veja: fea logs"
fi
