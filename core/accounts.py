"""Contas das redes (Task 19): conexão por OAuth, token criptografado, pausa e revogação.

O token só existe descriptografado dentro do worker na hora do envio (e na interface no
momento de conectar/testar). Conta em erro não publica; os envios dela ficam esperando e as
outras contas seguem normalmente (19.6).
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Account, Event
from core.operations import OperationError
from core.security import TokenCipher

ACTIONS = {"pause": "paused", "resume": "connected", "revoke": "revoked"}


def _event(session: Session, account: Account, action: str, detail: dict | None = None) -> None:
    session.add(Event(entity="account", entity_id=account.id, action=action, detail=detail))


def connect(
    session: Session,
    cipher: TokenCipher,
    *,
    platform: str,
    external_id: str,
    name: str,
    credentials: str,
) -> Account:
    """Cria a conta ou reconecta a existente (mesmo canal), guardando o token criptografado."""
    account = session.scalar(
        select(Account).where(Account.platform == platform, Account.external_id == external_id)
    )
    if account is None:
        account = Account(platform=platform, external_id=external_id, name=name)
        session.add(account)
    account.name = name[:200]
    account.token_encrypted = cipher.encrypt(credentials)
    account.status = "connected"
    session.flush()
    _event(session, account, "connected", {"platform": platform})
    return account


def credentials(cipher: TokenCipher, account: Account) -> str:
    if not account.token_encrypted:
        raise OperationError("Conta sem token. Conecte de novo.")
    return cipher.decrypt(account.token_encrypted)


def change_status(session: Session, account: Account, action: str) -> None:
    if action not in ACTIONS:
        raise OperationError("Ação desconhecida.")
    if action == "resume" and not account.token_encrypted:
        raise OperationError("Conta revogada: conecte de novo pelo OAuth.")
    account.status = ACTIONS[action]
    if action == "revoke":
        account.token_encrypted = None
    _event(session, account, action)


def mark_error(session: Session, account: Account, reason: str) -> None:
    if account.status != "error":
        account.status = "error"
        _event(session, account, "error", {"reason": reason[:500]})


def update_settings(session: Session, account: Account, daily_limit: int, timezone: str) -> None:
    if not 0 <= daily_limit <= 50:
        raise OperationError("Limite diário deve ficar entre 0 e 50.")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise OperationError(f"Fuso horário desconhecido: {timezone}") from exc
    account.daily_limit = daily_limit
    account.timezone = timezone
    _event(session, account, "settings", {"daily_limit": daily_limit, "timezone": timezone})


def list_accounts(session: Session) -> list[Account]:
    return list(session.scalars(select(Account).order_by(Account.platform, Account.name)))


def usable(account: Account) -> bool:
    return account.status == "connected"
