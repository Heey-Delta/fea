"""Configuração lida das variáveis de ambiente (ou de um arquivo .env local)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = DEFAULT_SECRET_KEY

    # Login: OAuth do GitHub, liberado só para a conta com este ID numérico.
    github_client_id: str = ""
    github_client_secret: str = ""
    github_allowed_id: str = ""
    # Endereço fixo da interface (ex.: https://fea-oh-alla.vercel.app). O GitHub só aceita
    # o retorno do login na URL cadastrada no OAuth App; sem isto, usa o endereço acessado.
    public_base_url: str = ""

    # Neon em produção; Postgres local em desenvolvimento.
    database_url: str = "postgresql://fea:fea@localhost:5432/fea"

    # Chave Fernet dos tokens das contas. Precisa ser a mesma na Vercel e na VPS.
    token_encryption_key: str = ""

    # Cloudflare R2.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""

    # Arquivos: R2 quando configurado; senão, disco local (desenvolvimento).
    storage_dir: str = "storage"

    # Reddit (Buscador): app do tipo "script" ou "web" em reddit.com/prefs/apps.
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "fea/0.1 (ferramenta de operacoes)"

    # Workers: espera por avisos do banco (LISTEN/NOTIFY) e intervalo máximo sem tarefas.
    worker_listen: bool = True
    worker_idle_max_s: float = 60.0

    log_level: str = "INFO"

    @property
    def r2_configured(self) -> bool:
        return bool(
            self.r2_account_id
            and self.r2_access_key_id
            and self.r2_secret_access_key
            and self.r2_bucket
        )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def check_production(self) -> None:
        """Recusa subir em produção com segredos padrão ou ausentes.

        As credenciais do GitHub podem faltar: sem elas o login fica desativado,
        mas a aplicação sobe e mostra o que falta configurar.
        """
        if not self.is_production:
            return
        problems = []
        if self.secret_key == DEFAULT_SECRET_KEY or len(self.secret_key) < 32:
            problems.append("SECRET_KEY")
        if not self.token_encryption_key:
            problems.append("TOKEN_ENCRYPTION_KEY")
        if problems:
            raise RuntimeError("Configuração de produção incompleta: " + ", ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
