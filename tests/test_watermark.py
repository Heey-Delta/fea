"""Detecção de marca d'água de outra rede (Task 7.7)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from core import watermark

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and watermark.available() and Path(FONT).exists()),
    reason="FFmpeg, Tesseract ou fonte ausente",
)


def video(path: Path, *texts: str) -> Path:
    draws = ",".join(
        f"drawtext=fontfile={FONT}:text='{t}':fontsize=44:fontcolor=white:"
        f"box=1:boxcolor=black@0.6:x=30:y={60 + 70 * i}"
        for i, t in enumerate(texts)
    )
    vf = ["-vf", draws] if texts else []
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x3a6ea5:size=540x960:rate=30:duration=3",
            *vf,
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            str(path),
        ],
        check=True,
    )
    return path


def test_platform_name_is_rejected(tmp_path):
    assert watermark.detect(video(tmp_path / "a.mp4", "TikTok"), "video") == (
        "marca d'água de terceiro: tiktok"
    )


def test_persistent_handle_is_rejected(tmp_path):
    reason = watermark.detect(video(tmp_path / "b.mp4", "@criador_original"), "video")
    # O OCR pode errar o fim do nome (sublinhado), mas acha o @ que persiste.
    assert reason.startswith("marca d'água de terceiro: @criador")


def test_clean_video_passes(tmp_path):
    assert watermark.detect(video(tmp_path / "c.mp4", "Quem nunca na academia"), "video") is None
    assert watermark.detect(video(tmp_path / "d.mp4"), "video") is None


def test_without_tesseract_check_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(watermark, "available", lambda: False)
    assert watermark.detect(tmp_path / "qualquer.mp4", "video") is None
