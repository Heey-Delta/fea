import pytest
from cryptography.fernet import Fernet

from core.config import DEFAULT_SECRET_KEY, Settings
from core.security import TokenCipher


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
    settings = Settings(_env_file=None, app_env="production", secret_key=DEFAULT_SECRET_KEY)
    with pytest.raises(RuntimeError) as exc:
        settings.check_production()
    assert "SECRET_KEY" in str(exc.value) and "TOKEN_ENCRYPTION_KEY" in str(exc.value)


def test_production_starts_without_github_credentials():
    """Sem as credenciais do GitHub o login fica desativado, mas a interface sobe."""
    Settings(
        _env_file=None,
        app_env="production",
        secret_key="x" * 40,
        token_encryption_key=Fernet.generate_key().decode(),
    ).check_production()
