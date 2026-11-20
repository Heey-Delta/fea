import json
import logging

from core.logging import REDACTED, JsonFormatter, redact, redact_text


def format_record(msg: str, **extra) -> dict:
    record = logging.makeLogRecord({"msg": msg, "levelname": "INFO", "name": "t", **extra})
    return json.loads(JsonFormatter().format(record))


def test_bearer_token_is_redacted():
    out = redact_text("Authorization: Bearer ya29.a0AfH6SMBx-secret")
    assert "ya29" not in out and REDACTED in out


def test_database_password_is_redacted():
    out = redact_text("conectando em postgresql://fea:SenhaForte@ep-x.neon.tech/db")
    assert "SenhaForte" not in out
    assert "postgresql://fea:" in out and "@ep-x.neon.tech/db" in out


def test_key_value_secrets_are_redacted():
    out = redact_text('refresh_token=1//0gAbc&client_secret: "GOCSPX-xyz"')
    assert "1//0gAbc" not in out and "GOCSPX-xyz" not in out


def test_sensitive_extra_fields_are_redacted():
    data = format_record("conta conectada", access_token="ya29.x", account="Conta A")
    assert data["access_token"] == REDACTED
    assert data["account"] == "Conta A"


def test_nested_structures_are_redacted():
    out = redact({"conta": "A", "credentials": {"token": "x"}, "lista": ["Bearer abc"]})
    assert out["credentials"] == REDACTED
    assert out["lista"] == [f"Bearer {REDACTED}"]


def test_plain_messages_are_kept():
    data = format_record("render concluído", item_id=42)
    assert data["msg"] == "render concluído"
    assert data["item_id"] == 42
