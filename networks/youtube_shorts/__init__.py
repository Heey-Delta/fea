"""Perfil YouTube Shorts (Task 9.5).

Limites conferidos em buscas (as páginas oficiais estavam bloqueadas na sessão em que foi
escrito): Shorts até 3 minutos desde outubro de 2024; título até 100 caracteres e descrição
até 5.000 são os limites conhecidos do YouTube. Confirmar no console antes de produção (9.6).
"""

from networks.base import NetworkProfile, OutputSpec

PROFILE = NetworkProfile(
    id="youtube_shorts",
    name="YouTube Shorts",
    output=OutputSpec(width=1080, height=1920, fps=30),
    max_duration_s=180,
    allowed_resolutions=((1080, 1920), (720, 1280)),
    allowed_fps=(24, 25, 30, 50, 60),
    title_max_chars=100,
    description_max_chars=5000,
    tags_max_chars=500,
    capabilities=frozenset({"direct_publish", "native_schedule"}),
    notes="Sem auditoria do Google, uploads pela API ficam privados.",
)
