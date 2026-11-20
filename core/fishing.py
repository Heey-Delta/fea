"""Regras da Pesca para cada item (Task 7): classificação, mídia, hashes e duplicados.

Ordem barata → cara: texto (sem baixar nada), mídia pelos metadados, e só então o download,
os hashes e a comparação com o que já existe.
"""

import hashlib
import json
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Item

PHASH_MAX_DISTANCE = 6
FRAME_POSITIONS = (0.10, 0.50, 0.90)
HASH_HEX = 16  # um pHash de 64 bits em hexadecimal


def normalize(text: str) -> str:
    """Minúsculas e sem acentos, para "Musculação" bater com "musculacao"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def contains(text: str, term: str) -> bool:
    term = normalize(term).strip()
    if not term:
        return False
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


@dataclass(frozen=True)
class TextResult:
    score: int
    reject_reason: str | None


def classify_text(
    text: str, tags: list[str], heat_tags: list[str], blocked_words: list[str]
) -> TextResult:
    """Score = tags encontradas + 2 × heat tags (Task 7.5). Bloqueio e nicho rejeitam."""
    norm = normalize(text)
    for word in blocked_words:
        if contains(norm, word):
            return TextResult(0, f"palavra bloqueada: {word}")
    score = sum(contains(norm, t) for t in tags) + 2 * sum(contains(norm, t) for t in heat_tags)
    if score == 0 and (tags or heat_tags):
        return TextResult(0, "fora do nicho")
    return TextResult(score, None)


def check_media(
    media_type: str, duration_s: float | None, accepted: list[str], max_duration_s: float | None
) -> str | None:
    if accepted and media_type not in accepted:
        return f"mídia não aceita: {media_type}"
    if media_type == "video" and max_duration_s and duration_s and duration_s > max_duration_s:
        return f"duração {duration_s:.0f}s acima do limite de {max_duration_s:.0f}s"
    return None


# --- arquivo ----------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if out.returncode != 0:
        raise ValueError(f"arquivo inválido: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def video_duration(path: Path) -> float:
    return float(probe(path)["format"].get("duration") or 0)


def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n)[:, None]
    i = np.arange(n)[None, :]
    return np.cos(np.pi * k * (2 * i + 1) / (2 * n))


_DCT = _dct_matrix(32)


def phash_of(img: Image.Image) -> str:
    """pHash de 64 bits (hexadecimal de 16 caracteres), igual ao `imagehash.phash`.

    Só precisa de numpy: a lib imagehash puxa o PyWavelets, que não compila no Termux (Android).
    O resultado é o mesmo, então os hashes já gravados continuam comparáveis.
    """
    gray = img.convert("L").resize((32, 32), Image.Resampling.LANCZOS)
    pixels = np.asarray(gray, dtype=np.float64)
    low = (_DCT @ pixels @ _DCT.T)[:8, :8]
    bits = (low > np.median(low)).flatten()
    return f"{int(''.join('1' if b else '0' for b in bits), 2):0{HASH_HEX}x}"


def image_phash(path: Path) -> str:
    with Image.open(path) as img:
        return phash_of(img.convert("RGB"))


def video_phash(path: Path, duration_s: float | None = None) -> str:
    """pHash de 3 quadros (10%, 50%, 90%) concatenados: 48 caracteres hexadecimais."""
    duration = duration_s or video_duration(path)
    hashes = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, pos in enumerate(FRAME_POSITIONS):
            frame = Path(tmp) / f"f{i}.png"
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
            if not frame.exists():
                raise ValueError("não foi possível extrair quadros do vídeo")
            hashes.append(image_phash(frame))
    return "".join(hashes)


def media_phash(path: Path, media_type: str, duration_s: float | None = None) -> str:
    return video_phash(path, duration_s) if media_type == "video" else image_phash(path)


def phash_distance(a: str, b: str) -> int | None:
    """Média da distância por quadro. None quando não dá para comparar (vídeo × imagem)."""
    if len(a) != len(b) or len(a) % HASH_HEX:
        return None
    parts = range(0, len(a), HASH_HEX)
    distances = [
        bin(int(a[i : i + HASH_HEX], 16) ^ int(b[i : i + HASH_HEX], 16)).count("1") for i in parts
    ]
    return round(sum(distances) / len(distances))


# --- duplicados -------------------------------------------------------------------------


def find_duplicate(
    session: Session, sha256: str, phash: str | None, exclude_item_id: int | None = None
) -> tuple[int, str] | None:
    """Mesmo arquivo (sha256) ou imagem parecida (pHash ≤ 6), em qualquer operação (7.3)."""
    base = select(Item.id).where(Item.status != "duplicate")
    if exclude_item_id is not None:
        base = base.where(Item.id != exclude_item_id)
    same = session.scalar(base.where(Item.sha256 == sha256).order_by(Item.id).limit(1))
    if same is not None:
        return same, "mesmo arquivo"
    if not phash:
        return None
    rows = session.execute(
        select(Item.id, Item.phash)
        .where(Item.phash.is_not(None), Item.status != "duplicate")
        .where(Item.id != exclude_item_id if exclude_item_id is not None else True)
        .order_by(Item.id)
    )
    for item_id, other in rows:
        distance = phash_distance(phash, other)
        if distance is not None and distance <= PHASH_MAX_DISTANCE:
            return item_id, f"imagem parecida (distância {distance})"
    return None
