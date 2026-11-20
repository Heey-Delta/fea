"""Perfil TikTok (Task 28.2).

Content Posting API: vídeo vertical, legenda (o "title" do post) até 2.200 caracteres com as
hashtags dentro. A duração máxima depende do criador (`max_video_post_duration_sec`, consultada
no envio); 10 minutos é o teto da API. Confirmar no console antes de produção.
"""

from networks.base import NetworkProfile, OutputSpec

PROFILE = NetworkProfile(
    id="tiktok",
    name="TikTok",
    platform="tiktok",
    output=OutputSpec(width=1080, height=1920, fps=30),
    max_duration_s=600,
    allowed_resolutions=((1080, 1920), (720, 1280)),
    allowed_fps=(24, 25, 30, 50, 60),
    title_max_chars=150,
    description_max_chars=2200,
    tags_max_chars=500,
    capabilities=frozenset({"direct_publish", "async_status"}),
    notes="Sem a auditoria do TikTok, os posts ficam visíveis só para o dono (SELF_ONLY).",
)
