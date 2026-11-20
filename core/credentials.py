"""Chaves dos serviços preenchidas pela tela Acessos (Task 28).

Cada chave pode vir de uma variável de ambiente (Vercel e VPS) ou do banco, criptografada com
TOKEN_ENCRYPTION_KEY. A variável de ambiente tem precedência. Preencher pela interface tem a
vantagem de valer na hora para a interface e para os workers, sem redeploy.

O valor nunca volta para o navegador: a tela só mostra se está preenchido e os 4 últimos
caracteres.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.models import AppCredential, Event
from core.security import TokenCipher


@dataclass(frozen=True)
class Field:
    name: str  # atributo em Settings (e variável de ambiente em maiúsculas)
    label: str
    secret: bool = True

    @property
    def env(self) -> str:
        return self.name.upper()


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    group: str  # "busca" | "publicacao"
    fields: tuple[Field, ...]
    oauth_platform: str | None = None  # contas conectadas por OAuth (publicação)
    console: str = ""  # onde criar o app
    note: str = ""
    any_field: bool = False  # pronto com qualquer campo preenchido (opções alternativas)


SERVICES: tuple[Service, ...] = (
    Service(
        "github",
        "Login da ferramenta (GitHub)",
        "login",
        (
            Field("github_client_id", "Client ID", secret=False),
            Field("github_client_secret", "Client secret"),
        ),
        console="https://github.com/settings/apps",
        note="Criado em um clique pela tela de login (fluxo App Manifest do GitHub).",
    ),
    Service(
        "r2",
        "Cloudflare R2",
        "infra",
        (
            Field("r2_account_id", "Account ID", secret=False),
            Field("r2_access_key_id", "Access Key ID", secret=False),
            Field("r2_secret_access_key", "Secret Access Key"),
            Field("r2_bucket", "Bucket", secret=False),
        ),
        console="https://dash.cloudflare.com/?to=/:account/r2/overview",
        note="Originais, vídeos editados e máscaras. Sem R2 os arquivos ficam no disco local "
        "(só desenvolvimento). Obrigatório para o Instagram.",
    ),
    Service(
        "reddit",
        "Reddit",
        "busca",
        (
            Field("reddit_client_id", "Client ID", secret=False),
            Field("reddit_client_secret", "Client secret"),
            Field("reddit_user_agent", "User-Agent", secret=False),
        ),
        console="https://www.reddit.com/prefs/apps",
        note='App do tipo "script". Uso não comercial na API gratuita.',
    ),
    Service(
        "drive",
        "Google Drive",
        "busca",
        (
            Field("google_drive_service_account", "Chave JSON da conta de serviço (opção 1)"),
            Field("google_drive_api_key", "Chave de API (opção 2, pasta com link público)"),
        ),
        console="https://console.cloud.google.com/apis/credentials",
        note="Vídeos que caírem numa pasta do Drive viram itens da operação. Preencha UMA das "
        "duas opções. Opção 1: conta de serviço (pasta privada; algumas contas bloqueiam a "
        'criação da chave). Opção 2: chave de API, com a pasta compartilhada como "qualquer '
        'pessoa com o link". Grátis e sem verificação do Google.',
        any_field=True,
    ),
    Service(
        "x",
        "X (Twitter)",
        "busca",
        (Field("x_bearer_token", "Bearer Token"),),
        console="https://developer.x.com/en/portal/dashboard",
        note="A busca da API v2 exige plano pago (Basic ou superior).",
    ),
    Service(
        "youtube",
        "YouTube Shorts",
        "publicacao",
        (
            Field("google_client_id", "Client ID", secret=False),
            Field("google_client_secret", "Client secret"),
        ),
        oauth_platform="youtube",
        console="https://console.cloud.google.com/apis/credentials",
        note="Sem a auditoria do Google, os vídeos enviados pela API ficam privados.",
    ),
    Service(
        "tiktok",
        "TikTok",
        "publicacao",
        (
            Field("tiktok_client_key", "Client key", secret=False),
            Field("tiktok_client_secret", "Client secret"),
        ),
        oauth_platform="tiktok",
        console="https://developers.tiktok.com/apps",
        note="Sem a auditoria do TikTok, os posts ficam visíveis só para o dono (SELF_ONLY).",
    ),
    Service(
        "instagram",
        "Instagram Reels",
        "publicacao",
        (
            Field("instagram_app_id", "Instagram App ID", secret=False),
            Field("instagram_app_secret", "Instagram App Secret"),
        ),
        oauth_platform="instagram",
        console="https://developers.facebook.com/apps",
        note="Conta profissional (Criador ou Empresa). Precisa do R2: o Instagram baixa o vídeo "
        "por uma URL pública.",
    ),
)
SERVICE_BY_ID = {s.id: s for s in SERVICES}
FIELD_BY_NAME = {f.name: f for s in SERVICES for f in s.fields}


class CredentialError(Exception):
    pass


def cipher_for(settings: Settings) -> TokenCipher | None:
    return TokenCipher(settings.token_encryption_key) if settings.token_encryption_key else None


def stored(session: Session, settings: Settings) -> dict[str, str]:
    """Valores do banco já descriptografados (os ilegíveis são ignorados)."""
    cipher = cipher_for(settings)
    if cipher is None:
        return {}
    values = {}
    for row in session.scalars(select(AppCredential)):
        try:
            values[row.name] = cipher.decrypt(row.value_encrypted)
        except Exception:  # noqa: BLE001 - chave trocada: o valor precisa ser preenchido de novo
            continue
    return values


def effective(session: Session, settings: Settings) -> Settings:
    """Settings com as chaves do banco preenchendo o que a variável de ambiente deixou vazio."""
    values = stored(session, settings)
    update = {
        name: value
        for name, value in values.items()
        if name in FIELD_BY_NAME and value and not _from_env(settings, name)
    }
    return settings.model_copy(update=update) if update else settings


def _from_env(settings: Settings, name: str) -> bool:
    value = getattr(settings, name, "")
    default = type(settings).model_fields[name].default
    return bool(value) and value != default


def save(session: Session, settings: Settings, values: dict[str, str]) -> list[str]:
    """Grava os campos preenchidos. Campo vazio não apaga (use `clear`). Devolve os gravados."""
    cipher = cipher_for(settings)
    if cipher is None:
        raise CredentialError("Defina TOKEN_ENCRYPTION_KEY antes de salvar chaves pela interface.")
    saved = []
    for name, value in values.items():
        value = (value or "").strip()
        if name not in FIELD_BY_NAME or not value:
            continue
        row = session.get(AppCredential, name)
        if row is None:
            row = AppCredential(name=name, value_encrypted="")
            session.add(row)
        row.value_encrypted = cipher.encrypt(value)
        saved.append(name)
    if saved:
        session.add(Event(entity="credential", action="saved", detail={"fields": saved}))
    session.flush()
    return saved


def clear(session: Session, service_id: str) -> None:
    service = SERVICE_BY_ID.get(service_id)
    if service is None:
        raise CredentialError("Serviço desconhecido.")
    for field in service.fields:
        row = session.get(AppCredential, field.name)
        if row is not None:
            session.delete(row)
    session.add(Event(entity="credential", action="cleared", detail={"service": service_id}))
    session.flush()


@dataclass
class FieldStatus:
    field: Field
    source: str  # "env" | "banco" | ""
    hint: str  # últimos caracteres (ou o valor, se não for segredo)


@dataclass
class ServiceStatus:
    service: Service
    fields: list[FieldStatus]

    @property
    def ready(self) -> bool:
        if self.service.any_field:
            return any(f.source for f in self.fields)
        required = [f for f in self.fields if f.field.name != "reddit_user_agent"]
        return all(f.source for f in required)


def status(session: Session, settings: Settings) -> list[ServiceStatus]:
    values = stored(session, settings)
    out = []
    for service in SERVICES:
        fields = []
        for field in service.fields:
            if _from_env(settings, field.name):
                source, value = "env", getattr(settings, field.name)
            elif values.get(field.name):
                source, value = "banco", values[field.name]
            else:
                source, value = "", ""
            hint = value if not field.secret else (f"••••{value[-4:]}" if value else "")
            fields.append(FieldStatus(field, source, hint))
        out.append(ServiceStatus(service, fields))
    return out


def load(factory, settings: Settings) -> Settings:
    """Atalho dos workers: settings efetivos abrindo uma sessão curta."""
    with factory() as session:
        return effective(session, settings)
