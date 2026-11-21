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
FOLDER_MIME = "application/vnd.google-apps.folder"
MAX_FOLDERS = 200  # subpastas percorridas por busca (proteção contra árvores enormes)
FOLDER_URL = re.compile(r"/folders/([A-Za-z0-9_-]{10,})")
FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")
FIELDS = (
    "nextPageToken,files(id,name,mimeType,size,createdTime,webViewLink,"
    "videoMediaMetadata(durationMillis,width,height),shortcutDetails(targetId,targetMimeType))"
)
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
# Uploads pelo celular às vezes chegam com tipo genérico: a extensão decide.
EXT_KIND = {
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image", ".gif": "image",
    ".heic": "image", ".heif": "image", ".bmp": "image",
    ".mp4": "video", ".mov": "video", ".m4v": "video", ".webm": "video", ".3gp": "video",
    ".mkv": "video",
}  # fmt: skip


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


class FolderPage:
    def __init__(self, items: list[RawItem], next_cursor: str | None, subfolders: list[str]):
        self.items, self.next_cursor, self.subfolders = items, next_cursor, subfolders


# Tipos que podem esconder uma imagem ou vídeo salvo com o nome errado (ex.: "meme.txt").
SNIFFABLE = ("text/plain", "application/octet-stream", "binary/octet-stream", "")
MAX_SNIFF = 300  # arquivos inspecionados por página (proteção contra pastas enormes)


def sniff(head: bytes) -> str | None:
    """ "image", "video" ou None pela assinatura dos primeiros bytes (não pelo nome)."""
    if head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if head.startswith((b"GIF87a", b"GIF89a", b"BM")):
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1", b"avif"):
            return "image"
        return "video"  # isom, mp42, qt, 3gp…
    if head.startswith(b"\x1a\x45\xdf\xa3"):  # Matroska/WebM
        return "video"
    return None


def skipped_summary(connector) -> str:
    """ "3 × application/pdf, 1 × …": o que a fonte tinha e não é imagem nem vídeo."""
    skipped = getattr(connector, "skipped", None) or {}
    top = sorted(skipped.items(), key=lambda kv: -kv[1])[:5]
    return ", ".join(f"{n} × {mime}" for mime, n in top)


def kind_of(mime: str, name: str) -> str | None:
    """ "image", "video" ou None. Pelo tipo do Drive; se genérico, pela extensão do nome."""
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("application/vnd.google-apps"):
        return None  # Docs, Planilhas etc.
    return EXT_KIND.get(Path(name).suffix.lower())


def parse(
    files: list[dict],
    skipped: dict | None = None,
    sniffer: Callable[[str], str | None] | None = None,
) -> list[RawItem]:
    """Itens de mídia. Atalhos para imagem/vídeo viram o arquivo de destino.

    `skipped` (opcional) conta o que ficou de fora, por tipo, para o diagnóstico.
    """
    items = []
    for f in files:
        mime = f.get("mimeType") or ""
        name = f.get("name") or f["id"]
        media_id = f["id"]
        if mime == FOLDER_MIME:
            continue
        if mime == SHORTCUT_MIME:
            target = f.get("shortcutDetails") or {}
            mime, media_id = target.get("targetMimeType") or "", target.get("targetId") or ""
            if mime == FOLDER_MIME or not media_id:
                continue
        kind = kind_of(mime, name)
        if kind is None and sniffer is not None and mime in SNIFFABLE:
            kind = sniffer(media_id)  # ex.: imagem salva como .txt
        if kind is None:
            if skipped is not None:
                skipped[mime or "sem tipo"] = skipped.get(mime or "sem tipo", 0) + 1
            continue
        meta = f.get("videoMediaMetadata") or {}
        duration = meta.get("durationMillis")
        created = f.get("createdTime")
        items.append(
            RawItem(
                external_id=media_id,
                url=f.get("webViewLink") or f"https://drive.google.com/file/d/{media_id}/view",
                author=None,
                published_at=datetime.fromisoformat(created.replace("Z", "+00:00"))
                if created
                else None,
                media_type=kind,
                text=Path(name).stem.replace("_", " ").replace("-", " "),
                media_url=media_id,
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
        self.skipped: dict[str, int] = {}  # arquivos da pasta que não são imagem/vídeo, por tipo

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
        """Uma página da pasta e das subpastas (largura primeiro).

        O cursor guarda a fila de pastas a visitar, quantas já entraram na fila e o
        `pageToken` da pasta atual. Cursor antigo (só o pageToken) continua valendo.
        """
        root = folder_id(source.reference)
        state = {"queue": [root], "seen": 1, "token": None}
        if cursor:
            try:
                parsed = json.loads(cursor)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict) and parsed.get("queue"):
                state = parsed
            else:  # cursor de versão antiga: só o pageToken da pasta principal
                state["token"] = cursor
        fid = state["queue"][0]
        page = self._fetch_folder(fid, state["token"], is_root=fid == root and not cursor)
        for sub in page.subfolders:
            if state["seen"] < MAX_FOLDERS:
                state["queue"].append(sub)
                state["seen"] += 1
        if page.next_cursor:
            state["token"] = page.next_cursor
        else:
            state["queue"], state["token"] = state["queue"][1:], None
        nxt = json.dumps(state) if state["queue"] else None
        return Page(items=page.items, next_cursor=nxt)

    def _fetch_folder(self, fid: str, token: str | None, is_root: bool):
        # Lista tudo (sem filtro de tipo no Google): atalhos e arquivos de tipo genérico
        # também entram, e o que sobrar aparece contado no diagnóstico.
        params = {
            "q": f"'{fid}' in parents and trashed = false",
            "fields": FIELDS,
            "orderBy": "createdTime desc",
            "pageSize": PAGE_SIZE,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if token:
            params["pageToken"] = token
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
        files = payload.get("files") or []
        budget = {"left": MAX_SNIFF}

        def sniffer(file_id: str) -> str | None:
            if budget["left"] <= 0:
                return None
            budget["left"] -= 1
            return self._sniff(file_id)

        items = parse(files, self.skipped, sniffer)
        subfolders = [f["id"] for f in files if f.get("mimeType") == FOLDER_MIME]
        subfolders += [
            (f.get("shortcutDetails") or {}).get("targetId")
            for f in files
            if f.get("mimeType") == SHORTCUT_MIME
            and (f.get("shortcutDetails") or {}).get("targetMimeType") == FOLDER_MIME
        ]
        if not files and is_root and not token and not self._folder_visible(fid):
            raise SourceError(f"O Google não enxerga a pasta. {self.share_hint}")
        return FolderPage(items, payload.get("nextPageToken"), subfolders)

    def _sniff(self, file_id: str) -> str | None:
        """Lê só os primeiros 32 bytes do arquivo para saber se é imagem/vídeo de verdade."""
        params, headers = self._auth({"alt": "media", "supportsAllDrives": "true"})
        try:
            response = self.client.get(
                f"{API}/files/{file_id}",
                params=params,
                headers={**headers, "Range": "bytes=0-31"},
            )
        except httpx.HTTPError:
            return None
        if response.status_code not in (200, 206):
            return None
        return sniff(response.content[:32])

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
