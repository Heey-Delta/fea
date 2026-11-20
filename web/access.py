"""Tela Acessos: tudo o que precisa de login ou chave, num lugar só (Tasks 19 e 28).

- Ferramenta: login do GitHub, banco, chave de criptografia, armazenamento e endereço público
  (vêm das variáveis de ambiente; a tela só mostra o estado).
- Busca: chaves do Reddit e do X, preenchidas aqui e guardadas criptografadas.
- Publicação: chaves dos apps (Google, TikTok, Meta) e o login OAuth de cada conta/canal.
"""

import secrets
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import accounts as acc
from core import credentials as creds
from core.models import Account, Event, PublishJob
from core.operations import OperationError
from networks import PLATFORM_LABEL
from networks.base import AdapterError
from web.common import db_session, render, require_user
from web.public import public_urls, vps_serializer

router = APIRouter(dependencies=[Depends(require_user)])

TIMEZONES = ("America/Sao_Paulo", "America/Manaus", "America/New_York", "Europe/Lisbon", "UTC")
OAUTH_PLATFORMS = ("youtube", "tiktok", "instagram")


def flash(request: Request, kind: str, text: str) -> None:
    request.session["flash"] = {"kind": kind, "text": text}


def settings_for(request: Request, session: Session):
    """Settings com as chaves salvas pela interface."""
    return creds.effective(session, request.app.state.settings)


def adapter_of(request: Request, platform: str, settings):
    return request.app.state.adapter_factory(platform, settings)


def redirect_uri(request: Request, platform: str) -> str:
    base = request.app.state.settings.public_base_url
    if base:
        return f"{base.rstrip('/')}/contas/{platform}/retorno"
    return str(request.url_for("oauth_callback", platform=platform))


def tool_status(request: Request) -> list[dict]:
    s = request.app.state.settings
    login = request.app.state.login_settings()
    github = bool(login.github_client_id and login.github_client_secret and s.github_allowed_id)
    return [
        {
            "name": "Login da ferramenta (GitHub)",
            "ok": github,
            "env": "app do GitHub (criado pela tela de login) e GITHUB_ALLOWED_ID",
            "hint": f"Callback: {(s.public_base_url or '').rstrip('/')}/auth/github/callback"
            if s.public_base_url
            else "Defina PUBLIC_BASE_URL para fixar o endereço de retorno.",
        },
        {
            "name": "Endereço público",
            "ok": bool(s.public_base_url),
            "env": "PUBLIC_BASE_URL",
            "hint": s.public_base_url or "Ex.: https://fea-rho.vercel.app",
        },
        {
            "name": "Chave de criptografia",
            "ok": bool(s.token_encryption_key),
            "env": "TOKEN_ENCRYPTION_KEY",
            "hint": "Já definida na Vercel. A VPS recebe pelo comando de instalação (Workers).",
        },
        {
            "name": "Contato público (opcional)",
            "optional": True,
            "ok": bool(s.contact_email),
            "env": "CONTACT_EMAIL, OPERATOR_NAME",
            "hint": "Aparece nas páginas de privacidade e termos que as plataformas pedem.",
        },
        db_status(request),
    ]


def db_status(request: Request) -> dict:
    from core.migrate import status

    s = request.app.state.settings
    row = {"name": "Banco de dados (Neon)", "env": "DATABASE_URL", "migrate": False}
    if "localhost" in s.database_url and s.is_production:
        return {**row, "ok": False, "hint": "Crie o banco: Vercel → Storage → Neon."}
    try:
        st = status(direct_engine(request))
    except Exception as exc:  # noqa: BLE001
        return {**row, "ok": False, "hint": f"Sem conexão com o banco: {str(exc)[:120]}"}
    if st["up_to_date"]:
        return {**row, "ok": True, "hint": f"Conectado e atualizado (migração {st['head']})."}
    current = st["current"] or "nenhuma"
    return {
        **row,
        "ok": False,
        "migrate": True,
        "hint": f"Conectado. Migração aplicada: {current}; a mais nova é {st['head']}.",
    }


def direct_engine(request: Request):
    """Conexão direta (sem o pool do Neon) para migrar: o advisory lock exige sessão fixa."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from core.db import sqlalchemy_url

    s = request.app.state.settings
    if not s.database_url_unpooled:
        return request.app.state.session_factory.kw["bind"]
    return create_engine(sqlalchemy_url(s.direct_database_url), poolclass=NullPool)


@router.post("/contas/vps/comando")
def vps_command(request: Request, session: Session = Depends(db_session)) -> Response:
    """Gera o comando de instalação da VPS (uma vez, 30 minutos)."""
    s = request.app.state.settings
    if not s.token_encryption_key:
        flash(request, "error", "Defina TOKEN_ENCRYPTION_KEY antes de instalar a VPS.")
        return RedirectResponse("/contas#vps", status_code=303)
    nonce = secrets.token_urlsafe(12)
    token = vps_serializer(s.secret_key).dumps({"n": nonce})
    base = (s.public_base_url or str(request.base_url)).rstrip("/")
    request.session["vps_cmd"] = f"bash <(curl -fsSL {base}/vps/instalar/{token})"
    session.add(Event(entity="vps_install", action="issued", detail={"nonce": nonce}))
    flash(request, "ok", "Comando gerado. Vale 30 minutos e uma única vez.")
    return RedirectResponse("/contas#vps", status_code=303)


@router.post("/contas/vps/env")
def worker_env(request: Request, session: Session = Depends(db_session)) -> Response:
    """Arquivo .env dos workers para rodar no próprio computador (Docker Desktop).

    Mesmo conteúdo que o comando da VPS grava: banco direto e chave de criptografia. Só sai
    para quem está logado; fica registrado em events.
    """
    s = request.app.state.settings
    if not s.token_encryption_key:
        flash(request, "error", "Defina TOKEN_ENCRYPTION_KEY antes de baixar o arquivo.")
        return RedirectResponse("/contas#vps", status_code=303)
    session.add(Event(entity="vps_install", action="env_downloaded", detail={}))
    session.commit()
    body = (
        "# Workers da Ferramenta de Operações. Guarde este arquivo como deploy/.env\n"
        "# Ele dá acesso ao banco: não envie para ninguém nem coloque no Git.\n"
        "APP_ENV=production\n"
        f"DATABASE_URL={s.direct_database_url}\n"
        f"TOKEN_ENCRYPTION_KEY={s.token_encryption_key}\n"
    )
    return Response(
        body,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="fea-workers.env"',
            "Cache-Control": "no-store, private",
        },
    )


@router.post("/contas/banco/migrar")
def migrate(request: Request) -> Response:
    from core.migrate import upgrade

    try:
        st = upgrade(direct_engine(request))
        flash(request, "ok", f"Banco atualizado até a migração {st['head']}.")
    except Exception as exc:  # noqa: BLE001
        flash(request, "error", f"Migração falhou: {str(exc)[:300]}")
    return RedirectResponse("/contas", status_code=303)


def worker_status(session: Session) -> list[dict]:
    from core.workers import status

    try:
        return status(session)
    except Exception:  # noqa: BLE001 - tabela ainda não migrada
        session.rollback()
        return []


@router.get("/contas", response_class=HTMLResponse)
def page(request: Request, session: Session = Depends(db_session)) -> Response:
    settings = request.app.state.settings
    accounts = acc.list_accounts(session)
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today = dict(
        session.execute(
            select(PublishJob.account_id, func.count())
            .where(PublishJob.status == "published", PublishJob.published_at >= midnight)
            .group_by(PublishJob.account_id)
        ).all()
    )
    by_platform: dict[str, list[Account]] = {p: [] for p in OAUTH_PLATFORMS}
    for account in accounts:
        by_platform.setdefault(account.platform, []).append(account)
    statuses = creds.status(session, settings)
    return render(
        request,
        "access.html",
        active="/contas",
        tool=tool_status(request),
        infra=[s for s in statuses if s.service.group == "infra"],
        workers=worker_status(session),
        vps_cmd=request.session.pop("vps_cmd", None),
        search=[s for s in statuses if s.service.group == "busca"],
        publishing=[s for s in statuses if s.service.group == "publicacao"],
        by_platform=by_platform,
        platform_label=PLATFORM_LABEL,
        today=today,
        redirect_uri=lambda p: redirect_uri(request, p),
        public_urls=public_urls(
            request.app.state.settings.public_base_url or str(request.base_url)
        ),
        can_save=bool(settings.token_encryption_key),
        timezones=TIMEZONES,
        flash=request.session.pop("flash", None),
    )


# --- Chaves dos serviços ------------------------------------------------------------------


def get_service(service_id: str) -> creds.Service:
    service = creds.SERVICE_BY_ID.get(service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Serviço desconhecido")
    return service


@router.post("/contas/chaves/{service_id}")
async def save_keys(request: Request, service_id: str, session: Session = Depends(db_session)):
    service = get_service(service_id)
    form = await request.form()
    values = {f.name: str(form.get(f.name) or "") for f in service.fields}
    try:
        saved = creds.save(session, request.app.state.settings, values)
    except creds.CredentialError as exc:
        flash(request, "error", str(exc))
        return RedirectResponse(f"/contas#{service_id}", status_code=303)
    if service_id == "r2" and hasattr(request.app.state.storage, "refresh"):
        request.app.state.storage.refresh()
    if saved:
        flash(request, "ok", f"{service.name}: {len(saved)} campo(s) salvo(s).")
    else:
        flash(request, "error", f"{service.name}: nada preenchido.")
    return RedirectResponse(f"/contas#{service_id}", status_code=303)


@router.post("/contas/chaves/{service_id}/limpar")
def clear_keys(request: Request, service_id: str, session: Session = Depends(db_session)):
    service = get_service(service_id)
    creds.clear(session, service_id)
    if hasattr(request.app.state.storage, "refresh"):
        request.app.state.storage.refresh()
    flash(request, "ok", f"{service.name}: chaves salvas pela interface removidas.")
    return RedirectResponse(f"/contas#{service_id}", status_code=303)


def test_reddit(settings, client: httpx.Client) -> str:
    from core.connectors.reddit import TOKEN_URL

    response = client.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(settings.reddit_client_id, settings.reddit_client_secret),
        headers={"User-Agent": settings.reddit_user_agent},
    )
    if response.status_code != 200 or "access_token" not in response.json():
        raise ValueError(f"Reddit recusou as chaves (HTTP {response.status_code}).")
    return "Reddit aceitou as chaves."


def test_x(settings, client: httpx.Client) -> str:
    from core.connectors.x import API

    response = client.get(
        f"{API}/tweets/search/recent",
        params={"query": "has:videos -is:retweet", "max_results": 10},
        headers={"Authorization": f"Bearer {settings.x_bearer_token}"},
    )
    if response.status_code == 200:
        return "X aceitou o token e a busca recente está liberada no plano."
    if response.status_code == 403:
        raise ValueError("Token aceito, mas o plano do X não libera a busca recente (403).")
    raise ValueError(f"X recusou o token (HTTP {response.status_code}).")


def test_drive(settings, client: httpx.Client) -> str:
    from core.connectors.base import SourceError
    from core.connectors.drive import DriveConnector

    try:
        connector = DriveConnector(settings, client=client, sleep=lambda _s: None)
        connector.token()
    except SourceError as exc:
        raise ValueError(str(exc)) from exc
    return (
        f"Google aceitou a conta de serviço. Compartilhe a pasta do Drive com "
        f"{connector.email} (Leitor) e use o link da pasta na fonte da operação."
    )


def test_r2(settings, client: httpx.Client) -> str:
    from core.storage import R2Storage

    if not settings.r2_configured:
        raise ValueError("preencha as quatro chaves.")
    storage = R2Storage(settings)
    try:
        storage.client.head_bucket(Bucket=settings.r2_bucket)
    except Exception as exc:  # noqa: BLE001 - botocore tem muitos tipos de erro
        raise ValueError(f"o R2 recusou o acesso ao bucket ({str(exc)[:160]}).") from exc
    return f"R2 ok: bucket {settings.r2_bucket} acessível."


@router.post("/contas/chaves/{service_id}/testar")
def test_keys(request: Request, service_id: str, session: Session = Depends(db_session)):
    service = get_service(service_id)
    settings = settings_for(request, session)
    testers = {"reddit": test_reddit, "x": test_x, "r2": test_r2, "drive": test_drive}
    if service_id not in testers:
        flash(request, "ok", f"{service.name}: o teste é a própria conexão de uma conta abaixo.")
        return RedirectResponse(f"/contas#{service_id}", status_code=303)
    try:
        with request.app.state.http_client_factory() as client:
            message = testers[service_id](settings, client)
        flash(request, "ok", message)
    except (ValueError, httpx.HTTPError) as exc:
        flash(request, "error", f"{service.name}: {exc}")
    return RedirectResponse(f"/contas#{service_id}", status_code=303)


# --- Login das contas (OAuth) -------------------------------------------------------------


def oauth_ready(settings, platform: str) -> list[str]:
    """Campos que faltam para conectar uma conta da plataforma."""
    service = creds.SERVICE_BY_ID[platform]
    missing = [f.label for f in service.fields if not getattr(settings, f.name, "")]
    if not settings.token_encryption_key:
        missing.append("TOKEN_ENCRYPTION_KEY")
    return missing


@router.get("/contas/{platform}/conectar")
def connect(request: Request, platform: str, session: Session = Depends(db_session)):
    if platform not in OAUTH_PLATFORMS:
        raise HTTPException(status_code=404, detail="Plataforma desconhecida")
    settings = settings_for(request, session)
    missing = oauth_ready(settings, platform)
    if missing:
        flash(request, "error", f"Para conectar, preencha antes: {', '.join(missing)}.")
        return RedirectResponse(f"/contas#{platform}", status_code=303)
    state = secrets.token_urlsafe(24)
    request.session[f"oauth_state_{platform}"] = state
    url = adapter_of(request, platform, settings).authorize_url(
        redirect_uri(request, platform), state
    )
    return RedirectResponse(url, status_code=302)


@router.get("/contas/{platform}/retorno", name="oauth_callback")
def callback(
    request: Request,
    platform: str,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
    session: Session = Depends(db_session),
) -> Response:
    if platform not in OAUTH_PLATFORMS:
        raise HTTPException(status_code=404, detail="Plataforma desconhecida")
    label = PLATFORM_LABEL[platform]
    expected = request.session.pop(f"oauth_state_{platform}", None)
    if error:
        flash(request, "error", f"{label} recusou a conexão: {error_description or error}.")
        return RedirectResponse(f"/contas#{platform}", status_code=303)
    if not expected or not secrets.compare_digest(expected, state) or not code:
        flash(request, "error", f"Retorno do {label} inválido (state). Tente conectar de novo.")
        return RedirectResponse(f"/contas#{platform}", status_code=303)
    settings = settings_for(request, session)
    adapter = adapter_of(request, platform, settings)
    try:
        credentials = adapter.exchange_code(code, redirect_uri(request, platform))
        external_id, name = adapter.account_info(credentials)
    except AdapterError as exc:
        flash(request, "error", f"Não foi possível conectar: {exc}")
        return RedirectResponse(f"/contas#{platform}", status_code=303)
    account = acc.connect(
        session,
        creds.cipher_for(settings),
        platform=platform,
        external_id=external_id,
        name=name,
        credentials=credentials,
    )
    flash(
        request,
        "ok",
        f"{label}: {account.name} conectada. Escolha a conta no bloco Publicador da operação.",
    )
    return RedirectResponse(f"/contas#{platform}", status_code=303)


# --- Ações por conta ----------------------------------------------------------------------


def get_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    return account


@router.post("/contas/{account_id:int}/acao")
def account_action(
    request: Request,
    account_id: int,
    acao: str = Form(...),
    session: Session = Depends(db_session),
) -> Response:
    account = get_account(session, account_id)
    try:
        acc.change_status(session, account, acao)
        flash(request, "ok", f"{account.name}: {account.status}.")
    except OperationError as exc:
        flash(request, "error", str(exc))
    return RedirectResponse(f"/contas#{account.platform}", status_code=303)


@router.post("/contas/{account_id:int}/testar")
def account_test(request: Request, account_id: int, session: Session = Depends(db_session)):
    account = get_account(session, account_id)
    settings = settings_for(request, session)
    try:
        cipher = creds.cipher_for(settings)
        if cipher is None:
            raise OperationError("Defina TOKEN_ENCRYPTION_KEY.")
        adapter = adapter_of(request, account.platform, settings)
        credentials = acc.credentials(cipher, account)
        fresh = adapter.fresh_credentials(credentials)
        if fresh != credentials:
            account.token_encrypted = cipher.encrypt(fresh)
        _, name = adapter.account_info(fresh)
        if account.status == "error":
            account.status = "connected"
        flash(request, "ok", f"Conexão ok: {name}.")
    except (AdapterError, OperationError, ValueError) as exc:
        acc.mark_error(session, account, str(exc))
        flash(request, "error", f"Falhou: {exc}")
    return RedirectResponse(f"/contas#{account.platform}", status_code=303)


@router.post("/contas/{account_id:int}/config")
def account_config(
    request: Request,
    account_id: int,
    daily_limit: int = Form(...),
    timezone: str = Form(...),
    session: Session = Depends(db_session),
) -> Response:
    account = get_account(session, account_id)
    try:
        acc.update_settings(session, account, daily_limit, timezone)
        flash(request, "ok", f"{account.name}: limite {daily_limit}/dia, fuso {timezone}.")
    except OperationError as exc:
        flash(request, "error", str(exc))
    return RedirectResponse(f"/contas#{account.platform}", status_code=303)
