"""Painel dos workers no terminal: uma tela que se atualiza no lugar, sem rolar mensagens.

    python -m worker painel           (no Termux: fea-painel)
    python3 worker/painel.py --dir deploy/status   (na VPS, fora do Docker)

Mostra cada worker com o verbo do que está fazendo (Aguardando, Buscando, Editando,
Publicando, Limpando), barra e porcentagem quando conhecidas, e uma bolinha verde (no ar) ou
vermelha (desligado ou com falha recente). Comandos: /log, /log editor, /voltar, /sair.

Só usa a biblioteca padrão: roda mesmo sem o ambiente dos workers.
"""

import argparse
import json
import os
import select
import shutil
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLES = (
    ("buscador", "Buscador"),
    ("editor", "Editor"),
    ("postador", "Postador"),
    ("limpeza", "Limpeza"),
)
ALIVE_FOR = 20  # segundos sem sinal = desligado (o worker dá sinal a cada 5 s)
ERROR_VISIBLE = 15 * 60  # uma falha deixa a bolinha vermelha por 15 minutos

GREEN, RED, YELLOW, CYAN = "\x1b[32m", "\x1b[31m", "\x1b[33m", "\x1b[36m"
BOLD, DIM, RESET = "\x1b[1m", "\x1b[2m", "\x1b[0m"


# --- dados -------------------------------------------------------------------------------


def load_statuses(folder: Path) -> dict[str, dict | None]:
    out = {}
    for role, _ in ROLES:
        try:
            out[role] = json.loads((folder / f"{role}.json").read_text())
        except (OSError, ValueError):
            out[role] = None
    return out


def is_alive(data: dict | None, now: float) -> bool:
    if not data or data.get("state") == "stopped":
        return False
    pid = data.get("pid")
    if pid and data.get("host") == socket.gethostname():
        try:
            os.kill(int(pid), 0)
        except (OSError, ValueError):
            return False
    return now - float(data.get("updated_at") or 0) < ALIVE_FOR


def recent_error(data: dict | None, now: float) -> str:
    if not data or not data.get("error") or not data.get("error_at"):
        return ""
    return data["error"] if now - float(data["error_at"]) < ERROR_VISIBLE else ""


# --- desenho -----------------------------------------------------------------------------


def elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds // 60 % 60:02d}m"


def bar(percent: float | None, width: int, tick: int) -> str:
    width = max(8, width)
    if percent is None:  # sem porcentagem conhecida: bloco que anda
        pos = tick % (width + 4) - 4
        cells = ["▓" if pos <= i < pos + 4 else "░" for i in range(width)]
        return CYAN + "".join(cells) + RESET
    filled = round(width * percent / 100)
    return GREEN + "█" * filled + DIM + "░" * (width - filled) + RESET


def cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def render_main(statuses: dict, now: float, width: int, tick: int) -> list[str]:
    width = max(40, width)
    online = sum(is_alive(statuses[r], now) for r, _ in ROLES)
    clock = datetime.fromtimestamp(now).strftime("%H:%M:%S")
    summary = f"{online}/4 no ar"
    color = GREEN if online == 4 else (YELLOW if online else RED)
    lines = [
        f"{BOLD}FEA · workers{RESET}  {color}{summary}{RESET}  {DIM}{clock}{RESET}",
        DIM + "─" * width + RESET,
    ]
    for role, name in ROLES:
        data = statuses[role]
        alive = is_alive(data, now)
        error = recent_error(data, now)
        dot = f"{GREEN}●{RESET}" if alive and not error else f"{RED}●{RESET}"
        if not alive:
            label, extra = f"{RED}Desligado{RESET}", f"{DIM}rode fea-ligar{RESET}"
        else:
            verb = data.get("label") or "Aguardando"
            label = (BOLD + verb + RESET) if data.get("state") == "busy" else verb
            extra = DIM + elapsed(now - float(data.get("since") or now)) + RESET
        lines.append(f"{dot} {name:<9} {label}  {extra}")
        if alive and data.get("state") == "busy":
            percent = data.get("percent")
            shown = f"{percent:3.0f}%" if percent is not None else "  … "
            detail = cut(data.get("detail") or "", max(0, width - 30))
            lines.append(
                f"  {bar(percent, min(20, width - 28), tick)} {shown}  {DIM}{detail}{RESET}"
            )
        if error:
            ago = elapsed(now - float(data.get("error_at") or now))
            lines.append(f"  {RED}✖ há {ago}: {cut(error, width - 14)}{RESET}")
    lines.append(DIM + "─" * width + RESET)
    lines.append(f"{DIM}/log  ·  /log editor  ·  /sair{RESET}")
    return lines


def format_log_line(raw: str, width: int) -> str | None:
    try:
        rec = json.loads(raw)
    except ValueError:
        text = raw.strip()
        return f"{DIM}{cut(text, width)}{RESET}" if text else None
    try:
        hour = datetime.fromisoformat(rec["ts"]).astimezone().strftime("%H:%M:%S")
    except (KeyError, ValueError):
        hour = "--:--:--"
    level = rec.get("level", "INFO")
    color = RED if level in ("ERROR", "CRITICAL") else (YELLOW if level == "WARNING" else "")
    msg = rec.get("msg", "")
    for key in ("job_type", "role", "error", "items", "status"):
        if rec.get(key) not in (None, ""):
            msg += f" · {key}={rec[key]}"
    if rec.get("exc"):
        last = [ln for ln in str(rec["exc"]).splitlines() if ln.strip()][-1:]
        msg += f" · {last[0].strip() if last else ''}"
    return f"{DIM}{hour}{RESET} {color}{cut(msg, width - 9)}{RESET}"


def read_log(logs: Path, role: str | None, count: int, width: int) -> list[str]:
    roles = [role] if role else [r for r, _ in ROLES]
    raw: list[tuple[str, str]] = []
    for r in roles:
        path = logs / f"{r}.log"
        try:
            with open(path, errors="replace") as f:
                tail = f.readlines()[-count:]
        except OSError:
            continue
        for line in tail:
            stamp = line[8:40] if line.startswith('{"ts": "') else ""
            raw.append((stamp, line if role else line.replace('"msg": "', f'"msg": "[{r}] ', 1)))
    raw.sort(key=lambda pair: pair[0])
    out = [x for x in (format_log_line(line, width) for _, line in raw[-count:]) if x]
    if not out:
        out = [
            f"{DIM}Sem log em {logs}. Na VPS com Docker: docker compose logs {role or ''}{RESET}"
        ]
    return out


def parse_command(text: str) -> tuple[str, str | None]:
    parts = text.strip().lstrip("/").split()
    if not parts:
        return "", None
    cmd = parts[0].lower()
    arg = parts[1].lower() if len(parts) > 1 else None
    if arg:
        arg = next((r for r, n in ROLES if r.startswith(arg) or n.lower().startswith(arg)), arg)
    return cmd, arg


# --- terminal ----------------------------------------------------------------------------


def draw(lines: list[str], prompt: str, height: int) -> None:
    body = lines[: max(1, height - 1)]
    out = ["\x1b[H"]
    out += [line + "\x1b[K\n" for line in body]
    out.append("\x1b[J" + f"> {prompt}\x1b[K")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def run(status: Path, logs: Path) -> None:
    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    view, view_role, buffer, notice, tick = "main", None, "", "", 0
    sys.stdout.write("\x1b[?1049h\x1b[?25l")  # tela alternativa e cursor escondido
    try:
        tty.setcbreak(fd)
        while True:
            size = shutil.get_terminal_size((60, 24))
            now = time.time()
            if view == "main":
                lines = render_main(load_statuses(status), now, size.columns, tick)
            else:
                title = f"{BOLD}Log · {view_role or 'todos'}{RESET}  {DIM}Esc ou /voltar{RESET}"
                lines = [title, DIM + "─" * size.columns + RESET]
                lines += read_log(logs, view_role, size.lines - 4, size.columns)
            if notice:
                lines.append(f"{YELLOW}{notice}{RESET}")
            draw(lines, buffer, size.lines)
            tick += 1
            ready, _, _ = select.select([sys.stdin], [], [], 0.5)
            if not ready:
                continue
            char = os.read(fd, 1).decode(errors="ignore")
            if char in ("\r", "\n"):
                cmd, arg = parse_command(buffer)
                buffer, notice = "", ""
                if cmd in ("sair", "q", "quit", "exit"):
                    return
                if cmd == "log":
                    view, view_role = "log", arg
                elif cmd in ("voltar", "painel", ""):
                    view = "main"
                else:
                    notice = "Comandos: /log, /log editor, /voltar, /sair"
            elif char == "\x1b":  # Esc
                view, buffer = "main", ""
            elif char in ("\x7f", "\b"):
                buffer = buffer[:-1]
            elif char.isprintable():
                buffer += char
    except KeyboardInterrupt:
        return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Painel dos workers")
    parser.add_argument(
        "--dir", default=os.environ.get("FEA_STATUS_DIR") or ROOT / "logs" / "status"
    )
    parser.add_argument("--logs", default=ROOT / "logs")
    parser.add_argument("--once", action="store_true", help="desenha uma vez e sai")
    args = parser.parse_args(argv)
    status, logs = Path(args.dir), Path(args.logs)
    if args.once or not sys.stdin.isatty():
        size = shutil.get_terminal_size((60, 24))
        print("\n".join(render_main(load_statuses(status), time.time(), size.columns, 0)))
        return 0
    run(status, logs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
