"""Estado dos workers da VPS a partir do sinal de vida gravado no banco."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.models import WorkerHeartbeat

ROLES = {"buscador": "Buscador", "editor": "Editor", "postador": "Postador", "limpeza": "Limpeza"}
ONLINE_FOR = timedelta(minutes=3)


def beat(
    session: Session,
    role: str,
    host: str,
    now: datetime | None = None,
    version: str | None = None,
) -> None:
    now = now or datetime.now(UTC)
    stmt = pg_insert(WorkerHeartbeat).values(
        role=role, host=host[:100], at=now, version=(version or None)
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["role", "host"],
            set_={"at": stmt.excluded.at, "version": stmt.excluded.version},
        )
    )


def status(session: Session, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    last: dict[str, WorkerHeartbeat] = {}
    for hb in session.scalars(select(WorkerHeartbeat)):
        if hb.role not in last or hb.at > last[hb.role].at:
            last[hb.role] = hb
    out = []
    for role, label in ROLES.items():
        hb = last.get(role)
        out.append(
            {
                "role": role,
                "name": label,
                "at": hb.at if hb else None,
                "online": bool(hb and now - hb.at < ONLINE_FOR),
                "version": (hb.version or "") if hb else "",
            }
        )
    return out


def outdated(statuses: list[dict], site_version: str) -> list[str]:
    """Workers no ar com código diferente do site. Sem versão conhecida, não dá para dizer."""
    if not site_version:
        return []
    return [
        w["name"] for w in statuses if w["online"] and w["version"] and w["version"] != site_version
    ]
