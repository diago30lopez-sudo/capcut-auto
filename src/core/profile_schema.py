"""Schema del perfil de edición y validación.

v2.0.0: EditProfile es la representación tipada de un perfil JSON.
Todos los campos de un canal viven aquí. Añadir un canal = añadir
un .json en profiles/, sin tocar código Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "3.0.0"


@dataclass
class EditProfile:
    # Identidad del perfil
    name: str = ""
    profile_id: str = ""
    project_name_suffix: str = ""
    default_project_name: str = ""

    # Watermark
    watermark_text: str = ""
    watermark_font_size: float = 8.0
    watermark_alpha: float = 0.15
    watermark_pos_x_json: float = 0.0
    watermark_pos_y_json: float = 0.0
    watermark_bold: bool = True
    watermark_italic: bool = True
    watermark_letter_spacing_json: float = 0.10
    watermark_font_path: str = ""
    watermark_font_resource_id: str = ""
    watermark_font_name: str = ""

    # Subtítulos
    subtitle_font_candidates: tuple = ()
    subtitle_font_size: float = 12.0
    subtitle_color: list = field(default_factory=lambda: [1.0, 1.0, 1.0])
    subtitle_keyword_color: list = field(default_factory=lambda: [1.0, 0.8431373, 0.0])
    subtitle_stroke_width_json: float = 0.06
    subtitle_pos_y_json: float = -0.8333333
    subtitle_popup: bool = True
    subtitle_uppercase: bool = True
    subtitle_max_words_per_line: int = 5
    subtitle_keywords: frozenset = field(default_factory=frozenset)
    subtitle_font_path: str = ""
    subtitle_font_resource_id: str = ""
    subtitle_font_name: str = ""

    # Toggles de features
    enable_transitions: bool = True
    enable_color_grading: bool = True
    enable_hsl: bool = True
    enable_paneos: bool = True
    enable_camera_shake: bool = True
    enable_sfx: bool = True
    enable_imagina_esto: bool = False

    # Zoom
    zoom_end_min: float = 1.10
    zoom_end_max: float = 1.15

    # Paneos y shake
    pan_ratio: float = 0.6
    pan_amplitude: tuple = (0.04, 0.08)
    shake_ratio: float = 1.0
    shake_amplitude: tuple = (0.010, 0.020)
    shake_zoom_boost: float = 1.06

    # CTA (ronda 8 fix)
    cta_enabled: bool = False
    cta_patterns: tuple = ()
    cta_avoid_overlap: bool = False

    # Match threshold del matcher
    match_threshold: float = 75.0

    # Sync audio a duración real
    sync_audio_to_real_end: bool = False

    # Transiciones
    transition_rules: dict = field(default_factory=lambda: {"type": "random", "ratio": 0.98})
    extra_assets: list = field(default_factory=list)
    layout_rules: dict = field(default_factory=dict)
    min_duration_us: int = 1500000
    fade_in_duration_us: int = 0
    transition_names: tuple = ()
    transition_ratio: float = 0.98

    # Color grading (valores fijos opcionales, si no None → aleatorio)
    grading_contrast: float | None = None
    grading_shadows: float | None = None
    grading_brightness: float | None = None
    grading_random: bool = False
    hsl_channels: list = field(default_factory=list)
    vignette_intensity: float = 0.0

    # Overlays
    glow_keywords: bool = False
    grid_overlay_enabled: bool = False
    grid_overlay_keywords: tuple = ()
    neon_text_enabled: bool = False

    # Color grading mode
    grading_random: bool = False

    # Audio
    sfx_dir: Any = None
    bgm_dir: Any = None
    bgm_volume_db: float = -20.0
    ducking_depth_db: float = -8.0
    ducking_active: bool = False

    # DYC específico (aunque los campos viven aquí, su uso depende del perfil)
    dyc_assets_dir: str | None = None
    dyc_start_animations: tuple = ()
    dyc_end_animation: Any = None
    dyc_color_effects: tuple = ()
    dyc_hsl_channels: tuple = ()
    dyc_subtitle_font: str = ""
    dyc_subtitle_font_resource_id: str | None = None
    dyc_glitch_transitions: tuple = ()

    # Chroma
    chroma_enabled: bool = False
    chroma_color: str = "#00FF00"
    chroma_intensity: float = 0.25
    chroma_shadow: float = 0.0
    chroma_edge_smooth: float = 0.0
    chroma_spill: float = 0.0


def resolve_placeholders(
    profile_data: dict[str, Any],
    dyc_assets_dir: str | None = None,
    repo_root: str | None = None,
    user_home: str | None = None,
) -> dict[str, Any]:
    """Sustituye placeholders {USER}, {USER_HOME}, {REPO_ROOT}, {DYC_ASSETS}
    en cualquier string del perfil. Devuelve una copia con los valores resueltos."""
    if repo_root is None:
        repo_root = str(Path(__file__).resolve().parent.parent.parent)
    if user_home is None:
        user_home = str(Path.home())

    replacements = {
        "{USER_HOME}": user_home.replace("\\", "/"),
        "{REPO_ROOT}": repo_root.replace("\\", "/"),
        "{USER}": Path(user_home).name,
    }
    if dyc_assets_dir:
        replacements["{DYC_ASSETS}"] = str(dyc_assets_dir).replace("\\", "/")

    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(v) for v in obj]
        if isinstance(obj, str):
            for key, val in replacements.items():
                obj = obj.replace(key, val)
            return obj
        return obj

    return _walk(profile_data)


def validate_profile(profile_data: dict[str, Any], profile_name: str) -> None:
    """Valida mínimamente un perfil contra el schema v2.0.0.

    Lanza ValueError si algo no cuadra.
    """
    if not isinstance(profile_data, dict):
        raise ValueError(f"[{profile_name}] El perfil debe ser un objeto JSON (dict).")

    if "schema_version" not in profile_data:
        raise ValueError(f"[{profile_name}] Falta 'schema_version'.")

    meta = profile_data.get("meta")
    if not isinstance(meta, dict):
        raise ValueError(f"[{profile_name}] Falta el bloque 'meta'.")

    if not meta.get("id"):
        raise ValueError(f"[{profile_name}] Falta meta.id.")

    if not meta.get("name"):
        raise ValueError(f"[{profile_name}] Falta meta.name.")

    # Bloque watermark (opcional pero si existe debe ser dict)
    for block in (
        "watermark",
        "subtitulos",
        "zoom",
        "transiciones",
        "paneos",
        "shake",
        "audio",
        "pipeline",
        "chroma",
        "assets",
        "cta",
    ):
        if block in profile_data and not isinstance(profile_data[block], dict):
            raise ValueError(f"[{profile_name}] El bloque '{block}' debe ser un dict.")


def parse_transition_rules(rules_data: dict | None) -> dict:
    """Devuelve las reglas de transición normalizadas."""
    if not rules_data or not isinstance(rules_data, dict):
        return {"type": "random", "ratio": 0.98}
    rule_type = str(rules_data.get("type", "random"))
    result = {"type": rule_type}
    if rule_type == "every_n":
        result["n"] = int(rules_data.get("n", 3))
    elif rule_type == "specific_cuts":
        result["indices"] = [int(i) for i in rules_data.get("indices", [])]
    elif rule_type == "keyword":
        result["keywords"] = list(rules_data.get("keywords", []))
    elif rule_type == "random":
        result["ratio"] = float(rules_data.get("ratio", 0.98))
    return result


def parse_extra_assets(assets_data: list | None) -> list:
    """Devuelve la lista de assets extra normalizada."""
    if not assets_data or not isinstance(assets_data, list):
        return []
    parsed = []
    for item in assets_data:
        if not isinstance(item, dict):
            continue
        parsed.append({
            "file": str(item.get("file", "")),
            "type": str(item.get("type", "audio")),
            "trigger": str(item.get("trigger", "start")),
            "time_us": int(item.get("time_us", 0)),
            "duration_us": int(item.get("duration_us", 0)),
            "volume_db": float(item.get("volume_db", 0.0)),
            "chroma_enabled": bool(item.get("chroma_enabled", False)),
            "chroma_color": str(item.get("chroma_color", "#000000")),
        })
    return parsed


def parse_layout_rules(layout_data: dict | None) -> dict:
    """Devuelve las reglas de layout normalizadas."""
    if not layout_data or not isinstance(layout_data, dict):
        return {}
    mode = str(layout_data.get("mode", "audio_sync"))
    result = {"mode": mode}
    if mode == "fixed_gap":
        result["gap_seconds"] = float(layout_data.get("gap_seconds", 2.0))
    elif mode == "fixed_duration":
        result["duration_seconds"] = float(layout_data.get("duration_seconds", 3.0))
    result["min_duration_us"] = int(layout_data.get("min_duration_us", 33333))
    return result
