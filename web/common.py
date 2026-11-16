"""Peças comuns às telas: renderização, login obrigatório e sessão do banco."""

from collections.abc import Iterator

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

# Menu lateral (Task 25.1). As telas ainda não construídas mostram a task que as entrega.
MENU = [
    {"label": "Dashboard", "href": "/", "task": "Task 25"},
    {"label": "Operações", "href": "/operacoes", "task": "Task 4"},
    {"label": "Fila", "href": "/fila", "task": "Task 8"},
    {"label": "Aprovação", "href": "/aprovacao", "task": "Task 18"},
    {"label": "Publicações", "href": "/publicacoes", "task": "Task 21"},
    {"label": "Contas", "href": "/contas", "task": "Task 19"},
]


class NotLoggedIn(Exception):
    """Levantada por `require_user`; vira um redirecionamento para /login."""


def render(request: Request, name: str, status_code: int = 200, **context) -> Response:
    context.setdefault("menu", MENU)
    context.setdefault("user", request.session.get("user"))
    templates = request.app.state.templates
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def require_user(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise NotLoggedIn()
    return user


def db_session(request: Request) -> Iterator[Session]:
    """Uma sessão por requisição; confirmada se a rota terminar sem erro."""
    session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
