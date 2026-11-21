"""Painel dos workers no terminal: uma tela que se atualiza no lugar, sem rolar mensagens.

    python -m worker painel           (no Termux: fea-painel)
    python3 worker/painel.py --dir deploy/status   (na VPS, fora do Docker)

Mostra cada worker com o verbo do que está fazendo (Aguardando, Buscando, Editando,
Publicando, Limpando), barra e porcentagem quando conhecidas, e uma etiqueta [ OK ], [ERRO]
(falha recente) ou [ OFF] (desligado). Estilo brutalista: blocos chapados, maiúsculas, preto e
branco com amarelo no que está acontecendo. Comandos: /log, /log editor, /voltar, /sair.

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
ERROR_VISIBLE = 15 * 60  # uma falha deixa a etiqueta [ERRO] por 15 minutos

BOLD, INVERSE, RESET = "\x1b[1m", "\x1b[7m", "\x1b[0m"
ACCENT = "\x1b[93m"  # amarelo forte: o que está acontecendo agora
TAG_OK = "\x1b[1;30;102m"  # preto sobre verde
TAG_ERR = "\x1b[1;97;41m"  # branco sobre vermelho
TAG_WARN = "\x1b[1;30;103m"  # preto sobre amarelo
TAG_OFF = "\x1b[1;30;107m"  # preto sobre branco
HEAVY, LIGHT = "━", "─"


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


# --- desenho (brutalista: blocos chapados, maiúsculas, preto/branco + amarelo) -----------

ANSI_RE = __import__("re").compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def visible(text: str) -> int:
    return len(ANSI_RE.sub("", text))


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - visible(text))


def elapsed(seconds: float) -> str:
    """MM:SS até uma hora; depois HHhMM."""
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return f"{seconds // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 3600:02d}H{seconds // 60 % 60:02d}"


def cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def tag(kind: str) -> str:
    """Etiqueta de estado em bloco de cor, sempre com 6 colunas."""
    return {
        "ok": f"{TAG_OK}[ OK ]{RESET}",
        "erro": f"{TAG_ERR}[ERRO]{RESET}",
        "off": f"{TAG_OFF}[ OFF]{RESET}",
    }[kind]


def bar(percent: float | None, width: int, tick: int) -> str:
    width = max(8, width)
    if percent is None:  # sem porcentagem conhecida: bloco que anda
        pos = tick % (width + 5) - 5
        cells = "".join("█" if pos <= i < pos + 5 else "▒" for i in range(width))
        return f"[{ACCENT}{cells}{RESET}]"
    filled = round(width * percent / 100)
    return f"[{ACCENT}{'█' * filled}{RESET}{'▒' * (width - filled)}]"


def banner(left: str, right: str, width: int) -> str:
    """Faixa invertida de largura total."""
    middle = max(1, width - len(left) - len(right))
    return f"{INVERSE}{BOLD}{left}{' ' * middle}{right}{RESET}"


def render_main(statuses: dict, now: float, width: int, tick: int) -> list[str]:
    width = max(40, width)
    online = sum(is_alive(statuses[r], now) for r, _ in ROLES)
    clock = datetime.fromtimestamp(now).strftime("%H:%M:%S")
    rule = HEAVY * width
    lines = [banner(" FEA//WORKERS", f"{online}/4 NO AR  {clock} ", width), rule]
    for number, (role, name) in enumerate(ROLES, start=1):
        data = statuses[role]
        alive = is_alive(data, now)
        error = recent_error(data, now)
        state = "off" if not alive else ("erro" if error else "ok")
        if not alive:
            verb, extra = f"{BOLD}DESLIGADO{RESET}", "FEA-LIGAR"
        else:
            word = (data.get("label") or "Aguardando").upper()
            busy = data.get("state") == "busy"
            verb = f"{ACCENT}{BOLD}{word}{RESET}" if busy else word
            extra = elapsed(now - float(data.get("since") or now))
        head = f" {BOLD}{number:02d}{RESET} {pad(BOLD + name.upper() + RESET, 9)} {tag(state)} "
        room = width - visible(head) - len(extra) - 1
        lines.append(f"{head}{pad(verb, max(0, room))}{extra}")
        if alive and data.get("state") == "busy":
            percent = data.get("percent")
            shown = (
                f"{BOLD}{percent:03.0f}%{RESET}" if percent is not None else f"{BOLD}---%{RESET}"
            )
            lines.append(f"    {bar(percent, max(8, width - 12), tick)} {shown}")
            detail = (data.get("detail") or "").upper().replace(" · ", " / ")
            if detail:
                lines.append(f"    {cut(detail, width - 4)}")
        if error:
            ago = elapsed(now - float(data.get("error_at") or now))
            text = cut(f"!! {error.upper()} (HÁ {ago})", width - 4)
            lines.append(f"    {TAG_ERR}{text}{RESET}")
        lines.append(LIGHT * width)
    lines[-1] = rule
    lines.append(banner(" /LOG  /LOG EDITOR  /SAIR", "", width))
    return lines


LEVEL_TAG = {
    "ERROR": f"{TAG_ERR}ERRO{RESET}",
    "CRITICAL": f"{TAG_ERR}ERRO{RESET}",
    "WARNING": f"{TAG_WARN}AVIS{RESET}",
}


def format_log_line(raw: str, width: int) -> str | None:
    try:
        rec = json.loads(raw)
    except ValueError:
        text = raw.strip()
        return cut(text, width) if text else None
    try:
        hour = datetime.fromisoformat(rec["ts"]).astimezone().strftime("%H:%M:%S")
    except (KeyError, ValueError):
        hour = "--:--:--"
    level = LEVEL_TAG.get(rec.get("level", "INFO"), f"{TAG_OFF}INFO{RESET}")
    msg = rec.get("msg", "")
    for key in ("job_type", "role", "error", "items", "status"):
        if rec.get(key) not in (None, ""):
            msg += f" | {key}={rec[key]}"
    if rec.get("exc"):
        last = [ln for ln in str(rec["exc"]).splitlines() if ln.strip()][-1:]
        msg += f" | {last[0].strip() if last else ''}"
    # Linhas longas quebram com recuo (no celular o detalhe do erro não pode sumir).
    room = max(10, width - 14)
    chunks = [msg[i : i + room] for i in range(0, len(msg), room)] or [""]
    first = f"{BOLD}{hour}{RESET} {level} {chunks[0]}"
    return "\n".join([first] + [" " * 14 + chunk for chunk in chunks[1:6]])


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
            label = r.upper()
            raw.append((stamp, line if role else line.replace('"msg": "', f'"msg": "{label}: ', 1)))
    raw.sort(key=lambda pair: pair[0])
    out = [
        part
        for x in (format_log_line(line, width) for _, line in raw[-count:])
        if x
        for part in x.split("\n")
    ][-count:]
    if not out:
        out = [f"SEM LOG EM {logs}. NA VPS COM DOCKER: docker compose logs {role or ''}"]
    return out


def render_log(logs: Path, role: str | None, width: int, height: int) -> list[str]:
    width = max(40, width)
    title = f" LOG//{(role or 'todos').upper()}"
    lines = [banner(title, "ESC VOLTA ", width), HEAVY * width]
    lines += read_log(logs, role, max(1, height - 5), width)
    return lines


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
    out.append("\x1b[J" + f"{BOLD}>>{RESET} {prompt.upper()}{ACCENT}█{RESET}\x1b[K")
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
                lines = render_log(logs, view_role, size.columns, size.lines)
            if notice:
                lines.append(f"{TAG_WARN}{notice}{RESET}")
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
                    notice = " COMANDOS: /LOG  /LOG EDITOR  /VOLTAR  /SAIR "
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
