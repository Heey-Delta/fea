import os

import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from core.security import hash_password

TEST_PASSWORD = "senha-de-teste"


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="development",
        secret_key="chave-de-teste-com-tamanho-suficiente",
        app_user="admin",
        app_password_hash=hash_password(TEST_PASSWORD),
        database_url=os.environ.get("TEST_DATABASE_URL", "postgresql://fea:fea@localhost:5432/fea"),
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    from web.main import create_app

    return TestClient(create_app(settings))


@pytest.fixture
def logged_client(client: TestClient) -> TestClient:
    response = client.post(
        "/login", data={"username": "admin", "password": TEST_PASSWORD}, follow_redirects=False
    )
    assert response.status_code == 303
    return client
