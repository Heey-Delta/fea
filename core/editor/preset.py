"""Preset de edição (Task 15.1): valores padrão e junção com o bloco Edição do fluxo.

O preset fica dentro do JSON versionado da operação, no bloco Edição (`config.preset`).
Tudo o que não for informado usa o padrão abaixo. Execuções usam o snapshot da versão.
"""

import copy
from typing import Any

FITS = ("cover", "contain", "blur")
CROP_POSITIONS = ("center", "top", "bottom")
TEXT_POSITIONS = ("top", "center", "bottom", "custom")
ELEMENT_POSITIONS = ("top_left", "top_right", "bottom_left", "bottom_right", "center", "custom")
AUDIO_MODES = ("keep", "remove", "replace", "random")
MAX_GROUP = 20

DEFAULT_PRESET: dict[str, Any] = {
    "video": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "fit": "blur",  # A preencher (cover), B ajustar (contain), C fundo desfocado (blur)
        "crop_position": "center",
        "background": "#000000",
        "blur": 40,
        "image_duration_s": 6,
        # Agrupar imagens: 0 desliga; N (2 a 20) junta N imagens num só vídeo.
        "group_images": 0,
    },
    "mask": {
        "mask_id": None,
        "x": 0,
        "y": 0,
        "width_pct": 100,
        "height_pct": 100,
        "scale": 1.0,
        "opacity": 1.0,
        "align": "center",
    },
    "texts": [],
    "elements": [],
    "audio": {
        "mode": "keep",
        "file_key": None,
        "permission_note": "",
        "volume": 1.0,
        "normalize": True,
        "fade_in_s": 0.0,
        "fade_out_s": 0.0,
        "required": False,
        # Modo "random": sorteia uma destas músicas (chaves do armazenamento) a cada vídeo.
        "library": [],
    },
    "export": {"crf": 20, "x264_preset": "veryfast", "audio_bitrate": "128k"},
    "max_retries": 2,
}

DEFAULT_TEXT: dict[str, Any] = {
    "content": "",
    "font": "DejaVuSans-Bold",
    "size": 64,
    "color": "#FFFFFF",
    "outline": 4,
    "outline_color": "#000000",
    "shadow": True,
    "align": "center",
    "position": "top",
    "x": None,
    "y": None,
    "max_width_pct": 90,
    "max_lines": 3,
    "margin": 120,
}

DEFAULT_ELEMENT: dict[str, Any] = {
    "file_key": None,
    "position": "bottom_right",
    "x": None,
    "y": None,
    "scale": 0.2,  # largura do elemento em fração da largura do vídeo
    "opacity": 1.0,
    "margin": 60,
}


def _merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def resolve(preset: dict | None) -> dict:
    """Preset completo: o informado por cima do padrão."""
    full = _merge(DEFAULT_PRESET, preset or {})
    full["texts"] = [_merge(DEFAULT_TEXT, t) for t in (preset or {}).get("texts", [])]
    full["elements"] = [_merge(DEFAULT_ELEMENT, e) for e in (preset or {}).get("elements", [])]
    return full


def from_config(config: dict) -> dict:
    node = next((n for n in config.get("nodes") or [] if n.get("type") == "edit"), None)
    return resolve(((node or {}).get("config") or {}).get("preset"))


def validate(preset: dict) -> list[str]:
    """Erros de forma do preset (as restrições da rede vêm do perfil, Task 9.3)."""
    p = resolve(preset)
    errors = []
    video = p["video"]
    if video["fit"] not in FITS:
        errors.append(f"Enquadramento inválido: {video['fit']}.")
    if video["crop_position"] not in CROP_POSITIONS:
        errors.append(f"Posição do corte inválida: {video['crop_position']}.")
    if int(video["width"]) % 2 or int(video["height"]) % 2:
        errors.append("Largura e altura precisam ser pares.")
    if not 0 <= float(p["mask"]["opacity"]) <= 1:
        errors.append("Opacidade da máscara deve ficar entre 0 e 1.")
    for i, text in enumerate(p["texts"], 1):
        if text["position"] not in TEXT_POSITIONS:
            errors.append(f"Texto {i}: posição inválida.")
        if "{titulo}" in text["content"]:
            errors.append(f"Texto {i}: o título não vai escrito no vídeo (decisão do projeto).")
    for i, element in enumerate(p["elements"], 1):
        if element["position"] not in ELEMENT_POSITIONS:
            errors.append(f"Elemento {i}: posição inválida.")
        if not element["file_key"]:
            errors.append(f"Elemento {i}: falta o arquivo.")
    group = int(video.get("group_images") or 0)
    if group and not 2 <= group <= MAX_GROUP:
        errors.append(f"Agrupar imagens: use de 2 a {MAX_GROUP} (ou 0 para desligar).")
    audio = p["audio"]
    if audio["mode"] not in AUDIO_MODES:
        errors.append(f"Modo de áudio inválido: {audio['mode']}.")
    if audio["mode"] == "replace" and not audio["file_key"]:
        errors.append("Áudio substituto: falta o arquivo.")
    if audio["mode"] == "replace" and not audio["permission_note"]:
        errors.append("Áudio substituto: registre a permissão de uso (Task 14.4).")
    return errors
