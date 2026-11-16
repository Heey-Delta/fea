"""Detecção de marca d'água de outra rede (Task 7.7). Nunca remove: só rejeita o item.

Lê o texto de 3 quadros com o Tesseract (OCR). Rejeita quando aparece o nome de outra rede
(TikTok, CapCut…) ou um "@usuario" que persiste em pelo menos 2 quadros, o padrão da marca
que o TikTok grava no vídeo. Sem Tesseract instalado, a checagem fica desligada com aviso.
"""

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from core.fishing import FRAME_POSITIONS, normalize, video_duration

log = logging.getLogger("watermark")

PLATFORM_TERMS = ("tiktok", "capcut", "kwai", "likee", "snapchat")
HANDLE = re.compile(r"@[a-z0-9_.]{3,}")
MIN_HANDLE_FRAMES = 2
_warned = False


def available() -> bool:
    return shutil.which("tesseract") is not None


def ocr(image_path: Path) -> str:
    """Texto do quadro. Amplia e passa para cinza: a marca costuma ser pequena e clara."""
    with Image.open(image_path) as img:
        gray = ImageOps.grayscale(img)
        gray = gray.resize((gray.width * 2, gray.height * 2))
        prepared = image_path.with_suffix(".ocr.png")
        gray.save(prepared)
    result = subprocess.run(
        ["tesseract", str(prepared), "stdout", "--psm", "11"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return normalize(result.stdout)


def frames(path: Path, media_type: str, tmp: Path, duration_s: float | None) -> list[Path]:
    if media_type == "image":
        return [path]
    duration = duration_s or video_duration(path)
    out = []
    for i, pos in enumerate(FRAME_POSITIONS):
        frame = tmp / f"w{i}.png"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{duration * pos:.3f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                str(frame),
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if frame.exists():
            out.append(frame)
    return out


def detect(
    path: Path,
    media_type: str,
    duration_s: float | None = None,
    terms: tuple[str, ...] = PLATFORM_TERMS,
) -> str | None:
    """Motivo da rejeição, ou None se não achou marca de outra rede."""
    global _warned
    if not available():
        if not _warned:
            log.warning("tesseract não instalado: checagem de marca d'água desligada")
            _warned = True
        return None
    with tempfile.TemporaryDirectory() as tmp:
        texts = [ocr(f) for f in frames(path, media_type, Path(tmp), duration_s)]
    for term in terms:
        if any(term in t for t in texts):
            return f"marca d'água de terceiro: {term}"
    handles: dict[str, int] = {}
    for t in texts:
        for handle in set(HANDLE.findall(t)):
            handles[handle] = handles.get(handle, 0) + 1
    needed = 1 if media_type == "image" else MIN_HANDLE_FRAMES
    persistent = sorted(h for h, n in handles.items() if n >= needed)
    if persistent:
        return f"marca d'água de terceiro: {persistent[0]}"
    return None
