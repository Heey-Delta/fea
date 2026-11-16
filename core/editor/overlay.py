"""Camada sobreposta do vídeo (Tasks 12, 13): máscara, elementos e textos num único PNG.

Tudo é estático e posicionado por regra fixa do preset, então a composição é feita uma vez
com o Pillow, no tamanho final do vídeo, na ordem: máscara → elementos → textos (o texto fica
por cima). O FFmpeg só sobrepõe este PNG ao vídeo enquadrado.
"""

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIRS = (
    Path(__file__).resolve().parents[2] / "assets" / "fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
)


@dataclass
class OverlayResult:
    path: Path | None
    warnings: list[str] = field(default_factory=list)
    used_mask: bool = False


def find_font(name: str) -> Path:
    """Procura a fonte pelo nome do arquivo (sem extensão) nas pastas conhecidas."""
    wanted = name.lower().removesuffix(".ttf").removesuffix(".otf")
    for folder in FONT_DIRS:
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.suffix.lower() in (".ttf", ".otf") and path.stem.lower() == wanted:
                return path
    raise ValueError(f"Fonte não encontrada: {name}. Coloque o arquivo em assets/fonts/.")


def hex_color(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


def with_opacity(img: Image.Image, opacity: float) -> Image.Image:
    img = img.convert("RGBA")
    if opacity < 1:
        alpha = img.getchannel("A").point(lambda a: round(a * opacity))
        img.putalpha(alpha)
    return img


def place_mask(canvas: Image.Image, mask_path: Path, cfg: dict, warnings: list[str]) -> None:
    """Máscara dentro da caixa (largura/altura em % da saída × escala), proporção mantida."""
    W, H = canvas.size
    with Image.open(mask_path) as mask:
        mask = mask.convert("RGBA")
        if mask.size != (W, H):
            warnings.append(f"Máscara {mask.width}×{mask.height} ajustada para {W}×{H}.")
        box_w = W * cfg["width_pct"] / 100 * cfg["scale"]
        box_h = H * cfg["height_pct"] / 100 * cfg["scale"]
        ratio = min(box_w / mask.width, box_h / mask.height)
        size = (max(1, round(mask.width * ratio)), max(1, round(mask.height * ratio)))
        mask = with_opacity(mask.resize(size, Image.LANCZOS), cfg["opacity"])
    x = cfg["x"] + round((box_w - size[0]) / 2)
    y_offsets = {"top": 0, "center": round((box_h - size[1]) / 2), "bottom": round(box_h - size[1])}
    y = cfg["y"] + y_offsets.get(cfg["align"], y_offsets["center"])
    canvas.alpha_composite(mask, (int(x), int(y)))


def place_element(canvas: Image.Image, path: Path, cfg: dict) -> None:
    W, H = canvas.size
    with Image.open(path) as element:
        element = element.convert("RGBA")
        width = max(1, round(W * cfg["scale"]))
        height = max(1, round(element.height * width / element.width))
        element = with_opacity(element.resize((width, height), Image.LANCZOS), cfg["opacity"])
    m = cfg["margin"]
    positions = {
        "top_left": (m, m),
        "top_right": (W - width - m, m),
        "bottom_left": (m, H - height - m),
        "bottom_right": (W - width - m, H - height - m),
        "center": ((W - width) // 2, (H - height) // 2),
        "custom": (cfg["x"] or 0, cfg["y"] or 0),
    }
    canvas.alpha_composite(element, positions[cfg["position"]])


def wrap(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if font.getlength(candidate) <= max_width or not line:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def place_text(canvas: Image.Image, cfg: dict, index: int, warnings: list[str]) -> None:
    """Quebra de linha pela largura máxima; reduz a fonte se passar do limite de linhas."""
    if not cfg["content"].strip():
        return
    W, H = canvas.size
    font_path = find_font(cfg["font"])
    max_width = W * cfg["max_width_pct"] / 100
    size = int(cfg["size"])
    while True:
        font = ImageFont.truetype(str(font_path), size)
        lines = wrap(cfg["content"], font, max_width)
        if len(lines) <= cfg["max_lines"] or size <= 24:
            break
        size -= 4
    if size < int(cfg["size"]):
        warnings.append(f"Texto {index}: fonte reduzida de {cfg['size']} para {size} para caber.")
    if len(lines) > cfg["max_lines"]:
        warnings.append(f"Texto {index}: passou de {cfg['max_lines']} linhas.")
    draw = ImageDraw.Draw(canvas)
    spacing = round(size * 0.2)
    stroke = int(cfg["outline"])
    box = draw.multiline_textbbox(
        (0, 0),
        "\n".join(lines),
        font=font,
        spacing=spacing,
        stroke_width=stroke,
        align=cfg["align"],
    )
    block_w, block_h = box[2] - box[0], box[3] - box[1]
    margin = int(cfg["margin"])
    if cfg["position"] == "custom":
        x, y = cfg["x"] or 0, cfg["y"] or 0
    else:
        y = {"top": margin, "center": (H - block_h) // 2, "bottom": H - margin - block_h}[
            cfg["position"]
        ]
        x = {"left": (W - max_width) / 2, "right": (W + max_width) / 2 - block_w}.get(
            cfg["align"], (W - block_w) / 2
        )
    x, y = round(x - box[0]), round(y - box[1])
    text = "\n".join(lines)
    if cfg["shadow"]:
        shadow = round(size * 0.06) or 2
        draw.multiline_text(
            (x + shadow, y + shadow),
            text,
            font=font,
            spacing=spacing,
            fill=(0, 0, 0, 140),
            align=cfg["align"],
        )
    draw.multiline_text(
        (x, y),
        text,
        font=font,
        spacing=spacing,
        fill=hex_color(cfg["color"]),
        stroke_width=stroke,
        stroke_fill=hex_color(cfg["outline_color"]),
        align=cfg["align"],
    )


def build_overlay(
    preset: dict,
    out: Path,
    mask_path: Path | None = None,
    element_paths: list[Path] | None = None,
) -> OverlayResult:
    """Monta o PNG da camada. Sem máscara, elemento ou texto, não gera arquivo."""
    W, H = int(preset["video"]["width"]), int(preset["video"]["height"])
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    result = OverlayResult(path=None)
    if mask_path:
        place_mask(canvas, mask_path, preset["mask"], result.warnings)
        result.used_mask = True
    for path, cfg in zip(element_paths or [], preset["elements"], strict=False):
        place_element(canvas, path, cfg)
    for i, cfg in enumerate(preset["texts"], 1):
        place_text(canvas, cfg, i, result.warnings)
    if canvas.getbbox() is None:
        return result
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    result.path = out
    return result
