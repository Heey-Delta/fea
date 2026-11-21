"""Diagnóstico em texto: tudo o que explica por que uma operação parou, numa tela só.

Feito para copiar e colar no suporte. Não inclui segredos: nada de chaves, tokens ou URLs de
banco; a pasta do Drive aparece só pelo final do id.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import workers
from core.editor import preset as pr
from core.models import Execution, Item, Job, Operation, Source
from core.operations import current_config, linked_account_ids
from core.version import code_version


def _ago(at: datetime | None, now: datetime) -> str:
    if at is None:
        return "nunca"
    seconds = int((now - at).total_seconds())
    if seconds < 120:
        return f"há {seconds}s"
    if seconds < 7200:
        return f"há {seconds // 60} min"
    return f"há {seconds // 3600} h"


def _node(config: dict, kind: str) -> dict:
    node = next((n for n in config.get("nodes") or [] if n.get("type") == kind), None)
    return (node or {}).get("config") or {}


def _short_ref(source: Source) -> str:
    ref = source.reference or ""
    return f"…{ref[-6:]}" if source.type == "drive" and len(ref) > 6 else ref


def report(session: Session, migration: dict | None = None, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    lines = [f"DIAGNÓSTICO · {now:%d/%m %H:%M} UTC · site {code_version() or '?'}"]
    if migration:
        mark = "ok" if migration.get("up_to_date") else "PENDENTE → Acessos › Aplicar migrações"
        lines.append(f"banco: {migration.get('current')} (código: {migration.get('head')}) {mark}")

    lines.append("\nWORKERS")
    for w in workers.status(session, now):
        state = "no ar" if w["online"] else "FORA"
        lines.append(
            f"  {w['role']:<10} {state:<6} visto {_ago(w['at'], now)}  v{w['version'] or '?'}"
        )

    since = now - timedelta(hours=6)
    jobs = session.execute(
        select(Job.type, Job.status, func.count())
        .where(Job.updated_at >= since)
        .group_by(Job.type, Job.status)
    ).all()
    lines.append("\nTAREFAS (6 h): " + (", ".join(f"{t}/{s}={n}" for t, s, n in jobs) or "nenhuma"))
    stuck = session.scalars(
        select(Job).where(Job.status == "running").order_by(Job.locked_at).limit(5)
    ).all()
    for job in stuck:
        lines.append(
            f"  rodando #{job.id} {job.type} por {job.locked_by} desde {_ago(job.locked_at, now)}"
        )
    failed = session.scalars(
        select(Job)
        .where(Job.last_error.is_not(None), Job.updated_at >= since)
        .order_by(Job.updated_at.desc())
        .limit(6)
    ).all()
    for job in failed:
        lines.append(f"  erro #{job.id} {job.type}/{job.status}: {(job.last_error or '')[:220]}")

    operations = session.scalars(
        select(Operation).where(Operation.status != "archived").order_by(Operation.id)
    ).all()
    for op in operations:
        lines.append(f"\nOPERAÇÃO #{op.id} {op.name} [{op.status}]")
        try:
            config = current_config(session, op).config
        except Exception:  # noqa: BLE001 - operação sem configuração
            lines.append("  sem configuração salva")
            continue
        fishing, approval, publish = (
            _node(config, "fishing"),
            _node(config, "approval"),
            _node(config, "publish"),
        )
        preset = pr.from_config(config)
        lines.append(
            f"  busca: mídia={fishing.get('accepted_media')} tags={fishing.get('tags') or []} "
            f"meta={fishing.get('target_x')} "
            f"repetidos={'barra' if fishing.get('block_duplicates') else 'passam'} "
            f"marca_dagua={'recusa' if fishing.get('reject_watermarks', True) else 'aceita'}"
        )
        lines.append(
            f"  edição: agrupar={preset['video'].get('group_images') or 'não'} "
            f"seg/imagem={preset['video']['image_duration_s']} áudio={preset['audio']['mode']} "
            f"músicas={len(preset['audio']['library'])} problemas={pr.validate(preset) or 'nenhum'}"
        )
        lines.append(
            f"  aprovação={'automática' if approval.get('auto_approve') else 'manual'} "
            f"agenda={'automática' if publish.get('automatic') else 'manual'} "
            f"contas={len(linked_account_ids(config))} auto={config.get('automation')}"
        )
        for src in session.scalars(select(Source).where(Source.operation_id == op.id)):
            lines.append(
                f"  fonte #{src.id} {src.type} {_short_ref(src)} [{src.status}] "
                f"{('erro: ' + src.last_error[:160]) if src.last_error else ''}"
            )
        for ex in session.scalars(
            select(Execution)
            .where(Execution.operation_id == op.id)
            .order_by(Execution.id.desc())
            .limit(3)
        ):
            lines.append(
                f"  execução #{ex.id} {ex.status} {_ago(ex.started_at, now)} meta={ex.target_x} "
                f"stats={ex.stats or {}} motivo={ex.shortfall_reason or '—'}"
            )
        counts = Counter(
            (status, (reason or "")[:70])
            for status, reason in session.execute(
                select(Item.status, Item.status_reason).where(Item.operation_id == op.id)
            )
        )
        for (status, reason), n in counts.most_common(12):
            lines.append(f"  itens {status}={n}{(' · ' + reason) if reason else ''}")
    return "\n".join(lines)
