#!/usr/bin/env bash
# Desliga os workers do Termux: primeiro o laço que religa, depois o processo do worker.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$DIR" || exit 1
for r in buscador editor postador limpeza; do
  stopped=""
  if [ -f "logs/$r.pid" ]; then
    kill "$(cat "logs/$r.pid")" 2>/dev/null && stopped=1
  fi
  if [ -f "logs/$r.child" ]; then
    kill "$(cat "logs/$r.child")" 2>/dev/null && stopped=1
  fi
  rm -f "logs/$r.pid" "logs/$r.child"
  [ -n "$stopped" ] && echo "$r desligado"
done
termux-wake-unlock 2>/dev/null || true
