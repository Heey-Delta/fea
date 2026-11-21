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


def fake_google_public(files, seen=None, folder_public=True, key_ok=True):
    """Drive aberto a quem tem o link: só chave de API, sem cabeçalho de login."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        assert "authorization" not in request.headers
        if request.url.params.get("key") != "AIzaChaveDeTeste":
            return httpx.Response(400, json={"error": {"message": "API key not valid"}})
        if not key_ok:
            return httpx.Response(403, json={"error": {"message": "API disabled"}})
        if request.url.path == "/drive/v3/files":
            if "q" not in request.url.params:  # teste da chave
                return httpx.Response(200, json={"files": []})
            return httpx.Response(200, json={"files": files if folder_public else []})
        if request.url.path == f"/drive/v3/files/{FOLDER}":
            return httpx.Response(200 if folder_public else 404, json={"id": FOLDER})
        if request.url.path == "/drive/v3/files/vid1" and request.url.params.get("alt"):
            return httpx.Response(200, content=b"conteudo-publico")
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def key_settings(key="AIzaChaveDeTeste") -> Settings:
    return Settings(_env_file=None, google_drive_api_key=key)


def test_modo_chave_de_api_lista_e_baixa_sem_login(tmp_path):
    seen = []
    conn = DriveConnector(key_settings(), client=fake_google_public(FILES, seen))
    conn.check_key()
    page = conn.fetch(SourceRef(1, "drive", FOLDER), None)
    assert [i.external_id for i in page.items] == ["vid1", "img1"]
    dest = conn.download(page.items[0], tmp_path / "v.mp4")
    assert Path(dest).read_bytes() == b"conteudo-publico"
    assert all(r.url.params["key"] == "AIzaChaveDeTeste" for r in seen)
    assert not any(r.url.path == "/token" for r in seen)  # sem conta de serviço


def test_modo_chave_de_api_explica_o_que_fazer():
    with pytest.raises(SourceError, match="não foi copiada|recusou a chave"):
        DriveConnector(key_settings("errada"), client=fake_google_public(FILES)).check_key()
    with pytest.raises(SourceError, match="não tem acesso"):
        DriveConnector(key_settings(), client=fake_google_public(FILES, key_ok=False)).check_key()
    conn = DriveConnector(key_settings(), client=fake_google_public(FILES, folder_public=False))
    with pytest.raises(SourceError, match="Qualquer pessoa com o link"):
        conn.fetch(SourceRef(1, "drive", FOLDER), None)


def test_conta_de_servico_tem_prioridade_e_sem_nada_falha():
    both = Settings(
        _env_file=None,
        google_drive_service_account=json.dumps(KEY),
        google_drive_api_key="AIzaChaveDeTeste",
    )
    assert DriveConnector(both, client=fake_google()).key is not None
    with pytest.raises(SourceError, match="não configurado"):
        DriveConnector(Settings(_env_file=None))


def test_acessos_considera_pronto_com_uma_das_duas_opcoes():
    from core import credentials as creds
    from core.credentials import FieldStatus, ServiceStatus

    svc = creds.SERVICE_BY_ID["drive"]
    first, second = svc.fields
    none = ServiceStatus(svc, [FieldStatus(first, "", ""), FieldStatus(second, "", "")])
    one = ServiceStatus(svc, [FieldStatus(first, "", ""), FieldStatus(second, "banco", "••••1")])
    assert not none.ready and one.ready


# --- busca de ponta a ponta: pasta do Drive → item elegível → tarefa de edição ---------

from tests.test_render_job import factory  # noqa: E402,F401
from tests.test_render_job import pytestmark as _db_marks  # noqa: E402


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="FFmpeg não instalado")
@_db_marks[0]
def test_busca_no_drive_de_ponta_a_ponta(factory, tmp_path):  # noqa: F811
    from sqlalchemy import select

    import core.models as m
    from core import executions
    from core import operations as ops
    from core.storage import LocalStorage
    from tests.test_fishing import make_video
    from worker.collect import run_collect

    video = make_video(tmp_path / "meu_video.mp4", "testsrc")
    files = [
        {
            "id": "vid1",
            "name": "meu_video.mp4",
            "mimeType": "video/mp4",
            "createdTime": "2026-11-21T00:00:00.000Z",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("key") == "AIzaChaveDeTeste"
        if request.url.path == "/drive/v3/files":
            return httpx.Response(200, json={"files": files})
        if request.url.path == "/drive/v3/files/vid1":
            return httpx.Response(200, content=video.read_bytes())
        return httpx.Response(404)

    config = ops.default_config()
    config["nodes"] += [
        {
            "id": "f1",
            "type": "source",
            "config": {
                "type": "drive",
                "reference": f"https://drive.google.com/drive/folders/{FOLDER}",
                "permission_note": "vídeos próprios",
            },
        },
        {"id": "c1", "type": "account", "config": {}},
    ]
    config["edges"] += [{"from": "f1", "to": "pesca"}, {"from": "c1", "to": "postagem"}]
    with factory() as s:
        op = ops.create_operation(s, "Drive", config)
        ops.change_status(s, op, "active")
        s.commit()
        ex = executions.start_execution(s, op, target_x=1)
        s.commit()
        ex_id = ex.id
    kwargs = {
        "client": httpx.Client(transport=httpx.MockTransport(handler)),
        "sleep": lambda _s: None,
    }
    progress = run_collect(
        factory, ex_id, key_settings(), LocalStorage(tmp_path / "storage"), kwargs
    )
    assert progress.examined == 1 and len(progress.eligible) == 1
    with factory() as s:
        item = s.scalars(select(m.Item).where(m.Item.execution_id == ex_id)).one()
        assert item.status == "eligible" and item.external_id == "vid1" and item.phash
        assert s.scalars(select(m.Job).where(m.Job.type == "render")).all()
        assert s.get(m.Execution, ex_id).status == "completed"


@_db_marks[0]
def test_pasta_vazia_explica_o_motivo_na_execucao(factory, tmp_path):  # noqa: F811
    import core.models as m
    from core import executions
    from core import operations as ops
    from core.storage import LocalStorage
    from worker.collect import run_collect

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/drive/v3/files":
            return httpx.Response(200, json={"files": []})
        return httpx.Response(200, json={"id": FOLDER})  # a pasta existe e está visível

    config = ops.default_config()
    config["nodes"] += [
        {
            "id": "f1",
            "type": "source",
            "config": {"type": "drive", "reference": FOLDER, "permission_note": "próprios"},
        },
        {"id": "c1", "type": "account", "config": {}},
    ]
    config["edges"] += [{"from": "f1", "to": "pesca"}, {"from": "c1", "to": "postagem"}]
    with factory() as s:
        op = ops.create_operation(s, "Vazia", config)
        ops.change_status(s, op, "active")
        s.commit()
        ex = executions.start_execution(s, op, target_x=1)
        s.commit()
        ex_id = ex.id
    kwargs = {
        "client": httpx.Client(transport=httpx.MockTransport(handler)),
        "sleep": lambda _s: None,
    }
    run_collect(factory, ex_id, key_settings(), LocalStorage(tmp_path / "st"), kwargs)
    with factory() as s:
        ex = s.get(m.Execution, ex_id)
        assert ex.status == "partial" and "pasta vazia" in ex.shortfall_reason
