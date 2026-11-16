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
