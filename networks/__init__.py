"""Registro dos perfis de rede (Task 9.2). Rede nova = pacote novo + uma linha aqui."""

from networks.base import NetworkProfile
from networks.youtube_shorts import PROFILE as YOUTUBE_SHORTS

PROFILES: dict[str, NetworkProfile] = {YOUTUBE_SHORTS.id: YOUTUBE_SHORTS}
DEFAULT = YOUTUBE_SHORTS.id


def get_profile(profile_id: str | None) -> NetworkProfile:
    try:
        return PROFILES[profile_id or DEFAULT]
    except KeyError as exc:
        raise ValueError(f"Rede desconhecida: {profile_id}") from exc


def profile_of_config(config: dict) -> NetworkProfile:
    node = next((n for n in config.get("nodes") or [] if n.get("type") == "network"), None)
    return get_profile(((node or {}).get("config") or {}).get("profile"))
