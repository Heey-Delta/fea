#!/data/data/com.termux/files/usr/bin/bash
# Instala os workers da Ferramenta de Operações no Termux (Android), sem Docker.
#
#   Termux do GitHub ou do F-Droid (nunca o da Play Store).
#   Antes: em Acessos → Workers, toque em "Baixar .env (meu computador)".
#   Depois: pkg install -y curl && bash <(curl -fsSL https://fea-rho.vercel.app/static/instalar-termux.sh)
#
# Pode rodar de novo a qualquer momento: atualiza o código e refaz o que faltar.
# Os quatro workers (Buscador, Editor, Postador e Limpeza) rodam em segundo plano.
set -euo pipefail

REPO="git@github.com:Heey-Delta/fea.git"
DIR="${FEA_DIR:-$HOME/fea}"
KEY="$HOME/.ssh/fea_deploy"
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m%s\033[0m\n' "$*" >&2; exit 1; }

[ -d /data/data/com.termux ] || die "Este instalador é só para o Termux (Android)."

# 1. Pacotes do sistema. Os que têm versão pronta no Termux evitam compilar no celular.
say "Instalando pacotes (alguns minutos)…"
termux-wake-lock 2>/dev/null || true
pkg update -y
pkg install -y python git openssh ffmpeg tesseract libpq openssl libffi \
  clang make pkg-config rust binutils libjpeg-turbo freetype \
  python-numpy python-pillow python-cryptography curl

# 2. Código (repositório privado: chave de implantação só de leitura)
if [ ! -d "$DIR/.git" ]; then
  mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
  [ -f "$KEY" ] || ssh-keygen -t ed25519 -N "" -f "$KEY" -C "fea-termux" >/dev/null
  say "Cole a chave abaixo em GitHub → Heey-Delta/fea → Settings → Deploy keys → Add deploy key"
  say "(título: Celular; deixe \"Allow write access\" desmarcado):"
  cat "$KEY.pub"
  read -rp $'\nDepois de adicionar, tecle Enter para continuar… ' _
  GIT_SSH_COMMAND="ssh -i $KEY -o StrictHostKeyChecking=accept-new" git clone "$REPO" "$DIR"
  git -C "$DIR" config core.sshCommand "ssh -i $KEY -o StrictHostKeyChecking=accept-new"
else
  say "Atualizando o código…"
  git -C "$DIR" pull --ff-only
fi
cd "$DIR"

# 3. Configuração (o .env baixado na tela Acessos). Nunca vai para o Git.
if [ ! -f .env ]; then
  [ -d "$HOME/storage/downloads" ] || termux-setup-storage || true
  sleep 3
  FOUND=""
  for f in "$HOME"/storage/downloads/fea-workers*.env "$HOME"/storage/shared/Download/fea-workers*.env; do
    [ -f "$f" ] && FOUND="$f"
  done
  [ -n "$FOUND" ] || die "Não achei o fea-workers.env em Downloads. Baixe-o em Acessos → Workers → \"Baixar .env (meu computador)\" e rode este instalador de novo."
  umask 077
  cp "$FOUND" .env
  say "Configuração copiada de $FOUND."
  rm -f "$FOUND"
fi
chmod 600 .env

# 4. Python: o ambiente enxerga o numpy, o Pillow e o cryptography do Termux.
say "Instalando as bibliotecas Python (a primeira vez demora; o pydantic compila)…"
[ -d .venv ] || python -m venv --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate
export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk)"
export MATHLIB="m"
export CARGO_BUILD_JOBS=2
pip install --upgrade pip wheel setuptools
# numpy, Pillow e cryptography já vêm do pacote do Termux (python-*); aqui entra só o resto.
pip install "sqlalchemy>=2.0" "alembic>=1.13" "psycopg>=3.2" "pydantic-settings>=2.4" \
  "httpx>=0.27" "boto3>=1.35" "itsdangerous>=2.2" "jinja2>=3.1"

# 5. Fonte do texto sobre o vídeo
mkdir -p assets/fonts
if [ ! -f assets/fonts/DejaVuSans-Bold.ttf ]; then
  curl -fsSL -o assets/fonts/DejaVuSans-Bold.ttf \
    https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf/DejaVuSans-Bold.ttf \
    || say "Não consegui baixar a fonte; textos sobre o vídeo podem falhar."
fi

# 6. Atalhos para ligar, desligar e ver os workers
mkdir -p "$HOME/.local/bin" logs
cat > "$HOME/.local/bin/fea-ligar" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null || true
cd "$DIR" && source .venv/bin/activate
export WORKER_CONCURRENCY=1 PYTHONUNBUFFERED=1
for r in buscador editor postador limpeza; do
  if [ -f logs/\$r.pid ] && kill -0 "\$(cat logs/\$r.pid)" 2>/dev/null; then echo "\$r já está rodando"; continue; fi
  nohup python -m worker \$r >> logs/\$r.log 2>&1 &
  echo \$! > logs/\$r.pid
  echo "\$r ligado"
done
EOF
cat > "$HOME/.local/bin/fea-desligar" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
cd "$DIR"
for r in buscador editor postador limpeza; do
  [ -f logs/\$r.pid ] && kill "\$(cat logs/\$r.pid)" 2>/dev/null && echo "\$r desligado"; rm -f logs/\$r.pid
done
termux-wake-unlock 2>/dev/null || true
EOF
cat > "$HOME/.local/bin/fea-status" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
cd "$DIR"
for r in buscador editor postador limpeza; do
  if [ -f logs/\$r.pid ] && kill -0 "\$(cat logs/\$r.pid)" 2>/dev/null; then echo "\$r: rodando"; else echo "\$r: parado"; fi
done
echo; echo "Últimas linhas dos logs (sem dados sensíveis):"
tail -n 3 logs/*.log 2>/dev/null | cut -c1-200
EOF
chmod +x "$HOME"/.local/bin/fea-*
grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
export PATH="$HOME/.local/bin:$PATH"

# 7. Verificação e migrações
say "Verificando FFmpeg e o banco…"
python -m worker check
say "Aplicando migrações do banco…"
alembic upgrade head

say "Ligando os workers…"
fea-ligar
say "Pronto. Em 1 minuto, Acessos → Workers mostra 4/4 no ar.
  fea-status     como estão os workers
  fea-desligar   parar
  fea-ligar      voltar
Deixe o celular na tomada e tire o Termux da otimização de bateria (Configurações do Android)."
