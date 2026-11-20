"""Limite de uso do Cloudflare R2 para nunca sair da franquia grátis.

A Cloudflare não tem um teto de gastos para o R2: passou da franquia, cobra. Por isso a própria
ferramenta conta o que faz no bucket e trava antes do limite:

- Classe A (gravar e listar): 1 milhão por mês grátis.
- Classe B (ler): 10 milhões por mês grátis.
- Armazenamento: 10 GB-mês grátis. A ferramenta mede o bucket de hora em hora (worker Limpeza)
  e soma cada arquivo enviado na hora. Usar o pico, e não a média do mês, deixa a conta folgada.

As contas são por mês do calendário (UTC). Ao chegar no percentual escolhido (padrão 80% da
franquia), gravações e leituras param com `QuotaExceeded`. Os workers tentam de novo mais
tarde; a interface mostra o aviso. Apagar arquivos é grátis e nunca é bloqueado.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.models import AppSetting, R2Usage
from core.queue import RetryableError

log = logging.getLogger("usage")

GB = 1024**3
FREE_TIER = {"class_a": 1_000_000, "class_b": 10_000_000, "storage_bytes": 10 * GB}
LABELS = {
    "class_a": "Gravações e listagens (Classe A)",
    "class_b": "Leituras (Classe B)",
    "storage_bytes": "Armazenamento",
}
DEFAULT_PCT = 80
PCT_KEY = "r2_limit_pct"
MEASURED_KEY = "r2_measured_at"


class QuotaExceeded(RetryableError):
    """Chegou no limite do mês: a tarefa volta para a fila e tenta mais tarde."""


def month_of(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m")


def get_setting(session: Session, name: str, default: str = "") -> str:
    row = session.get(AppSetting, name)
    return row.value if row is not None else default


def set_setting(session: Session, name: str, value: str) -> None:
    row = session.get(AppSetting, name)
    if row is None:
        session.add(AppSetting(name=name, value=value))
    else:
        row.value = value
    session.flush()


def limit_pct(session: Session) -> int:
    try:
        return max(10, min(100, int(get_setting(session, PCT_KEY, str(DEFAULT_PCT)))))
    except ValueError:
        return DEFAULT_PCT


def limits(pct: int) -> dict[str, int]:
    return {metric: free * pct // 100 for metric, free in FREE_TIER.items()}


def values(session: Session, month: str | None = None) -> dict[str, int]:
    month = month or month_of()
    out = dict.fromkeys(FREE_TIER, 0)
    for row in session.scalars(select(R2Usage).where(R2Usage.month == month)):
        out[row.metric] = row.value
    return out


def add(session: Session, metric: str, amount: int, month: str | None = None) -> None:
    if amount <= 0:
        return
    stmt = insert(R2Usage).values(month=month or month_of(), metric=metric, value=amount)
    stmt = stmt.on_conflict_do_update(
        index_elements=["month", "metric"], set_={"value": R2Usage.value + amount}
    )
    session.execute(stmt)


def set_storage(session: Session, size: int, now: datetime | None = None) -> None:
    """Medição do bucket: o armazenamento do mês é o maior valor medido."""
    month = month_of(now)
    stmt = insert(R2Usage).values(month=month, metric="storage_bytes", value=size)
    stmt = stmt.on_conflict_do_update(
        index_elements=["month", "metric"],
        set_={"value": func.greatest(R2Usage.value, size)},
    )
    session.execute(stmt)
    set_setting(session, MEASURED_KEY, (now or datetime.now(UTC)).isoformat())


@dataclass
class UsageRow:
    metric: str
    label: str
    value: int
    limit: int
    free: int

    @property
    def pct_of_limit(self) -> int:
        return min(100, round(100 * self.value / self.limit)) if self.limit else 0

    @property
    def level(self) -> str:
        p = self.pct_of_limit
        return "bad" if p >= 100 else ("warn" if p >= 75 else "ok")

    def fmt(self, n: int) -> str:
        if self.metric == "storage_bytes":
            return f"{n / GB:.2f} GB"
        return f"{n:,}".replace(",", ".")


def report(session: Session, now: datetime | None = None) -> dict:
    pct = limit_pct(session)
    lim = limits(pct)
    vals = values(session, month_of(now))
    rows = [UsageRow(m, LABELS[m], vals[m], lim[m], FREE_TIER[m]) for m in FREE_TIER]
    measured = get_setting(session, MEASURED_KEY)
    return {
        "pct": pct,
        "rows": rows,
        "blocked": any(r.value >= r.limit for r in rows),
        "measured_at": datetime.fromisoformat(measured) if measured else None,
        "month": month_of(now),
    }


class UsageMeter:
    """Conta as operações no bucket e bloqueia ao chegar no limite.

    O limite é lido do banco no máximo a cada `ttl` segundos. Cada operação é gravada na hora
    (as operações do R2 são poucas: um vídeo gera algumas dezenas).
    """

    def __init__(self, session_factory, ttl: float = 30.0):
        self.session_factory = session_factory
        self.ttl = ttl
        self._snap: tuple[dict[str, int], dict[str, int]] | None = None
        self._at = -1e9

    def _snapshot(self) -> tuple[dict[str, int], dict[str, int]]:
        now = time.monotonic()
        if self._snap is None or now - self._at >= self.ttl:
            with self.session_factory() as session:
                self._snap = (values(session), limits(limit_pct(session)))
            self._at = now
        return self._snap

    def check(self, metric: str, extra: int = 0) -> None:
        try:
            vals, lim = self._snapshot()
        except QuotaExceeded:
            raise
        except Exception:  # noqa: BLE001 - sem banco: não há como contar, então não grava
            log.exception("contador do R2 indisponível")
            raise QuotaExceeded(
                "Contador de uso do R2 indisponível (banco fora do ar): operação adiada."
            ) from None
        if vals[metric] + extra >= lim[metric]:
            raise QuotaExceeded(
                f"Limite mensal do R2 atingido: {LABELS[metric]}. Nada é cobrado; a operação "
                "volta a funcionar no mês que vem ou se você aumentar o limite no Dashboard."
            )

    def add(self, metric: str, amount: int = 1) -> None:
        if amount <= 0:
            return
        try:
            with self.session_factory() as session:
                add(session, metric, amount)
                session.commit()
        except Exception:  # noqa: BLE001 - a operação já aconteceu; só registra o erro
            log.exception("falha ao contar uso do R2")
        if self._snap is not None:
            self._snap[0][metric] = self._snap[0].get(metric, 0) + amount
