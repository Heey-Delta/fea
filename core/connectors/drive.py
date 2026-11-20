"""Conector do Google Drive: uma pasta do Drive como fonte da Busca.

Vídeos (e imagens) que caírem na pasta entram na operação como itens, passam pelo Motor
Editor e seguem para o Publicador, igual às outras fontes.

Acesso por **conta de serviço** do Google Cloud, não pelo login OAuth:
- o escopo de leitura do Drive (`drive.readonly`) é *restrito* no OAuth e exigiria verificação
  do app; a conta de serviço lê só o que foi compartilhado com ela, sem tela de consentimento;
- você compartilha a pasta com o e-mail da conta de serviço (como "Leitor") e cola a chave
  JSON dela na tela Acessos.

Referência da fonte: o link da pasta (`https://drive.google.com/drive/folders/<id>`) ou o id.
"""

import base64
import json
import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx

from core.config import Settings
from core.connectors.base import Page, RawItem, SourceError, SourceRef, request_with_retry
from core.queue import PermanentError

API = "https://www.googleapis.com/drive/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive.readonly"
PAGE_SIZE = 100
FOLDER_URL = re.compile(r"/folders/([A-Za-z0-9_-]{10,})")
FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")
FIELDS = (
    "nextPageToken,files(id,name,mimeType,size,createdTime,webViewLink,"
    "videoMediaMetadata(durationMillis,width,height))"
)


def folder_id(reference: str) -> str:
    reference = (reference or "").strip()
    match = FOLDER_URL.search(reference)
    if match:
        return match.group(1)
    if "id=" in reference:
        value = reference.split("id=", 1)[1].split("&", 1)[0]
        if FOLDER_ID.match(value):
            return value
    if FOLDER_ID.match(reference):
        return reference
    raise SourceError("Fonte do Drive sem pasta válida: cole o link da pasta do Google Drive.")


def load_key(raw: str) -> dict:
    """A chave JSON da conta de serviço, como baixada do Google Cloud."""
    try:
        key = json.loads(raw)
    except (TypeError, ValueError):
        raise SourceError(
            "Chave do Google Drive inválida: cole o JSON inteiro da conta de serviço."
        ) from None
    if key.get("type") != "service_account" or not key.get("private_key"):
        raise SourceError("A chave colada não é de uma conta de serviço do Google Cloud.")
    if not key.get("client_email"):
        raise SourceError("A chave da conta de serviço não tem client_email.")
    return key


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def signed_assertion(key: dict, now: float | None = None) -> str:
    """JWT RS256 do fluxo de conta de serviço (RFC 7523), assinado com a chave privada."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    now = int(now if now is not None else time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    if key.get("private_key_id"):
        header["kid"] = key["private_key_id"]
    claims = {
        "iss": key["client_email"],
        "scope": SCOPE,
        "aud": key.get("token_uri") or TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    try:
        private = serialization.load_pem_private_key(key["private_key"].encode(), password=None)
    except (ValueError, TypeError) as exc:
        raise SourceError("Chave privada da conta de serviço ilegível.") from exc
    signature = private.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64(signature)}"


def parse(files: list[dict]) -> list[RawItem]:
    items = []
    for f in files:
        mime = f.get("mimeType") or ""
        if mime.startswith("video/"):
            kind = "video"
        elif mime.startswith("image/"):
            kind = "image"
        else:
            continue
        meta = f.get("videoMediaMetadata") or {}
        duration = meta.get("durationMillis")
        created = f.get("createdTime")
        name = f.get("name") or f["id"]
        items.append(
            RawItem(
                external_id=f["id"],
                url=f.get("webViewLink") or f"https://drive.google.com/file/d/{f['id']}/view",
                author=None,
                published_at=datetime.fromisoformat(created.replace("Z", "+00:00"))
                if created
                else None,
                media_type=kind,
                text=Path(name).stem.replace("_", " ").replace("-", " "),
                media_url=f["id"],
                duration_s=int(duration) / 1000 if duration else None,
                extra={"width": meta.get("width"), "height": meta.get("height"), "name": name},
            )
        )
    return items


class DriveConnector:
    # A pasta não tem busca por texto útil: as tags valem só como filtro do texto (nome).
    supports_search = False

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ):
        # Dois modos. Conta de serviço (pasta privada, compartilhada com o e-mail dela) quando há
        # a chave JSON. Senão, chave de API (pasta compartilhada como "qualquer pessoa com o
        # link"), que não depende de chave de conta de serviço (muitas contas a bloqueiam por
        # política da organização).
        self.api_key = (settings.google_drive_api_key or "").strip()
        if settings.google_drive_service_account:
            self.key = load_key(settings.google_drive_service_account)
        elif self.api_key:
            self.key = None
        else:
            raise SourceError(
                "Google Drive não configurado: em Acessos, cole a chave JSON da conta de serviço "
                "ou uma chave de API."
            )
        self.client = client or httpx.Client(timeout=60, follow_redirects=True)
        self.sleep = sleep
        self.clock = clock
        self._token: str | None = None
        self._expires = 0.0

    @property
    def email(self) -> str:
        return self.key["client_email"] if self.key else ""

    @property
    def share_hint(self) -> str:
        if self.key:
            return f"Compartilhe a pasta com {self.email} (Leitor)."
        return 'Compartilhe a pasta como "Qualquer pessoa com o link" (Leitor).'

    def _auth(self, params: dict | None = None) -> tuple[dict, dict]:
        """(parâmetros, cabeçalhos) de autenticação do modo em uso."""
        params = dict(params or {})
        if self.key:
            return params, {"Authorization": f"Bearer {self.token()}"}
        params["key"] = self.api_key
        return params, {}

    def token(self) -> str:
        if self._token and self.clock() < self._expires - 60:
            return self._token
        response = request_with_retry(
            lambda: self.client.post(
                self.key.get("token_uri") or TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": signed_assertion(self.key, self.clock()),
                },
            ),
            sleep=self.sleep,
        )
        if response.status_code != 200 or "access_token" not in response.json():
            raise SourceError(
                f"O Google recusou a conta de serviço (HTTP {response.status_code}). "
                "Confira a chave e se a API do Google Drive está ativada no projeto."
            )
        body = response.json()
        self._token = body["access_token"]
        self._expires = self.clock() + float(body.get("expires_in", 3600))
        return self._token

    def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        def send():
            query, headers = self._auth(params)
            return self.client.get(url, params=query, headers=headers)

        return request_with_retry(send, sleep=self.sleep)

    def check_key(self) -> None:
        """Modo chave de API: uma listagem vazia basta para saber se o Google aceitou a chave."""
        if self.key:
            self.token()
            return
        response = self._get(f"{API}/files", params={"pageSize": 1})
        if response.status_code == 200:
            return
        if response.status_code == 400:
            raise SourceError(
                "O Google recusou a chave de API: confira se ela foi copiada inteira."
            )
        raise SourceError(
            f"A chave de API não tem acesso (HTTP {response.status_code}). Ative a Google Drive "
            "API no projeto e, se restringiu a chave, permita a Google Drive API nela."
        )

    def fetch(self, source: SourceRef, cursor: str | None) -> Page:
        fid = folder_id(source.reference)
        params = {
            "q": f"'{fid}' in parents and trashed = false and "
            "(mimeType contains 'video/' or mimeType contains 'image/')",
            "fields": FIELDS,
            "orderBy": "createdTime desc",
            "pageSize": PAGE_SIZE,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if cursor:
            params["pageToken"] = cursor
        response = self._get(f"{API}/files", params=params)
        if response.status_code == 404:
            raise SourceError(f"Pasta do Drive não encontrada. {self.share_hint}")
        if response.status_code in (401, 403):
            raise SourceError(
                f"Sem acesso ao Drive: ative a Google Drive API no projeto. {self.share_hint}"
            )
        if response.status_code != 200:
            raise SourceError(f"Google Drive respondeu {response.status_code}.")
        payload = response.json()
        items = parse(payload.get("files") or [])
        if not items and not cursor and not self._folder_visible(fid):
            raise SourceError(f"O Google não enxerga a pasta. {self.share_hint}")
        return Page(items=items, next_cursor=payload.get("nextPageToken"))

    def _folder_visible(self, fid: str) -> bool:
        response = self._get(
            f"{API}/files/{fid}", params={"fields": "id", "supportsAllDrives": "true"}
        )
        return response.status_code == 200

    def search(self, source: SourceRef, tags: list[str], cursor: str | None) -> Page:
        return self.fetch(source, cursor)

    def download(self, item: RawItem, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"{API}/files/{item.media_url}"
        for attempt in range(3):
            try:
                params, headers = self._auth({"alt": "media", "supportsAllDrives": "true"})
                with self.client.stream("GET", url, params=params, headers=headers) as response:
                    if response.status_code == 200:
                        with open(dest, "wb") as out:
                            for chunk in response.iter_bytes(1024 * 1024):
                                out.write(chunk)
                        return dest
                    if response.status_code in (429,) or response.status_code >= 500:
                        raise httpx.TransportError(f"HTTP {response.status_code}")
                    raise PermanentError(
                        f"Arquivo indisponível no Drive (HTTP {response.status_code})."
                    )
            except httpx.TransportError:
                if attempt == 2:
                    raise
                self.sleep(2**attempt)
        return dest
