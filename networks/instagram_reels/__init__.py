"""Perfil Instagram Reels (Task 28.2).

Instagram API with Instagram Login: o Reels é criado a partir de uma URL pública do vídeo (o R2
gera uma URL assinada), processado de forma assíncrona e depois publicado. Legenda até 2.200
caracteres e até 30 hashtags. Conta profissional (Criador ou Empresa).
"""

from networks.base import NetworkProfile, OutputSpec

PROFILE = NetworkProfile(
    id="instagram_reels",
    name="Instagram Reels",
    platform="instagram",
    output=OutputSpec(width=1080, height=1920, fps=30),
    max_duration_s=900,
    allowed_resolutions=((1080, 1920), (720, 1280)),
    allowed_fps=(24, 25, 30, 50, 60),
    title_max_chars=150,
    description_max_chars=2200,
    tags_max_chars=500,
    capabilities=frozenset({"direct_publish", "async_status", "needs_public_url"}),
    notes="Precisa do armazenamento R2: o Instagram baixa o vídeo por uma URL pública.",
)
