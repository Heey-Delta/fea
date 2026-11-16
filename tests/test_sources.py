"""Fontes e conectores (Task 5): Reddit simulado, upload, armazenamento e sincronização."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from core.config import Settings
from core.connectors import SourceRef, make_connector
from core.connectors.base import SourceError, request_with_retry
from core.connectors.reddit import RedditConnector, audio_candidates, parse_post, subreddit_name
from core.connectors.upload import UploadConnector, upload_prefix
from core.queue import RetryableError
from core.storage import LocalStorage

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg não instalado")
REDDIT = Settings(_env_file=None, reddit_client_id="id", reddit_client_secret="segredo")
SOURCE = SourceRef(1, "reddit", "r/GymMemes")


def video_post(post_id="abc", **overrides):
    data = {
        "id": post_id,
        "permalink": f"/r/GymMemes/comments/{post_id}/x/",
        "author": "autor",
        "created_utc": 1_790_000_000,
        "title": "Quem nunca na academia",
        "is_video": True,
        "media": {
            "reddit_video": {
                "fallback_url": f"https://v.redd.it/{post_id}/DASH_720.mp4?source=fallback",
                "duration": 12,
                "width": 720,
                "height": 1280,
                "has_audio": True,
            }
        },
    }
    data.update(overrides)
    return {"kind": "t3", "data": data}


class FakeReddit:
    """Responde como a API do Reddit e registra as chamadas."""

    def __init__(self, posts=None, listing_status=200, token_status=200, files=None):
        self.posts = posts if posts is not None else [video_post()]
        self.listing_status = listing_status
        self.token_status = token_status
        self.files = files or {}
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.url.path == "/api/v1/access_token":
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if request.url.host == "oauth.reddit.com":
            assert request.headers["authorization"] == "Bearer tok"
            if isinstance(self.listing_status, list):
                status = self.listing_status.pop(0)
            else:
                status = self.listing_status
            if status != 200:
                return httpx.Response(status)
            return httpx.Response(200, json={"data": {"children": self.posts, "after": "t3_next"}})
        content = self.files.get(str(request.url).split("?")[0])
        return httpx.Response(200, content=content) if content else httpx.Response(403)

    def connector(self) -> RedditConnector:
        client = httpx.Client(transport=httpx.MockTransport(self))
        return RedditConnector(REDDIT, client=client, sleep=lambda s: None)


# --- parsing ----------------------------------------------------------------------------


def test_subreddit_name():
    assert subreddit_name("r/GymMemes") == "GymMemes"
    assert subreddit_name("/r/GymMemes") == "GymMemes"
    assert subreddit_name("GymMemes") == "GymMemes"
    for bad in ("", "r/", "r/a b", "https://evil.com"):
        with pytest.raises(SourceError):
            subreddit_name(bad)


def test_parse_video_post():
    item = parse_post(video_post()["data"])
    assert item.external_id == "abc" and item.media_type == "video"
    assert item.url == "https://www.reddit.com/r/GymMemes/comments/abc/x/"
    assert item.duration_s == 12 and item.text == "Quem nunca na academia"
    assert item.audio_urls[0] == "https://v.redd.it/abc/DASH_AUDIO_128.mp4"


def test_parse_image_text_and_nsfw():
    image = parse_post({"id": "i1", "url": "https://i.redd.it/x.jpg", "title": "meme"})
    assert image.media_type == "image" and image.media_url == "https://i.redd.it/x.jpg"
    assert parse_post({"id": "t1", "title": "só texto", "url": "https://reddit.com/x"}) is None
    assert parse_post({**video_post()["data"], "over_18": True}) is None


def test_video_without_audio_has_no_audio_candidates():
    post = video_post()["data"]
    post["media"]["reddit_video"]["has_audio"] = False
    assert parse_post(post).audio_urls == ()


def test_audio_candidates_share_folder():
    urls = audio_candidates("https://v.redd.it/xyz/DASH_480.mp4?source=fallback")
    assert all(u.startswith("https://v.redd.it/xyz/") for u in urls)


# --- API --------------------------------------------------------------------------------


def test_fetch_lists_new_posts_with_cursor():
    fake = FakeReddit(posts=[video_post("a"), video_post("b")])
    page = fake.connector().fetch(SOURCE, "t3_prev")
    assert [i.external_id for i in page.items] == ["a", "b"]
    assert page.next_cursor == "t3_next"
    listing = fake.calls[-1]
    assert listing.url.path == "/r/GymMemes/new"
    assert listing.url.params["after"] == "t3_prev"
    assert "fea" in listing.headers["user-agent"]


def test_search_uses_tags_inside_the_community():
    fake = FakeReddit()
    fake.connector().search(SOURCE, ["academia", "memes de luta"], None)
    request = fake.calls[-1]
    assert request.url.path == "/r/GymMemes/search"
    assert request.url.params["q"] == 'academia OR "memes de luta"'
    assert request.url.params["restrict_sr"] == "1"


def test_token_is_reused():
    fake = FakeReddit()
    connector = fake.connector()
    connector.fetch(SOURCE, None)
    connector.fetch(SOURCE, None)
    assert sum(c.url.path == "/api/v1/access_token" for c in fake.calls) == 1


@pytest.mark.parametrize("status", [403, 404])
def test_private_or_missing_community_is_source_error(status):
    with pytest.raises(SourceError):
        FakeReddit(listing_status=status).connector().fetch(SOURCE, None)


def test_invalid_credentials_is_source_error():
    with pytest.raises(SourceError, match="Credencial"):
        FakeReddit(token_status=401).connector().fetch(SOURCE, None)


def test_temporary_errors_are_retried_then_succeed():
    fake = FakeReddit(listing_status=[503, 429, 200])
    assert len(fake.connector().fetch(SOURCE, None).items) == 1


def test_persistent_server_error_becomes_retryable():
    with pytest.raises(RetryableError):
        FakeReddit(listing_status=500).connector().fetch(SOURCE, None)


def test_retry_waits_longer_each_time():
    waits = []
    with pytest.raises(RetryableError):
        request_with_retry(lambda: httpx.Response(502), sleep=waits.append, base_delay=1)
    assert waits == [1, 2]


def test_missing_credentials():
    with pytest.raises(SourceError, match="REDDIT_CLIENT_ID"):
        RedditConnector(Settings(_env_file=None))


# --- download ---------------------------------------------------------------------------


def make_media(tmp_path: Path) -> tuple[bytes, bytes]:
    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.mp4"
    common = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run(
        [
            *common,
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x568:rate=30:duration=2",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            str(video),
        ],
        check=True,
    )
    subprocess.run(
        [*common, "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", str(audio)],
        check=True,
    )
    return video.read_bytes(), audio.read_bytes()


def streams(path: Path) -> list[str]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(s["codec_type"] for s in json.loads(out.stdout)["streams"])


@needs_ffmpeg
def test_download_merges_video_and_audio(tmp_path):
    video, audio = make_media(tmp_path)
    fake = FakeReddit(
        files={
            "https://v.redd.it/abc/DASH_720.mp4": video,
            "https://v.redd.it/abc/DASH_audio.mp4": audio,  # 3º candidato: testa a busca
        }
    )
    item = parse_post(video_post()["data"])
    out = fake.connector().download(item, tmp_path / "out" / "original.mp4")
    assert streams(out) == ["audio", "video"]


@needs_ffmpeg
def test_download_without_audio_keeps_video(tmp_path):
    video, _ = make_media(tmp_path)
    fake = FakeReddit(files={"https://v.redd.it/abc/DASH_720.mp4": video})
    out = fake.connector().download(parse_post(video_post()["data"]), tmp_path / "o.mp4")
    assert streams(out) == ["video"]


def test_download_missing_video_is_permanent(tmp_path):
    from core.queue import PermanentError

    with pytest.raises(PermanentError):
        FakeReddit().connector().download(parse_post(video_post()["data"]), tmp_path / "o.mp4")


# --- upload e armazenamento -------------------------------------------------------------


def test_local_storage_stays_inside_its_folder(tmp_path):
    storage = LocalStorage(tmp_path / "st")
    root = (tmp_path / "st").resolve()
    for key in ("../fora.txt", "a/../../fora.txt", "/etc/passwd"):
        assert root in storage._path(key).parents  # ".." e "/" são descartados
    with pytest.raises(ValueError):
        storage._path("../..")
    src = tmp_path / "f.txt"
    src.write_text("x")
    storage.put_file("a/b/f.txt", src)
    assert storage.exists("a/b/f.txt") and storage.list("a/") == ["a/b/f.txt"]
    storage.delete("a/b/f.txt")
    assert not storage.exists("a/b/f.txt")


def test_upload_connector_lists_new_media(tmp_path):
    storage = LocalStorage(tmp_path)
    prefix = upload_prefix(7, 3)
    for name in ("b_meme-legal.mp4", "a.png", "notas.txt"):
        f = tmp_path / "in" / name
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(b"x")
        storage.put_file(prefix + name, f)
    connector = UploadConnector(storage, 7)
    page = connector.fetch(SourceRef(3, "upload", ""), None)
    assert [(i.media_type, i.text) for i in page.items] == [
        ("image", "a"),
        ("video", "b meme legal"),
    ]
    assert connector.fetch(SourceRef(3, "upload", ""), prefix + "b_meme-legal.mp4").items == []
    assert connector.supports_search is False
    out = connector.download(page.items[0], tmp_path / "dl" / "a.png")
    assert out.read_bytes() == b"x"


def test_make_connector_unknown_type(tmp_path):
    with pytest.raises(SourceError):
        make_connector("orkut", REDDIT, LocalStorage(tmp_path), 1)


# --- sincronização com o canvas e tela --------------------------------------------------

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL não definida")


@pytest.fixture
def session():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from core.db import sqlalchemy_url

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url(DATABASE_URL))
    command.upgrade(cfg, "head")
    engine = create_engine(sqlalchemy_url(DATABASE_URL))
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE operations, events RESTART IDENTITY CASCADE"))
    with Session(engine) as s:
        yield s
    engine.dispose()


def flow_with_sources(*sources):
    from core import operations as ops

    config = ops.default_config()
    for node_id, cfg in sources:
        config["nodes"].append({"id": node_id, "type": "source", "config": cfg})
        config["edges"].append({"from": node_id, "to": "pesca"})
    return config


@needs_db
def test_canvas_sources_become_rows(session):
    from core import operations as ops
    from core.sources import list_sources

    op = ops.create_operation(
        session,
        "A",
        flow_with_sources(
            ("f1", {"type": "reddit", "reference": "r/GymMemes", "permission_note": "ok"}),
            ("f2", {"type": "upload", "reference": "Meus vídeos"}),
        ),
    )
    rows = list_sources(session, op.id)
    assert [(s.node_id, s.type, s.reference, s.permission_note) for s in rows] == [
        ("f1", "reddit", "r/GymMemes", "ok"),
        ("f2", "upload", "Meus vídeos", None),
    ]


@needs_db
def test_removed_block_pauses_source_and_comes_back(session):
    from core import operations as ops
    from core.sources import list_sources

    reddit = ("f1", {"type": "reddit", "reference": "r/GymMemes"})
    op = ops.create_operation(session, "A", flow_with_sources(reddit))
    ops.save_config(session, op, flow_with_sources())
    assert [s.status for s in list_sources(session, op.id)] == ["paused"]
    ops.save_config(session, op, flow_with_sources(reddit))
    assert [s.status for s in list_sources(session, op.id)] == ["ok"]


@needs_db
def test_changing_community_resets_cursor(session):
    from core import operations as ops
    from core.sources import list_sources

    op = ops.create_operation(
        session, "A", flow_with_sources(("f1", {"type": "reddit", "reference": "r/a1"}))
    )
    source = list_sources(session, op.id)[0]
    source.cursor = {"after": "t3_x"}
    session.flush()
    ops.save_config(session, op, flow_with_sources(("f1", {"type": "reddit", "reference": "r/b2"})))
    assert list_sources(session, op.id)[0].cursor is None


def test_reddit_source_needs_community():
    from core import operations as ops

    issues = ops.validate_graph(flow_with_sources(("f1", {"type": "reddit"})))
    assert any(i.message.startswith("Fonte do Reddit sem comunidade") for i in issues)


@needs_db
def test_connection_test_from_sources_tab(settings, session):
    from fastapi.testclient import TestClient

    from core import operations as ops
    from tests.conftest import fake_github, github_login
    from web.main import create_app

    op = ops.create_operation(
        session,
        "A",
        flow_with_sources(("f1", {"type": "reddit", "reference": "r/GymMemes"})),
    )
    session.commit()
    app = create_app(
        settings.model_copy(update={"reddit_client_id": "id", "reddit_client_secret": "s"})
    )
    app.state.http_client_factory = fake_github()
    fake = FakeReddit(posts=[video_post("a"), video_post("b")])
    app.state.connector_kwargs = {
        "client": httpx.Client(transport=httpx.MockTransport(fake)),
        "sleep": lambda s: None,
    }
    client = TestClient(app)
    github_login(client)
    tab = client.get(f"/operacoes/{op.id}?aba=fontes")
    assert "r/GymMemes" in tab.text and "itens ficam pendentes" in tab.text
    from core.sources import list_sources

    source_id = list_sources(session, op.id)[0].id
    result = client.post(f"/operacoes/{op.id}/fontes/{source_id}/testar")
    assert "Conexão ok: 2 itens" in result.text

    fake.listing_status = 404
    result = client.post(f"/operacoes/{op.id}/fontes/{source_id}/testar")
    assert "Comunidade privada" in result.text
    session.expire_all()
    assert (
        __import__("core.sources", fromlist=["x"]).list_sources(session, op.id)[0].status == "error"
    )
