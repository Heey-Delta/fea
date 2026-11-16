"""Máscaras PNG (Task 12): importação, validação e versões.

A máscara é criada fora da ferramenta e importada. Cada envio cria uma versão nova e imutável;
os renders guardam a versão usada, então trocar a máscara não muda vídeos já feitos (12.5).
"""

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.fishing import sha256_file
from core.models import Event, MaskAsset, MaskVersion
from core.storage import Storage


class MaskError(Exception):
    """Arquivo recusado (corrompido ou não é PNG): bloqueia o uso."""


@dataclass
class MaskCheck:
    width: int
    height: int
    has_alpha: bool
    warnings: list[str] = field(default_factory=list)


def validate_png(path: Path, output: tuple[int, int]) -> MaskCheck:
    """Integridade, formato PNG, dimensões, transparência e proporção (Task 12.2)."""
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            fmt, size, mode = img.format, img.size, img.mode
            has_alpha = mode in ("RGBA", "LA") or (mode == "P" and "transparency" in img.info)
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise MaskError("Arquivo corrompido ou não é uma imagem.") from exc
    if fmt != "PNG":
        raise MaskError(f"A máscara precisa ser PNG (recebido: {fmt}).")
    check = MaskCheck(width=size[0], height=size[1], has_alpha=has_alpha)
    if not has_alpha:
        check.warnings.append("Sem canal de transparência: a máscara vai cobrir o vídeo.")
    if size != output:
        check.warnings.append(
            f"Dimensões {size[0]}×{size[1]} diferentes da saída {output[0]}×{output[1]}: "
            "será ajustada mantendo a proporção."
        )
    if abs(size[0] / size[1] - output[0] / output[1]) > 0.01:
        check.warnings.append("Proporção diferente da saída.")
    return check


def import_mask(
    session: Session,
    storage: Storage,
    operation_id: int,
    path: Path,
    *,
    name: str | None = None,
    mask_id: int | None = None,
    output: tuple[int, int] = (1080, 1920),
) -> tuple[MaskVersion, MaskCheck]:
    """Cria a máscara (ou uma nova versão dela, com `mask_id`)."""
    check = validate_png(path, output)
    if mask_id is None:
        mask = MaskAsset(operation_id=operation_id, name=(name or path.stem).strip()[:200])
        session.add(mask)
        session.flush()
    else:
        mask = session.get(MaskAsset, mask_id)
        if mask is None or mask.operation_id != operation_id:
            raise MaskError("Máscara não encontrada nesta operação.")
    current = session.scalar(
        select(func.max(MaskVersion.version)).where(MaskVersion.mask_id == mask.id)
    )
    version_number = (current or 0) + 1
    key = f"operations/{operation_id}/masks/{mask.id}/{version_number}.png"
    storage.put_file(key, path, "image/png")
    version = MaskVersion(
        mask_id=mask.id,
        version=version_number,
        file_key=key,
        width=check.width,
        height=check.height,
        has_alpha=check.has_alpha,
        checksum=sha256_file(path),
    )
    session.add(version)
    session.add(
        Event(
            entity="mask",
            entity_id=mask.id,
            operation_id=operation_id,
            action="version_added",
            detail={"version": version_number, "warnings": check.warnings},
        )
    )
    session.flush()
    return version, check


def latest_version(session: Session, mask_id: int) -> MaskVersion | None:
    return session.scalar(
        select(MaskVersion)
        .where(MaskVersion.mask_id == mask_id)
        .order_by(MaskVersion.version.desc())
        .limit(1)
    )


def list_masks(session: Session, operation_id: int) -> list[tuple[MaskAsset, list[MaskVersion]]]:
    masks = session.scalars(
        select(MaskAsset).where(MaskAsset.operation_id == operation_id).order_by(MaskAsset.id)
    )
    return [
        (
            mask,
            list(
                session.scalars(
                    select(MaskVersion)
                    .where(MaskVersion.mask_id == mask.id)
                    .order_by(MaskVersion.version.desc())
                )
            ),
        )
        for mask in masks
    ]
