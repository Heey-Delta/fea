"""Adaptador YouTube (Task 20) contra respostas simuladas da API do Google."""

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from networks.base import AuthError, PublishRequest, RateLimited, Uncertain
from networks.youtube_shorts.adapter import YouTubeAdapter, authorize_url

CREDS = json.dumps({"refresh_token": "r1"})


def adapter(handler):
    return YouTubeAdapter(
        "cid", "secret", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )


def google(upload_status=200, upload_exc=None, token_status=200, start_status=200, start_body=None):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth2.googleapis.com":
            if token_status != 200:
                return httpx.Response(token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "at", "refresh_token": "r-new"})
        if request.url.path == "/upload/youtube/v3/videos":
            if start_status != 200:
                return httpx.Response(start_status, json=start_body or {})
            return httpx.Response(200, headers={"Location": "https://upload.test/session/1"})
        if request.url.host == "upload.test":
            if upload_exc:
                raise upload_exc
            return httpx.Response(upload_status, json={"id": "vid9", "status": {}})
        if request.url.path.endswith("/channels"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UC1",
                            "snippet": {"title": "Meu canal"},
                            "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}},
                        }
                    ]
                },
            )
        if request.url.path.endswith("/playlistItems"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "snippet": {
                                "title": "Gato pulando!",
                                "publishedAt": "2026-11-16T13:05:00Z",
                                "resourceId": {"videoId": "vidX"},
                            }
                        }
                    ]
                },
            )
        return httpx.Response(404)

    return handler, seen


def req(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"\x00" * 10)
    return PublishRequest(str(f), "Título", "Desc", ["shorts"], "public")


def test_authorize_url_asks_offline_upload_scope():
    q = parse_qs(urlparse(authorize_url("cid", "https://x/retorno", "st")).query)
    assert q["access_type"] == ["offline"] and "youtube.upload" in q["scope"][0]
    assert q["state"] == ["st"]


def test_exchange_code_and_account_info():
    handler, _ = google()
    a = adapter(handler)
    creds = a.exchange_code("code", "https://x/retorno")
    assert json.loads(creds) == {"refresh_token": "r-new"}
    assert a.account_info(creds) == ("UC1", "Meu canal")


def test_publish_resumable(tmp_path):
    handler, seen = google()
    result = adapter(handler).publish(CREDS, req(tmp_path))
    assert result.external_id == "vid9" and result.url.endswith("/vid9")
    start = next(r for r in seen if r.url.path == "/upload/youtube/v3/videos")
    body = json.loads(start.content)
    assert body["snippet"]["title"] == "Título" and body["status"]["privacyStatus"] == "public"


def test_errors_are_classified(tmp_path):
    with pytest.raises(AuthError):
        adapter(google(token_status=400)[0]).publish(CREDS, req(tmp_path))
    quota = {"error": {"errors": [{"reason": "quotaExceeded"}]}}
    with pytest.raises(RateLimited):
        adapter(google(start_status=403, start_body=quota)[0]).publish(CREDS, req(tmp_path))
    with pytest.raises(Uncertain):
        adapter(google(upload_exc=httpx.ReadTimeout("t"))[0]).publish(CREDS, req(tmp_path))
    with pytest.raises(Uncertain):
        adapter(google(upload_status=503)[0]).publish(CREDS, req(tmp_path))


def test_check_finds_by_title():
    a = adapter(google()[0])
    assert a.check(CREDS, "gato pulando", "2026-11-16T13:00:00+00:00").external_id == "vidX"
    assert a.check(CREDS, "outro", "2026-11-16T13:00:00+00:00") is None
    assert a.check(CREDS, "gato pulando", "2026-11-16T14:00:00+00:00") is None
