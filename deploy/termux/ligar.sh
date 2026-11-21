#!/usr/bin/env bash
# Liga os workers no Termux com reinício automático (Task 42).
#
# O Android mata processos em segundo plano (tela apagada, economia de bateria, "phantom
# process killer" do Android 12+). Antes, um worker morto ficava morto e a operação parava no
# meio. Agora cada papel roda num laço: se o processo cair, volta em 10 s e o motivo fica no log.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$DIR" || exit 1
# shellcheck disable=SC1091
source .venv/bin/activate
termux-wake-lock 2>/dev/null || true
export WORKER_CONCURRENCY="${WORKER_CONCURRENCY:-1}" PYTHONUNBUFFERED=1
mkdir -p logs
for r in buscador editor postador limpeza; do
  if [ -f "logs/$r.pid" ] && kill -0 "$(cat "logs/$r.pid")" 2>/dev/null; then
    echo "$r já está rodando"
    continue
  fi
  nohup bash -c '
    r="$1"
    while true; do
      python -m worker "$r" >> "logs/$r.log" 2>&1 &
      echo $! > "logs/$r.child"
      wait $!
      code=$?
      echo "$(date "+%F %T") worker $r parou (código $code); religando em 10 s" >> "logs/$r.log"
      sleep 10
    done
  ' _ "$r" > /dev/null 2>&1 &
  echo $! > "logs/$r.pid"
  echo "$r ligado (religa sozinho se cair)"
done
