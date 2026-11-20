"""Editor Nível 1 (Tasks 9 a 14 e 17) com FFmpeg de verdade."""

import ast
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from core.editor import overlay as ov
from core.editor import preset as pr
from core.editor import qc
from core.editor import render as rd
from networks import get_profile, profile_of_config

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg não instalado")
SMALL = {"video": {"width": 360, "height": 640, "fps": 30}, "export": {"x264_preset": "ultrafast"}}


def source(path: Path, size: str, audio: bool = True, duration: int = 2) -> Path:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={size}:rate=25:duration={duration}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={duration}", "-c:a", "aac"]
    cmd += ["-pix_fmt", "yuv420p", "-c:v", "libx264", "-shortest", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    d = tmp_path_factory.mktemp("src")
    return {
        "horizontal": source(d / "h.mp4", "640x360"),
        "vertical": source(d / "v.mp4", "360x640"),
        "square": source(d / "s.mp4", "480x480"),
        "silent": source(d / "mudo.mp4", "640x360", audio=False),
        "long": source(d / "longo.mp4", "640x360", duration=6),
    }


def render(tmp_path, preset_override, src, media_type="video", **kwargs):
    preset = pr.resolve({**SMALL, **preset_override} if preset_override else SMALL)
    if preset_override and "video" in preset_override:
        preset["video"].update({**SMALL["video"], **preset_override["video"]})
    info = rd.analyze(src, media_type)
    out = tmp_path / "out.mp4"
    plan = rd.plan_render(preset, src, media_type, info, out, **kwargs)
    rd.run(plan)
    return preset, plan, out


def frame_pixel(path: Path, xy: tuple[int, int], tmp: Path) -> tuple[int, int, int]:
    png = tmp / "frame.png"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            "0.5",
            "-i",
            str(path),
            "-frames:v",
            "1",
            str(png),
        ],
        check=True,
    )
    with Image.open(png) as img:
        return img.convert("RGB").getpixel(xy)


# --- enquadramento e padronização -------------------------------------------------------


@pytest.mark.parametrize("fit", ["cover", "contain", "blur"])
@pytest.mark.parametrize("kind", ["horizontal", "vertical", "square"])
def test_every_fit_produces_the_standard(tmp_path, sources, fit, kind):
    preset, plan, out = render(tmp_path, {"video": {"fit": fit}}, sources[kind])
    report = qc.check_render(
        out,
        preset,
        expected_audio=plan.has_audio,
        audio_required=False,
        used_mask=False,
        mask_configured=False,
        max_duration_s=180,
    )
    assert report.passed, report.errors


def test_contain_keeps_background_color(tmp_path, sources):
    _, _, out = render(
        tmp_path, {"video": {"fit": "contain", "background": "#FF0000"}}, sources["horizontal"]
    )
    r, g, b = frame_pixel(out, (180, 20), tmp_path)  # faixa de cima: fundo
    assert r > 200 and g < 60 and b < 60


def test_full_hd_vertical_output(tmp_path, sources):
    preset = pr.resolve({"export": {"x264_preset": "ultrafast"}})
    info = rd.analyze(sources["horizontal"], "video")
    out = tmp_path / "hd.mp4"
    plan = rd.plan_render(preset, sources["horizontal"], "video", info, out)
    rd.run(plan)
    report = qc.check_render(
        out,
        preset,
        expected_audio=True,
        audio_required=False,
        used_mask=False,
        mask_configured=False,
        max_duration_s=180,
    )
    assert report.passed, report.errors


def test_image_becomes_video(tmp_path):
    img = tmp_path / "meme.png"
    Image.new("RGB", (800, 600), (30, 120, 200)).save(img)
    preset, plan, out = render(tmp_path, {"video": {"image_duration_s": 3}}, img, "image")
    assert abs(rd.analyze(out, "video").duration - 3) < 0.2
    assert not plan.has_audio


def test_long_video_is_cut_to_network_limit(tmp_path, sources):
    _, plan, out = render(tmp_path, None, sources["long"], max_duration_s=4)
    assert abs(rd.analyze(out, "video").duration - 4) < 0.2
    assert any("cortado" in w for w in plan.warnings)


# --- máscara, elementos e textos --------------------------------------------------------


def test_mask_is_applied_over_the_video(tmp_path, sources):
    mask = tmp_path / "mask.png"
    img = Image.new("RGBA", (360, 640), (0, 0, 0, 0))
    img.paste((0, 200, 0, 255), (0, 0, 360, 80))  # faixa verde em cima, resto transparente
    img.save(mask)
    preset = pr.resolve(SMALL)
    result = ov.build_overlay(preset, tmp_path / "ov.png", mask_path=mask)
    assert result.used_mask and result.warnings == []
    _, _, out = render(tmp_path, None, sources["vertical"], overlay=result.path)
    r, g, b = frame_pixel(out, (180, 40), tmp_path)
    assert g > 150 and r < 80 and b < 80


def test_mask_with_other_size_is_adjusted_with_warning(tmp_path):
    mask = tmp_path / "m.png"
    Image.new("RGBA", (500, 500), (255, 0, 0, 255)).save(mask)
    result = ov.build_overlay(pr.resolve(SMALL), tmp_path / "ov.png", mask_path=mask)
    assert any("ajustada" in w for w in result.warnings)


def test_mask_opacity(tmp_path):
    mask = tmp_path / "m.png"
    Image.new("RGBA", (360, 640), (255, 0, 0, 255)).save(mask)
    preset = pr.resolve({**SMALL, "mask": {"opacity": 0.5}})
    path = ov.build_overlay(preset, tmp_path / "ov.png", mask_path=mask).path
    with Image.open(path) as img:
        assert abs(img.getpixel((10, 10))[3] - 128) <= 1


def test_text_is_wrapped_and_shrunk(tmp_path):
    preset = pr.resolve(
        {
            **SMALL,
            "texts": [
                {
                    "content": "Um texto bem comprido que precisa quebrar em várias linhas "
                    "para caber",
                    "size": 64,
                    "max_lines": 2,
                    "margin": 20,
                }
            ],
        }
    )
    result = ov.build_overlay(preset, tmp_path / "ov.png")
    assert result.path is not None
    assert any("reduzida" in w for w in result.warnings)
    with Image.open(result.path) as img:
        assert img.getbbox()[1] < 200  # texto no topo


def test_element_goes_to_its_corner(tmp_path):
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (100, 50), (0, 0, 255, 255)).save(logo)
    preset = pr.resolve(
        {
            **SMALL,
            "elements": [
                {"file_key": "k", "position": "bottom_right", "scale": 0.25, "margin": 10}
            ],
        }
    )
    path = ov.build_overlay(preset, tmp_path / "ov.png", element_paths=[logo]).path
    with Image.open(path) as img:
        left, top, right, bottom = img.getbbox()
    assert (right, bottom) == (350, 630) and left == 260


def test_empty_overlay_makes_no_file(tmp_path):
    assert ov.build_overlay(pr.resolve(SMALL), tmp_path / "ov.png").path is None


def test_missing_font_is_a_clear_error():
    with pytest.raises(ValueError, match="assets/fonts"):
        ov.find_font("FonteQueNaoExiste")


# --- áudio ------------------------------------------------------------------------------


def test_audio_remove(tmp_path, sources):
    _, plan, out = render(tmp_path, {"audio": {"mode": "remove"}}, sources["horizontal"])
    assert not plan.has_audio and not rd.analyze(out, "video").has_audio


def test_audio_replace_with_fades(tmp_path, sources):
    music = tmp_path / "musica.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=1",
            "-c:a",
            "aac",
            str(music),
        ],
        check=True,
    )
    preset, plan, out = render(
        tmp_path,
        {"audio": {"mode": "replace", "file_key": "k", "fade_in_s": 0.3, "fade_out_s": 0.3}},
        sources["silent"],
        replacement_audio=music,
    )
    assert plan.has_audio and rd.analyze(out, "video").has_audio  # 1s em loop até 2s


def test_silent_source_warns_and_required_audio_blocks(tmp_path, sources):
    preset, plan, out = render(tmp_path, None, sources["silent"])
    assert "O original não tem áudio." in plan.warnings
    ok = qc.check_render(
        out,
        preset,
        expected_audio=False,
        audio_required=False,
        used_mask=False,
        mask_configured=False,
        max_duration_s=180,
    )
    blocked = qc.check_render(
        out,
        preset,
        expected_audio=False,
        audio_required=True,
        used_mask=False,
        mask_configured=False,
        max_duration_s=180,
    )
    assert ok.passed and not blocked.passed


# --- QC ---------------------------------------------------------------------------------


def test_qc_blocks_wrong_output(tmp_path, sources):
    preset = pr.resolve(SMALL)
    report = qc.check_render(
        sources["horizontal"],
        preset,
        expected_audio=True,
        audio_required=False,
        used_mask=False,
        mask_configured=True,
        max_duration_s=180,
    )
    assert not report.passed
    names = {e.split(":")[0] for e in report.errors}
    assert {"resolução e proporção", "FPS", "máscara aplicada"} <= names


def test_qc_missing_file(tmp_path):
    report = qc.check_render(
        tmp_path / "nada.mp4",
        pr.resolve(SMALL),
        expected_audio=False,
        audio_required=False,
        used_mask=False,
        mask_configured=False,
        max_duration_s=None,
    )
    assert not report.passed


def test_qc_warnings_do_not_block(tmp_path, sources):
    preset, plan, out = render(tmp_path, None, sources["vertical"])
    report = qc.check_render(
        out,
        preset,
        expected_audio=True,
        audio_required=False,
        used_mask=False,
        mask_configured=False,
        max_duration_s=180,
        extra_warnings=["Texto 1: fonte reduzida"],
    )
    assert report.passed and report.warnings == ["aviso: Texto 1: fonte reduzida"]


# --- preset e rede ----------------------------------------------------------------------


def test_preset_defaults_and_validation():
    full = pr.resolve({"video": {"fit": "cover"}})
    assert full["video"]["width"] == 1080 and full["video"]["fit"] == "cover"
    assert pr.validate({}) == []
    errors = pr.validate(
        {
            "video": {"fit": "zoom"},
            "texts": [{"content": "{titulo}"}],
            "audio": {"mode": "replace"},
            "elements": [{"position": "meio"}],
        }
    )
    joined = " ".join(errors)
    assert "Enquadramento inválido" in joined and "título não vai escrito" in joined
    assert "falta o arquivo" in joined and "permissão de uso" in joined


def test_youtube_shorts_profile():
    profile = get_profile("youtube_shorts")
    assert profile.output.aspect == "9:16" and profile.max_duration_s == 180
    assert profile.validate_preset(pr.resolve({})) == []
    assert profile.validate_preset({"video": {"width": 1920, "height": 1080, "fps": 29}}) != []
    with pytest.raises(ValueError):
        get_profile("orkut")
    assert profile_of_config({"nodes": [{"type": "network", "config": {}}]}).id == "youtube_shorts"


def test_core_never_imports_networks():
    """Task 9.4: o motor genérico não depende de nenhuma rede."""
    for path in Path("core").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(n.split(".")[0] == "networks" for n in names), path
