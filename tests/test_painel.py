"""Painel dos workers no terminal e o registro de atividade que ele lê."""

import json
import re
import shutil
import subprocess
import time

import pytest

from core import activity
from core.editor import render as rd
from core.logging import redact_text
from worker import painel

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def plain(lines):
    return "\n".join(ANSI.sub("", line) for line in lines)


def test_activity_grava_estado_progresso_e_falha(tmp_path):
    clock = [1000.0]
    act = activity.Activity("editor", tmp_path, clock=lambda: clock[0])
    act.busy("render", "tarefa #87")
    clock[0] += 1
    act.progress(58.4, "58% do vídeo")
    data = json.loads((tmp_path / "editor.json").read_text())
    assert (data["state"], data["label"], round(data["percent"])) == ("busy", "Editando", 58)
    act.failed("FFmpeg falhou: entrada inválida")
    data = json.loads((tmp_path / "editor.json").read_text())
    assert data["state"] == "idle" and data["error"].startswith("FFmpeg falhou")
    act.stopped()
    assert json.loads((tmp_path / "editor.json").read_text())["state"] == "stopped"


def test_progresso_logo_apos_o_inicio_chega_ao_painel(tmp_path):
    """Duas gravações por segundo no máximo, mas o último valor nunca se perde."""
    clock = [1000.0]
    act = activity.Activity("editor", tmp_path, clock=lambda: clock[0])
    act.busy("render")
    act.progress(42)  # no mesmo instante: não grava agora
    assert json.loads((tmp_path / "editor.json").read_text())["percent"] is None
    act.touch()  # o worker chama a cada segundo
    assert json.loads((tmp_path / "editor.json").read_text())["percent"] == 42


def test_painel_desenha_verbos_barra_cores_e_desligado():
    now = time.time()
    statuses = {
        "buscador": {"state": "idle", "label": "Aguardando", "since": now - 70, "updated_at": now},
        "editor": {
            "state": "busy",
            "label": "Editando",
            "percent": 58.0,
            "detail": "tarefa #87",
            "since": now - 72,
            "updated_at": now,
        },
        "postador": {
            "state": "idle",
            "label": "Aguardando",
            "since": now,
            "updated_at": now,
            "error": "Publicando (tarefa #5): token recusado",
            "error_at": now - 120,
        },
        "limpeza": {"state": "idle", "label": "Aguardando", "since": now, "updated_at": now - 60},
    }
    lines = painel.render_main(statuses, now, 60, 0)
    text = plain(lines)
    assert "3/4 no ar" in text
    assert "Editando" in text and " 58%" in text and "tarefa #87" in text
    assert "Aguardando  1m10s" in text
    assert "token recusado" in text and "há 2m00s" in text
    assert "Limpeza   Desligado" in text
    raw = "\n".join(lines)
    assert "\x1b[32m●" in raw and "\x1b[31m●" in raw  # verde no ar, vermelho com problema


def test_comandos_e_log_formatado(tmp_path):
    assert painel.parse_command("/log ed") == ("log", "editor")
    assert painel.parse_command("/log") == ("log", None)
    assert painel.parse_command("/sair") == ("sair", None)
    (tmp_path / "editor.log").write_text(
        json.dumps(
            {
                "ts": "2026-11-21T00:19:39+00:00",
                "level": "INFO",
                "msg": "tarefa concluída",
                "job_type": "render",
            }
        )
        + "\n"
        + json.dumps(
            {
                "ts": "2026-11-21T00:20:00+00:00",
                "level": "ERROR",
                "msg": "erro",
                "exc": "Traceback...\nRuntimeError: FFmpeg falhou",
            }
        )
        + "\n"
    )
    out = plain(painel.read_log(tmp_path, "editor", 10, 80))
    assert "tarefa concluída · job_type=render" in out and "RuntimeError: FFmpeg falhou" in out


def test_painel_once_sem_terminal(tmp_path, capsys):
    activity.Activity("buscador", tmp_path).idle()
    assert painel.main(["--once", "--dir", str(tmp_path)]) == 0
    assert "Buscador  Aguardando" in ANSI.sub("", capsys.readouterr().out)


def test_chave_de_api_na_url_nunca_vai_para_o_log():
    line = 'GET https://www.googleapis.com/drive/v3/files?q=x&key=AIzaSyAbc_123&pageSize=1 "200"'
    assert "AIza" not in redact_text(line) and "pageSize=1" in redact_text(line)


def test_progresso_do_ffmpeg_por_linha():
    assert rd.progress_percent("out_time_us=4000000", 8.0) == 50.0
    assert rd.progress_percent("progress=end", 8.0) == 100.0
    assert rd.progress_percent("frame=12", 8.0) is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg não instalado")
def test_edicao_real_informa_progresso(tmp_path):
    seen = []
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x568:rate=30:duration=3",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        str(tmp_path / "o.mp4"),
    ]
    rd.run(rd.RenderPlan(cmd, 3.0, False, []), on_progress=seen.append)
    assert seen and seen[-1] == 100.0 and seen == sorted(seen)
    with pytest.raises(RuntimeError, match="FFmpeg falhou"):
        bad = rd.RenderPlan(
            ["ffmpeg", "-i", str(tmp_path / "nao-existe.mp4"), str(tmp_path / "x.mp4")],
            3.0,
            False,
            [],
        )
        rd.run(bad, on_progress=seen.append)
    assert subprocess.run(["true"]).returncode == 0
