"""Controle de qualidade do render (Task 17).

Impeditivo bloqueia a aprovação; aviso passa e fica visível (Task 17.2).
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.fishing import probe


@dataclass
class Check:
    name: str
    ok: bool
    blocking: bool
    detail: str = ""


@dataclass
class QCReport:
    checks: list[Check] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks if c.blocking)

    @property
    def errors(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if c.blocking and not c.ok]

    def add(self, name: str, ok: bool, detail: str = "", blocking: bool = True) -> None:
        self.checks.append(Check(name, ok, blocking, detail))
        if not ok and not blocking:
            self.warnings.append(f"{name}: {detail}")

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checks": [asdict(c) for c in self.checks],
            "warnings": self.warnings,
        }


def check_render(
    path: Path,
    preset: dict,
    *,
    expected_audio: bool,
    audio_required: bool,
    used_mask: bool,
    mask_configured: bool,
    max_duration_s: float | None,
    extra_warnings: list[str] | None = None,
) -> QCReport:
    report = QCReport()
    video_cfg = preset["video"]
    report.add("arquivo existe", path.is_file() and path.stat().st_size > 0, str(path.name))
    if not path.is_file():
        return report
    try:
        info = probe(path)
    except ValueError as exc:
        report.add("arquivo abre", False, str(exc))
        return report
    report.add("arquivo abre", True)
    video = next((s for s in info["streams"] if s.get("codec_type") == "video"), {})
    audio = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
    size = (video.get("width"), video.get("height"))
    want = (int(video_cfg["width"]), int(video_cfg["height"]))
    report.add(
        "resolução e proporção", size == want, f"{size[0]}×{size[1]} (esperado {want[0]}×{want[1]})"
    )
    num, _, den = (video.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0
    report.add("FPS", abs(fps - int(video_cfg["fps"])) < 0.5, f"{fps:.2f}")
    report.add("codec de vídeo", video.get("codec_name") == "h264", str(video.get("codec_name")))
    report.add("pixel format", video.get("pix_fmt") == "yuv420p", str(video.get("pix_fmt")))
    report.add(
        "formato",
        "mp4" in info["format"].get("format_name", ""),
        info["format"].get("format_name", ""),
    )
    duration = float(info["format"].get("duration") or 0)
    valid = duration > 0 and (not max_duration_s or duration <= max_duration_s + 0.5)
    report.add("duração", valid, f"{duration:.1f}s")
    if expected_audio:
        report.add(
            "áudio",
            audio is not None and audio.get("codec_name") == "aac",
            str(audio.get("codec_name")) if audio else "sem faixa de áudio",
        )
    elif audio_required:
        report.add("áudio", False, "o preset exige áudio e o original não tem")
    else:
        report.add("áudio", True, "sem áudio, conforme o original ou o preset")
    if mask_configured:
        report.add(
            "máscara aplicada", used_mask, "" if used_mask else "máscara configurada e não aplicada"
        )
    for warning in extra_warnings or []:
        report.add("aviso", False, warning, blocking=False)
    return report
