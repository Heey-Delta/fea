"""Configuração lida das variáveis de ambiente (ou de um arquivo .env local)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = DEFAULT_SECRET_KEY

    # Usuário único da ferramenta. A senha fica só como hash (python -m core.security).
    app_user: str = "admin"
    app_password_hash: str = ""

    # Neon em produção; Postgres local em desenvolvimento.
    database_url: str = "postgresql://fea:fea@localhost:5432/fea"

    # Chave Fernet dos tokens das contas. Precisa ser a mesma na Vercel e na VPS.
    token_encryption_key: str = ""

    # Cloudflare R2.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""

    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def check_production(self) -> None:
        """Recusa subir em produção com segredos padrão ou ausentes."""
        if not self.is_production:
            return
        problems = []
        if self.secret_key == DEFAULT_SECRET_KEY or len(self.secret_key) < 32:
            problems.append("SECRET_KEY")
        if not self.app_password_hash:
            problems.append("APP_PASSWORD_HASH")
        if not self.token_encryption_key:
            problems.append("TOKEN_ENCRYPTION_KEY")
        if problems:
            raise RuntimeError("Configuração de produção incompleta: " + ", ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
