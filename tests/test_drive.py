"""Fonte Google Drive: conta de serviço, listagem da pasta e download."""

import base64
import json
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from core.config import Settings
from core.connectors import SOURCE_TYPES, make_connector
from core.connectors.base import SourceError, SourceRef
from core.connectors.drive import DriveConnector, folder_id, load_key

FOLDER = "1AbCdEfGhIjKlMnOpQrStUv"
PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = PRIVATE.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
KEY = {
    "type": "service_account",
    "client_email": "fea-drive@projeto.iam.gserviceaccount.com",
    "private_key_id": "abc123",
    "private_key": PEM,
    "token_uri": "https://oauth2.googleapis.com/token",
}


def settings(key=KEY) -> Settings:
    return Settings(_env_file=None, google_drive_service_account=json.dumps(key))


def unb64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def fake_google(files=None, shared=True, seen=None):
    files = files if files is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == "/token":
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            header, claims, signature = form["assertion"].split(".")
            PRIVATE.public_key().verify(  # assinatura RS256 válida, senão levanta
                unb64(signature),
                f"{header}.{claims}".encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            body = json.loads(unb64(claims))
            assert body["iss"] == KEY["client_email"]
            assert body["scope"].endswith("/drive.readonly")
            return httpx.Response(200, json={"access_token": "ya29.t", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer ya29.t"
        if request.url.path == "/drive/v3/files":
            if not shared:
                return httpx.Response(200, json={"files": []})
            assert f"'{FOLDER}' in parents" in request.url.params["q"]
            return httpx.Response(200, json={"files": files})
        if request.url.path == f"/drive/v3/files/{FOLDER}":
            return httpx.Response(200 if shared else 404, json={"id": FOLDER})
        if request.url.path == "/drive/v3/files/vid1" and request.url.params.get("alt"):
            return httpx.Response(200, content=b"conteudo-do-video")
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


FILES = [
    {
        "id": "vid1",
        "name": "treino_de_costas.mp4",
        "mimeType": "video/mp4",
        "createdTime": "2026-11-20T10:00:00.000Z",
        "videoMediaMetadata": {"durationMillis": "15500", "width": 1080, "height": 1920},
    },
    {"id": "img1", "name": "capa.png", "mimeType": "image/png"},
    {"id": "doc1", "name": "roteiro.pdf", "mimeType": "application/pdf"},
]


def test_folder_id_aceita_link_ou_id():
    assert folder_id(f"https://drive.google.com/drive/folders/{FOLDER}?usp=sharing") == FOLDER
    assert folder_id(f"https://drive.google.com/drive/u/0/folders/{FOLDER}") == FOLDER
    assert folder_id(f"https://drive.google.com/open?id={FOLDER}") == FOLDER
    assert folder_id(FOLDER) == FOLDER
    with pytest.raises(SourceError):
        folder_id("minha pasta")


def test_chave_precisa_ser_de_conta_de_servico():
    with pytest.raises(SourceError):
        load_key("não é json")
    with pytest.raises(SourceError):
        load_key(json.dumps({"type": "authorized_user"}))
    with pytest.raises(SourceError):
        DriveConnector(Settings(_env_file=None))


def test_lista_videos_e_imagens_da_pasta_e_baixa(tmp_path):
    seen = []
    conn = make_connector("drive", settings(), None, 1, client=fake_google(FILES, seen=seen))
    page = conn.fetch(
        SourceRef(1, "drive", f"https://drive.google.com/drive/folders/{FOLDER}"), None
    )
    assert [i.external_id for i in page.items] == ["vid1", "img1"]  # o PDF fica de fora
    video = page.items[0]
    assert video.media_type == "video" and video.duration_s == 15.5
    assert video.text == "treino de costas"
    assert video.extra["height"] == 1920
    dest = conn.download(video, tmp_path / "v.mp4")
    assert Path(dest).read_bytes() == b"conteudo-do-video"
    assert sum(r.url.path == "/token" for r in seen) == 1  # token reaproveitado


def test_pasta_nao_compartilhada_explica_o_que_fazer():
    conn = DriveConnector(settings(), client=fake_google(shared=False), sleep=lambda _s: None)
    with pytest.raises(SourceError, match="fea-drive@projeto.iam.gserviceaccount.com"):
        conn.fetch(SourceRef(1, "drive", FOLDER), None)


def test_drive_aparece_como_tipo_de_fonte():
    assert SOURCE_TYPES["drive"] == "Google Drive"
