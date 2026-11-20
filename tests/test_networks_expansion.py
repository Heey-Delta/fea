"""Task 28: TikTok, Instagram Reels, buscador do X, várias redes por operação e métricas."""

import json

import httpx
import pytest

from core.config import Settings
from core.connectors.base import SourceError, SourceRef
from core.connectors.x import XConnector, build_query, parse
from networks import get_profile, make_adapter, profile_of_config, profiles_of_config
from networks.base import AuthError, PublishFailed, PublishRequest, RateLimited
from networks.instagram_reels.adapter import InstagramAdapter
from networks.tiktok.adapter import TikTokAdapter, caption_of, chunks_for


def mock(handler):
    return lambda: httpx.Client(transport=httpx.MockTransport(handler))


def request(tmp_path, **kw):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"\x00" * 1000)
    return PublishRequest(str(f), "Título", "Título\n\n#gatos", ["gatos"], "public", **kw)


# --- Perfis -------------------------------------------------------------------------------


def config_with(*profiles):
    return {"nodes": [{"type": "network", "config": {"profiles": list(profiles)}}]}


def test_several_networks_share_the_common_standard():
    merged = profile_of_config(config_with("youtube_shorts", "tiktok", "instagram_reels"))
    assert merged.max_duration_s == 180  # o menor (Shorts)
    assert (1080, 1920) in merged.allowed_resolutions
    assert [p.platform for p in profiles_of_config(config_with("tiktok", "instagram_reels"))] == [
        "tiktok",
        "instagram",
    ]
    # Configuração antiga (um perfil só) continua valendo.
    old = {"nodes": [{"type": "network", "config": {"profile": "tiktok"}}]}
    assert profile_of_config(old).id == "tiktok"


def test_make_adapter_per_platform():
    settings = Settings(_env_file=None)
    for platform in ("youtube", "tiktok", "instagram"):
        assert make_adapter(platform, settings).platform == platform
    with pytest.raises(ValueError):
        make_adapter("orkut", settings)
    assert get_profile("instagram_reels").platform == "instagram"


# --- TikTok -------------------------------------------------------------------------------


def tiktok_api(status="PUBLISH_COMPLETE", options=("PUBLIC_TO_EVERYONE", "SELF_ONLY"), error=""):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        path = req.url.path
        ok = {"error": {"code": error or "ok", "message": error}}
        if path == "/v2/oauth/token/":
            return httpx.Response(
                200,
                json={
                    "access_token": "at2",
                    "refresh_token": "rt2",
                    "open_id": "oid",
                    "expires_in": 86400,
                },
            )
        if error:
            return httpx.Response(429 if "rate" in error else 401, json=ok)
        if path == "/v2/post/publish/creator_info/query/":
            return httpx.Response(
                200, json={"data": {"privacy_level_options": list(options)}, **ok}
            )
        if path == "/v2/post/publish/video/init/":
            return httpx.Response(
                200,
                json={"data": {"publish_id": "p1", "upload_url": "https://up.test/u"}, **ok},
            )
        if req.url.host == "up.test":
            return httpx.Response(201)
        if path == "/v2/post/publish/status/fetch/":
            return httpx.Response(
                200,
                json={"data": {"status": status, "publicaly_available_post_id": [777]}, **ok},
            )
        if path == "/v2/user/info/":
            return httpx.Response(
                200, json={"data": {"user": {"open_id": "oid", "display_name": "Meu TikTok"}}, **ok}
            )
        if path == "/v2/video/query/":
            return httpx.Response(
                200, json={"data": {"videos": [{"id": "777", "view_count": 10}]}, **ok}
            )
        return httpx.Response(404)

    return handler, seen


CREDS = json.dumps({"access_token": "at", "refresh_token": "rt", "open_id": "oid", "expires_at": 0})


def test_tiktok_oauth_refresh_and_account():
    handler, _ = tiktok_api()
    adapter = TikTokAdapter("ck", "cs", mock(handler), now=lambda: 1000)
    assert "client_key=ck" in adapter.authorize_url("https://x/retorno", "st")
    fresh = json.loads(adapter.fresh_credentials(CREDS))  # expirado: renova
    assert fresh["refresh_token"] == "rt2" and fresh["expires_at"] == 1000 + 86400
    assert adapter.fresh_credentials(json.dumps(fresh)) == json.dumps(fresh)
    assert adapter.account_info(json.dumps(fresh)) == ("oid", "Meu TikTok")


def test_tiktok_publish_is_async_and_respects_privacy(tmp_path):
    handler, seen = tiktok_api(options=("SELF_ONLY",))
    adapter = TikTokAdapter("ck", "cs", mock(handler))
    result = adapter.publish(CREDS, request(tmp_path))
    assert (result.external_id, result.status) == ("p1", "processing")
    init = next(r for r in seen if r.url.path.endswith("/video/init/"))
    body = json.loads(init.content)
    assert body["post_info"]["privacy_level"] == "SELF_ONLY"  # app sem auditoria
    assert (
        body["post_info"]["title"].startswith("Título") and "#gatos" in body["post_info"]["title"]
    )
    upload = next(r for r in seen if r.url.host == "up.test")
    assert upload.headers["Content-Range"] == "bytes 0-999/1000"
    done = adapter.status(CREDS, "p1")
    assert done.external_id == "777" and done.url.endswith("/video/777")
    assert adapter.metrics(CREDS, ["777"]) == {
        "777": {"views": 10, "likes": 0, "comments": 0, "shares": 0}
    }


def test_tiktok_status_and_errors(tmp_path):
    assert (
        TikTokAdapter("ck", "cs", mock(tiktok_api("PROCESSING_UPLOAD")[0])).status(CREDS, "p")
        is None
    )
    with pytest.raises(PublishFailed):
        TikTokAdapter("ck", "cs", mock(tiktok_api("FAILED")[0])).status(CREDS, "p")
    with pytest.raises(RateLimited):
        TikTokAdapter("ck", "cs", mock(tiktok_api(error="rate_limit_exceeded")[0])).publish(
            CREDS, request(tmp_path)
        )
    with pytest.raises(AuthError):
        TikTokAdapter("ck", "cs", mock(tiktok_api(error="access_token_invalid")[0])).publish(
            CREDS, request(tmp_path)
        )


def test_tiktok_chunks_and_caption():
    assert chunks_for(1000) == (1000, 1)
    size = 100 * 1024 * 1024
    chunk, total = chunks_for(size)
    assert chunk * total <= size < chunk * (total + 1)
    req = PublishRequest("f", "Olá", "Olá\n\n#a #b", [], "public")
    assert caption_of(req) == "Olá\n\n#a #b"


# --- Instagram ----------------------------------------------------------------------------


def instagram_api(container_status="FINISHED"):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        path = req.url.path
        if req.url.host == "api.instagram.com":
            return httpx.Response(200, json={"access_token": "short", "user_id": 42})
        if path == "/access_token":
            return httpx.Response(200, json={"access_token": "long", "expires_in": 5184000})
        if path == "/refresh_access_token":
            return httpx.Response(200, json={"access_token": "long2", "expires_in": 5184000})
        if path.endswith("/me"):
            return httpx.Response(200, json={"user_id": "42", "username": "meu_ig"})
        if path.endswith("/42/media"):
            return httpx.Response(200, json={"id": "c9"})
        if path.endswith("/c9"):
            return httpx.Response(200, json={"status_code": container_status})
        if path.endswith("/42/media_publish"):
            return httpx.Response(200, json={"id": "m5"})
        if path.endswith("/m5/insights"):
            return httpx.Response(
                200, json={"data": [{"name": "views", "values": [{"value": 99}]}]}
            )
        if path.endswith("/m5"):
            return httpx.Response(
                200,
                json={
                    "permalink": "https://instagram.com/reel/x",
                    "like_count": 3,
                    "comments_count": 1,
                },
            )
        return httpx.Response(404)

    return handler, seen


def test_instagram_oauth_and_refresh():
    handler, _ = instagram_api()
    adapter = InstagramAdapter("aid", "sec", mock(handler), now=lambda: 0)
    assert "instagram_business_content_publish" in adapter.authorize_url("https://x/r", "s")
    creds = adapter.exchange_code("code", "https://x/r")
    data = json.loads(creds)
    assert (data["access_token"], data["user_id"]) == ("long", "42")
    assert adapter.account_info(creds) == ("42", "meu_ig")
    later = InstagramAdapter("aid", "sec", mock(handler), now=lambda: 31 * 86400)
    assert json.loads(later.fresh_credentials(creds))["access_token"] == "long2"


def test_instagram_publish_needs_public_url_then_publishes(tmp_path):
    handler, seen = instagram_api()
    creds = json.dumps({"access_token": "t", "user_id": "42", "issued_at": 0, "expires_at": 9e12})
    adapter = InstagramAdapter("aid", "sec", mock(handler))
    with pytest.raises(PublishFailed, match="R2"):
        adapter.publish(creds, request(tmp_path))
    result = adapter.publish(creds, request(tmp_path, file_url="https://r2.test/v.mp4"))
    assert (result.external_id, result.status) == ("container:c9", "processing")
    media = next(r for r in seen if r.url.path.endswith("/42/media"))
    assert media.url.params["media_type"] == "REELS"
    done = adapter.status(creds, "container:c9")
    assert done.external_id == "m5" and done.url == "https://instagram.com/reel/x"
    assert adapter.metrics(creds, ["m5"]) == {"m5": {"likes": 3, "comments": 1, "views": 99}}
    pending = InstagramAdapter("aid", "sec", mock(instagram_api("IN_PROGRESS")[0]))
    assert pending.status(creds, "container:c9") is None
    with pytest.raises(PublishFailed):
        InstagramAdapter("aid", "sec", mock(instagram_api("ERROR")[0])).status(
            creds, "container:c9"
        )


# --- X ------------------------------------------------------------------------------------


X_PAYLOAD = {
    "data": [
        {
            "id": "1",
            "text": "academia supino",
            "author_id": "u1",
            "created_at": "2026-11-19T10:00:00.000Z",
            "attachments": {"media_keys": ["m1"]},
        },
        {"id": "2", "text": "sem mídia", "author_id": "u1"},
        {
            "id": "3",
            "text": "sensível",
            "possibly_sensitive": True,
            "attachments": {"media_keys": ["m1"]},
        },
        {"id": "4", "text": "foto", "author_id": "u1", "attachments": {"media_keys": ["m2"]}},
    ],
    "includes": {
        "media": [
            {
                "media_key": "m1",
                "type": "video",
                "duration_ms": 12000,
                "variants": [
                    {
                        "content_type": "video/mp4",
                        "bit_rate": 256000,
                        "url": "https://v.test/low.mp4",
                    },
                    {
                        "content_type": "video/mp4",
                        "bit_rate": 2176000,
                        "url": "https://v.test/hi.mp4",
                    },
                    {"content_type": "application/x-mpegURL", "url": "https://v.test/p.m3u8"},
                ],
            },
            {"media_key": "m2", "type": "photo", "url": "https://p.test/a.jpg"},
        ],
        "users": [{"id": "u1", "username": "criador"}],
    },
    "meta": {"next_token": "nt"},
}


def test_x_query_and_parse():
    assert build_query("@criador", ["supino", "leg day"]) == (
        'from:criador (supino OR "leg day") (has:videos OR has:images) -is:retweet'
    )
    assert build_query("#academia lang:pt", []).startswith("(#academia lang:pt)")
    with pytest.raises(SourceError):
        build_query("  ", [])
    items = parse(X_PAYLOAD)
    assert [i.external_id for i in items] == ["1", "4"]
    video = items[0]
    assert video.media_url == "https://v.test/hi.mp4" and video.duration_s == 12
    assert video.url == "https://x.com/criador/status/1" and items[1].media_type == "image"


def test_x_connector_search_and_errors(tmp_path):
    calls = []

    def handler(req):
        calls.append(req)
        if req.url.host == "v.test":
            return httpx.Response(200, content=b"video")
        return httpx.Response(200, json=X_PAYLOAD)

    settings = Settings(_env_file=None, x_bearer_token="tok")
    connector = XConnector(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    page = connector.search(SourceRef(1, "x", "@criador"), ["supino"], None)
    assert page.next_cursor == "nt" and len(page.items) == 2
    assert calls[0].headers["Authorization"] == "Bearer tok"
    assert connector.download(page.items[0], tmp_path / "a.mp4").read_bytes() == b"video"
    with pytest.raises(SourceError, match="Acessos"):
        XConnector(Settings(_env_file=None))
    denied = XConnector(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))),
    )
    with pytest.raises(SourceError, match="plano"):
        denied.fetch(SourceRef(1, "x", "@criador"), None)
