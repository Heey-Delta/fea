"""Registro dos perfis de rede (Task 9.2). Rede nova = pacote novo + uma linha aqui.

Uma operação pode publicar em mais de uma rede (bloco Publicador). O vídeo editado é um só:
ele segue o padrão comum a todas as redes escolhidas (resoluções e FPS em comum, a menor
duração máxima). Título e legenda respeitam o limite de cada rede no envio.
"""

from dataclasses import replace

from networks.base import NetworkProfile
from networks.instagram_reels import PROFILE as INSTAGRAM_REELS
from networks.tiktok import PROFILE as TIKTOK
from networks.youtube_shorts import PROFILE as YOUTUBE_SHORTS

PROFILES: dict[str, NetworkProfile] = {p.id: p for p in (YOUTUBE_SHORTS, TIKTOK, INSTAGRAM_REELS)}
DEFAULT = YOUTUBE_SHORTS.id
PLATFORMS = {p.platform: p for p in PROFILES.values()}
PLATFORM_LABEL = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram"}


def get_profile(profile_id: str | None) -> NetworkProfile:
    try:
        return PROFILES[profile_id or DEFAULT]
    except KeyError as exc:
        raise ValueError(f"Rede desconhecida: {profile_id}") from exc


def profile_for_platform(platform: str) -> NetworkProfile:
    return PLATFORMS.get(platform, YOUTUBE_SHORTS)


def profile_ids_of_config(config: dict) -> list[str]:
    node = next((n for n in config.get("nodes") or [] if n.get("type") == "network"), None)
    cfg = (node or {}).get("config") or {}
    ids = [i for i in (cfg.get("profiles") or []) if i]
    if not ids:
        ids = [cfg.get("profile") or DEFAULT]
    return list(dict.fromkeys(ids))


def merge(profiles: list[NetworkProfile]) -> NetworkProfile:
    """Padrão comum: o que todas as redes aceitam."""
    if len(profiles) == 1:
        return profiles[0]
    first = profiles[0]
    resolutions = tuple(
        r for r in first.allowed_resolutions if all(r in p.allowed_resolutions for p in profiles)
    )
    fps = tuple(f for f in first.allowed_fps if all(f in p.allowed_fps for p in profiles))
    return replace(
        first,
        id="+".join(p.id for p in profiles),
        name=" + ".join(p.name for p in profiles),
        max_duration_s=min(p.max_duration_s for p in profiles),
        allowed_resolutions=resolutions or first.allowed_resolutions,
        allowed_fps=fps or first.allowed_fps,
        title_max_chars=min(p.title_max_chars for p in profiles),
        description_max_chars=min(p.description_max_chars for p in profiles),
        tags_max_chars=min(p.tags_max_chars for p in profiles),
        notes=" ".join(p.notes for p in profiles if p.notes),
    )


def profiles_of_config(config: dict) -> list[NetworkProfile]:
    return [get_profile(i) for i in profile_ids_of_config(config)]


def profile_of_config(config: dict) -> NetworkProfile:
    return merge(profiles_of_config(config))


def make_adapter(platform: str, settings, client_factory=None):
    """Adaptador de publicação da plataforma da conta (Tasks 20 e 28.2)."""
    if platform == "youtube":
        from networks.youtube_shorts.adapter import YouTubeAdapter

        return YouTubeAdapter(
            settings.google_client_id, settings.google_client_secret, client_factory
        )
    if platform == "tiktok":
        from networks.tiktok.adapter import TikTokAdapter

        return TikTokAdapter(
            settings.tiktok_client_key, settings.tiktok_client_secret, client_factory
        )
    if platform == "instagram":
        from networks.instagram_reels.adapter import InstagramAdapter

        return InstagramAdapter(
            settings.instagram_app_id, settings.instagram_app_secret, client_factory
        )
    raise ValueError(f"Plataforma sem adaptador: {platform}")
