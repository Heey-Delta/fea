"""Estado dos workers da VPS a partir do sinal de vida gravado no banco."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.models import WorkerHeartbeat

ROLES = {"buscador": "Buscador", "editor": "Editor", "postador": "Postador", "limpeza": "Limpeza"}
ONLINE_FOR = timedelta(minutes=3)


def beat(session: Session, role: str, host: str, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    stmt = pg_insert(WorkerHeartbeat).values(role=role, host=host[:100], at=now)
    session.execute(
        stmt.on_conflict_do_update(index_elements=["role", "host"], set_={"at": stmt.excluded.at})
    )


def status(session: Session, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    last: dict[str, datetime] = {}
    for hb in session.scalars(select(WorkerHeartbeat)):
        if hb.role not in last or hb.at > last[hb.role]:
            last[hb.role] = hb.at
    return [
        {
            "role": role,
            "name": label,
            "at": last.get(role),
            "online": bool(last.get(role) and now - last[role] < ONLINE_FOR),
        }
        for role, label in ROLES.items()
    ]
