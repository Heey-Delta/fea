import pytest
from cryptography.fernet import Fernet

from core.config import DEFAULT_SECRET_KEY, Settings
from core.security import TokenCipher, hash_password, verify_password


def test_password_hash_roundtrip():
    stored = hash_password("abc123")
    assert stored.startswith("scrypt:")
    assert "$" not in stored  # não pode ser interpolado pelo Docker Compose
    assert verify_password("abc123", stored)
    assert not verify_password("abc124", stored)


def test_verify_rejects_malformed_hash():
    assert not verify_password("x", "")
    assert not verify_password("x", "md5:00:11")
    assert not verify_password("x", "scrypt:zz:11")


def test_token_cipher_roundtrip():
    cipher = TokenCipher(Fernet.generate_key().decode())
    encrypted = cipher.encrypt("ya29.token-oauth")
    assert "ya29" not in encrypted
    assert cipher.decrypt(encrypted) == "ya29.token-oauth"


def test_token_cipher_wrong_key():
    encrypted = TokenCipher(Fernet.generate_key().decode()).encrypt("segredo")
    with pytest.raises(ValueError):
        TokenCipher(Fernet.generate_key().decode()).decrypt(encrypted)


def test_token_cipher_requires_key():
    with pytest.raises(ValueError):
        TokenCipher("")


def test_production_refuses_default_secrets():
    with pytest.raises(RuntimeError) as exc:
        Settings(
            _env_file=None, app_env="production", secret_key=DEFAULT_SECRET_KEY
        ).check_production()
    message = str(exc.value)
    assert "SECRET_KEY" in message and "APP_PASSWORD_HASH" in message
    assert "TOKEN_ENCRYPTION_KEY" in message


def test_production_accepts_complete_config():
    Settings(
        _env_file=None,
        app_env="production",
        secret_key="x" * 40,
        app_password_hash=hash_password("p"),
        token_encryption_key=Fernet.generate_key().decode(),
    ).check_production()
