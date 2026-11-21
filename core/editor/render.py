"""Render com FFmpeg (Tasks 10, 11 e 14).

Etapas: análise (ffprobe) → enquadramento → padronização (resolução, FPS, pixel format) →
camada sobreposta (máscara, elementos, textos) → áudio → H.264/AAC MP4.

Enquadramento:
- cover (A, preencher): cobre a tela e corta o excesso, com posição do corte;
- contain (B, ajustar): vídeo inteiro, sobras com a cor de fundo;
- blur (C, fundo desfocado): o próprio vídeo ampliado e desfocado atrás do vídeo inteiro.
"""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from core.fishing import probe


@dataclass
class SourceInfo:
    width: int
    height: int
    duration: float
    has_audio: bool
    fps: float


@dataclass
class RenderPlan:
    command: list[str]
    duration: float
    has_audio: bool
    warnings: list[str] = field(default_factory=list)


def analyze(path: Path, media_type: str) -> SourceInfo:
    """Etapa 2 (Task 10.2): o que é o original."""
    info = probe(path)
    video = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("arquivo sem imagem")
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
    num, _, den = rate.partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    duration = float(info["format"].get("duration") or 0) if media_type == "video" else 0.0
    return SourceInfo(
        width=int(video["width"]),
        height=int(video["height"]),
        duration=duration,
        has_audio=any(s.get("codec_type") == "audio" for s in info["streams"]),
        fps=fps,
    )


def fit_filter(video: dict) -> str:
    """Filtro do enquadramento a partir de [0:v], saindo em [base]."""
    W, H = int(video["width"]), int(video["height"])
    fit = video["fit"]
    if fit == "cover":
        y = {"top": "0", "bottom": f"ih-{H}", "center": f"(ih-{H})/2"}[video["crop_position"]]
        return (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}:(iw-{W})/2:{y},setsar=1[base]"
        )
    if fit == "contain":
        color = video["background"].lstrip("#")
        return (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x{color},setsar=1[base]"
        )
    sigma = max(1, int(video["blur"]))
    return (
        f"[0:v]split=2[bgsrc][fgsrc];"
        f"[bgsrc]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"gblur=sigma={sigma}[bg];"
        f"[fgsrc]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]"
    )


def audio_filter(audio: dict, duration: float) -> str:
    parts = []
    if float(audio["volume"]) != 1.0:
        parts.append(f"volume={float(audio['volume'])}")
    if audio["normalize"]:
        parts.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    if float(audio["fade_in_s"]) > 0:
        parts.append(f"afade=t=in:st=0:d={float(audio['fade_in_s'])}")
    fade_out = float(audio["fade_out_s"])
    if fade_out > 0 and duration > fade_out:
        parts.append(f"afade=t=out:st={duration - fade_out:.3f}:d={fade_out}")
    parts.append("aresample=48000")
    return ",".join(parts)


def plan_render(
    preset: dict,
    source: Path,
    media_type: str,
    info: SourceInfo,
    out: Path,
    overlay: Path | None = None,
    replacement_audio: Path | None = None,
    max_duration_s: float | None = None,
) -> RenderPlan:
    video, audio, export = preset["video"], preset["audio"], preset["export"]
    warnings: list[str] = []
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if media_type == "image":
        duration = float(video["image_duration_s"])
        cmd += [
            "-loop",
            "1",
            "-framerate",
            str(video["fps"]),
            "-t",
            f"{duration}",
            "-i",
            str(source),
        ]
    else:
        duration = info.duration
        cmd += ["-i", str(source)]
    if max_duration_s and duration > max_duration_s:
        warnings.append(f"Vídeo cortado em {max_duration_s:.0f}s (limite da rede).")
        duration = max_duration_s

    inputs = 1
    filters = [fit_filter(video)]
    last = "base"
    if overlay is not None:
        cmd += ["-i", str(overlay)]
        filters.append(f"[{last}][{inputs}:v]overlay=0:0:format=auto[ov]")
        last = "ov"
        inputs += 1
    filters.append(f"[{last}]fps={video['fps']},format=yuv420p[vout]")

    audio_label = None
    mode = audio["mode"]
    if mode == "replace" and replacement_audio is not None:
        cmd += ["-stream_loop", "-1", "-i", str(replacement_audio)]
        filters.append(f"[{inputs}:a]atrim=0:{duration:.3f},{audio_filter(audio, duration)}[aout]")
        audio_label = "aout"
        inputs += 1
    elif mode == "keep" and info.has_audio:
        filters.append(f"[0:a]{audio_filter(audio, duration)}[aout]")
        audio_label = "aout"
    elif mode == "keep":
        warnings.append("O original não tem áudio.")

    cmd += ["-filter_complex", ";".join(filters), "-map", "[vout]"]
    if audio_label:
        cmd += ["-map", f"[{audio_label}]", "-c:a", "aac", "-b:a", export["audio_bitrate"]]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        export["x264_preset"],
        "-crf",
        str(export["crf"]),
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(video["fps"]),
        "-t",
        f"{duration:.3f}",
        "-movflags",
        "+faststart",
        str(out),
    ]
    return RenderPlan(
        command=cmd, duration=duration, has_audio=audio_label is not None, warnings=warnings
    )


def progress_percent(line: str, duration: float) -> float | None:
    """Porcentagem a partir de uma linha do `-progress` do FFmpeg (`out_time_us=…`)."""
    key, _, value = line.strip().partition("=")
    if key == "progress" and value == "end":
        return 100.0
    if key not in ("out_time_us", "out_time_ms") or duration <= 0:
        return None
    try:
        seconds = int(value) / 1_000_000  # as duas chaves vêm em microssegundos
    except ValueError:
        return None
    return max(0.0, min(100.0, 100 * seconds / duration))


def run(plan: RenderPlan, timeout_s: int = 900, on_progress=None) -> None:
    """Roda o FFmpeg. Com `on_progress`, informa a porcentagem enquanto edita."""
    if on_progress is None:
        result = subprocess.run(plan.command, capture_output=True, text=True, timeout=timeout_s)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg falhou: {result.stderr.strip()[-500:]}")
        return
    import tempfile
    import time

    cmd = [plan.command[0], "-progress", "pipe:1", "-nostats", *plan.command[1:]]
    started = time.monotonic()
    with tempfile.TemporaryFile(mode="w+") as errors:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors, text=True)
        try:
            for line in proc.stdout:
                percent = progress_percent(line, plan.duration)
                if percent is not None:
                    on_progress(percent)
                if time.monotonic() - started > timeout_s:
                    proc.kill()
                    raise subprocess.TimeoutExpired(cmd, timeout_s)
            proc.wait(timeout=max(1, timeout_s - (time.monotonic() - started)))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if proc.returncode != 0:
            errors.seek(0)
            raise RuntimeError(f"FFmpeg falhou: {errors.read().strip()[-500:]}")
