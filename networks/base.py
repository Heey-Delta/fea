"""Perfil de rede social (Task 9.1).

Cada rede é um pacote em networks/ com um NetworkProfile: o padrão de saída do vídeo, as
restrições, os limites de metadados e as capacidades da plataforma. O motor genérico (core/)
nunca importa networks/; quem junta os dois é a interface e o worker (Task 9.4).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OutputSpec:
    width: int
    height: int
    fps: int
    video_codec: str = "h264"
    audio_codec: str = "aac"
    pixel_format: str = "yuv420p"
    container: str = "mp4"

    @property
    def aspect(self) -> str:
        from math import gcd

        d = gcd(self.width, self.height)
        return f"{self.width // d}:{self.height // d}"


@dataclass(frozen=True)
class NetworkProfile:
    id: str
    name: str
    platform: str  # plataforma das contas que publicam neste perfil (accounts.platform)
    output: OutputSpec
    max_duration_s: float
    allowed_resolutions: tuple[tuple[int, int], ...]
    allowed_fps: tuple[int, ...]
    title_max_chars: int
    description_max_chars: int
    tags_max_chars: int
    capabilities: frozenset[str] = field(default_factory=frozenset)
    notes: str = ""

    def validate_preset(self, preset: dict) -> list[str]:
        """Erros do preset de Edição contra as restrições do perfil (Task 9.3)."""
        errors = []
        video = preset.get("video") or {}
        size = (
            int(video.get("width", self.output.width)),
            int(video.get("height", self.output.height)),
        )
        if size not in self.allowed_resolutions:
            allowed = ", ".join(f"{w}×{h}" for w, h in self.allowed_resolutions)
            errors.append(f"Resolução {size[0]}×{size[1]} não aceita em {self.name} ({allowed}).")
        fps = int(video.get("fps", self.output.fps))
        if fps not in self.allowed_fps:
            errors.append(f"{fps} FPS não aceito em {self.name}.")
        return errors


# --- Adaptador de publicação (Task 20.1) ---------------------------------------------------


@dataclass
class PublishRequest:
    file_path: str
    title: str
    description: str
    tags: list[str]
    privacy: str = "public"
    publish_at: str | None = None  # ISO 8601, agendamento nativo da plataforma
    file_url: str | None = None  # URL pública e temporária do arquivo (Instagram)


@dataclass
class PublishResult:
    external_id: str
    url: str
    status: str = "published"  # published | processing | scheduled_platform


class AdapterError(Exception):
    """Erro da plataforma. As subclasses dizem ao Postador o que fazer."""


class AuthError(AdapterError):
    """Token inválido ou revogado: a conta vai para erro e os envios dela esperam (19.6)."""


class RateLimited(AdapterError):
    """Cota ou limite de taxa: `retry_wait` de 2, 10 e 30 minutos (24.2)."""


class TemporaryError(AdapterError):
    """Falha antes do envio do arquivo (rede, 5xx): pode tentar de novo com segurança."""


class Uncertain(AdapterError):
    """Timeout no meio do envio: o vídeo pode ter sido criado. Exige `check` antes do retry."""


class PublishFailed(AdapterError):
    """Recusa definitiva (arquivo inválido, metadados recusados)."""


class PlatformAdapter:
    """Interface comum (20.1). `credentials` é o token já descriptografado (JSON)."""

    platform: str = ""
    capabilities: frozenset[str] = frozenset()

    # --- Conexão da conta (OAuth) ---------------------------------------------------------

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        raise NotImplementedError

    def exchange_code(self, code: str, redirect_uri: str) -> str:
        """Troca o código do retorno do OAuth pelas credenciais (JSON)."""
        raise NotImplementedError

    def fresh_credentials(self, credentials: str) -> str:
        """Renova o token se a plataforma exigir. Se mudar, o Postador grava o novo valor."""
        return credentials

    # --- Envio ----------------------------------------------------------------------------

    def status(self, credentials: str, external_id: str) -> PublishResult | None:
        """Envio assíncrono: resultado final, ou None se ainda processa. Falha → PublishFailed."""
        raise NotImplementedError

    def metrics(self, credentials: str, external_ids: list[str]) -> dict[str, dict]:
        """Métricas por vídeo publicado (Task 28.3): views, likes, comments…"""
        return {}

    def publish(self, credentials: str, request: PublishRequest) -> PublishResult:
        raise NotImplementedError

    def check(self, credentials: str, title: str, since_iso: str) -> PublishResult | None:
        """Procura um envio recente com este título. None = não foi criado."""
        raise NotImplementedError

    def account_info(self, credentials: str) -> tuple[str, str]:
        """(id externo, nome) da conta: usado ao conectar e no "testar"."""
        raise NotImplementedError
