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
  python-numpy python-pillow python-cryptography curl bzip2

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
# Só duas bibliotecas não têm versão pronta para Android: MarkupSafe (compila em segundos) e
# pydantic-core (Rust, 15 a 40 minutos). Por isso o pydantic vem por último, isolado.
say "Instalando as bibliotecas leves…"
pip install "sqlalchemy>=2.0" "alembic>=1.13" "psycopg>=3.2" "httpx>=0.27" "boto3>=1.35" \
  "itsdangerous>=2.2" "jinja2>=3.1" "tzdata" \
  || die "Falhou uma biblioteca leve. Copie as últimas linhas do erro (sem chaves) e mande ao Claude."
say "Instalando o pydantic (a parte mais demorada: pode compilar por 15 a 40 minutos)…"
pkg install -y python-pydantic 2>/dev/null || say "Sem pacote pronto do pydantic: o pip vai compilar."
pip install "pydantic-settings>=2.4" \
  || die "Falhou o pydantic. Rode este instalador de novo (ele continua) ou mande as últimas linhas do erro ao Claude."

# 5. Fonte do texto sobre o vídeo (o pacote oficial do DejaVu traz o arquivo dentro)
mkdir -p assets/fonts
if [ ! -f assets/fonts/DejaVuSans-Bold.ttf ]; then
  FONT_TMP="$(mktemp -d)"
  if curl -fsSL -o "$FONT_TMP/dejavu.tar.bz2" \
      https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.tar.bz2 \
    && tar -xjf "$FONT_TMP/dejavu.tar.bz2" -C "$FONT_TMP" dejavu-fonts-ttf-2.37/ttf/DejaVuSans-Bold.ttf \
    && cp "$FONT_TMP/dejavu-fonts-ttf-2.37/ttf/DejaVuSans-Bold.ttf" assets/fonts/; then
    say "Fonte instalada."
  else
    say "Não consegui instalar a fonte; textos sobre o vídeo podem falhar."
  fi
  rm -rf "$FONT_TMP"
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
# Retrato rápido dos workers (o painel ao vivo é o fea-painel).
cd "$DIR" && exec python worker/painel.py --once
EOF
cat > "$HOME/.local/bin/fea-painel" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
# Painel ao vivo: verbo de cada worker, barra, porcentagem e /log para os detalhes.
cd "$DIR" && exec python worker/painel.py
EOF
cat > "$HOME/.local/bin/fea-atualizar" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
# Baixa o código novo e reinicia os workers (eles não se atualizam sozinhos).
cd "$DIR" && git pull --ff-only || exit 1
source .venv/bin/activate && alembic upgrade head
fea-desligar; fea-ligar; fea-status
EOF
chmod +x "$HOME"/.local/bin/fea-*
grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
export PATH="$HOME/.local/bin:$PATH"

# 7. Verificação e migrações
# O Termux não traz o banco de fusos horários do sistema: o pacote tzdata do pip supre isso.
say "Verificando se os módulos dos workers carregam…"
python -c "import worker.handlers, worker.publish, worker.render, worker.collect" \
  || die "Um módulo dos workers não carregou (erro acima). Copie as últimas linhas, sem chaves, e mande ao Claude."
say "Verificando FFmpeg e o banco…"
python -m worker check
say "Aplicando migrações do banco…"
alembic upgrade head

say "Ligando os workers (reinicia os que já rodavam, para carregar o código novo)…"
fea-desligar >/dev/null 2>&1 || true
fea-ligar
say "Pronto. Em 1 minuto, Acessos → Workers mostra 4/4 no ar.
  fea-painel     painel ao vivo (digite /log para os detalhes, /sair para fechar)
  fea-status     retrato rápido dos workers
  fea-desligar   parar
  fea-ligar      voltar
  fea-atualizar  baixar o código novo e reiniciar (faça isso depois de cada atualização)
Deixe o celular na tomada e tire o Termux da otimização de bateria (Configurações do Android)."
