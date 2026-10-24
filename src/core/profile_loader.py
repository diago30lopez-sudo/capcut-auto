"""Cargador de perfiles de edición desde archivos JSON.

Lee todos los archivos .json en una carpeta, valida cada uno contra
el schema y devuelve un diccionario {nombre_del_perfil: perfil}.

Uso:
    from src.core.profile_loader import load_profiles
    profiles = load_profiles("D:/capcut-auto/profiles")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.core.profile_schema import validate_profile, resolve_placeholders

log = logging.getLogger("capcutauto")


def load_profiles(
    profiles_dir: str | Path,
    dyc_assets_dir: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Carga todos los perfiles JSON de la carpeta indicada."""
    profiles_path = Path(profiles_dir)
    if not profiles_path.is_dir():
        profiles_path.mkdir(parents=True, exist_ok=True)
        log.warning("Carpeta de perfiles no existía: %s. Creada vacía.", profiles_path)
        return {}

    json_files = sorted(profiles_path.glob("*.json"))
    if not json_files:
        log.warning("No se encontraron perfiles en %s.", profiles_path)
        return {}

    profiles: dict[str, dict[str, Any]] = {}
    for json_file in json_files:
        try:
            raw = json.loads(json_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Error leyendo %s: %s", json_file.name, exc)
            continue

        if not isinstance(raw, dict):
            log.error("%s: el archivo debe contener un objeto JSON.", json_file.name)
            continue

        resolved = resolve_placeholders(raw, dyc_assets_dir=dyc_assets_dir)
        profile_name = json_file.stem

        try:
            validate_profile(resolved, profile_name)
        except ValueError as exc:
            log.error("Perfil '%s' inválido en %s:\n%s", profile_name, json_file.name, exc)
            continue

        profiles[profile_name] = resolved
        log.info(
            "Perfil cargado: %s (%s)",
            profile_name,
            resolved.get("meta", {}).get("name", "sin nombre"),
        )

    return profiles


def get_profile(
    profiles: dict[str, dict[str, Any]],
    name: str,
) -> dict[str, Any]:
    """Devuelve un perfil por su id (meta.id)."""
    for pid, data in profiles.items():
        meta = data.get("meta", {})
        if meta.get("id") == name or pid == name:
            return data
    raise ValueError(f"Perfil no encontrado: '{name}'. Disponibles: {list(profiles.keys())}")


def get_profile_names(profiles: dict[str, dict[str, Any]]) -> list[str]:
    """Devuelve la lista de nombres visibles."""
    names = []
    for pid, data in profiles.items():
        meta = data.get("meta", {})
        names.append(meta.get("name", pid))
    return names


def get_profile_by_display_name(
    profiles: dict[str, dict[str, Any]],
    display_name: str,
) -> dict[str, Any]:
    """Devuelve un perfil por su nombre visible (meta.name)."""
    for pid, data in profiles.items():
        meta = data.get("meta", {})
        if meta.get("name") == display_name or pid == display_name:
            return data
    raise ValueError(
        f"Perfil no encontrado: '{display_name}'. Disponibles: {get_profile_names(profiles)}"
    )


def build_edit_profile(profile_data: dict[str, Any]):
    """Convierte un perfil JSON a un objeto EditProfile."""
    from src.core.profile_schema import EditProfile, parse_transition_rules, parse_extra_assets, parse_layout_rules

    meta_id = profile_data.get("meta", {}).get("id", "")
    defaults = {
        "name": profile_data.get("meta", {}).get("name", meta_id),
        "profile_id": meta_id,
        "project_name_suffix": profile_data.get("project_name_suffix", ""),
        "watermark_text": profile_data.get("watermark", {}).get("text", ""),
        "watermark_font_size": profile_data.get("watermark", {}).get("font_size", 8.0),
        "watermark_alpha": profile_data.get("watermark", {}).get("opacity", 0.15),
        "watermark_pos_x_json": profile_data.get("watermark", {}).get("position_x", 0.0),
        "watermark_pos_y_json": profile_data.get("watermark", {}).get("position_y", 0.0),
        "watermark_bold": profile_data.get("watermark", {}).get("bold", True),
        "watermark_italic": profile_data.get("watermark", {}).get("italic", True),
        "watermark_letter_spacing_json": profile_data.get("watermark", {}).get("letter_spacing", 0.10),
        "watermark_font_path": profile_data.get("watermark", {}).get("font_path", ""),
        "watermark_font_resource_id": profile_data.get("watermark", {}).get("font_resource_id", ""),
        "watermark_font_name": profile_data.get("watermark", {}).get("font_name", ""),
        "subtitle_font_candidates": (),
        "subtitle_font_size": profile_data.get("subtitulos", {}).get("font_size", 12.0),
        "subtitle_color": [1.0, 1.0, 1.0],
        "subtitle_keyword_color": profile_data.get("subtitulos", {}).get("keyword_color", [1.0, 0.8431373, 0.0]),
        "subtitle_stroke_width_json": profile_data.get("subtitulos", {}).get("stroke_width", 0.06),
        "subtitle_pos_y_json": profile_data.get("subtitulos", {}).get("position_y", -0.8333333),
        "subtitle_popup": profile_data.get("subtitulos", {}).get("popup", True),
        "subtitle_uppercase": profile_data.get("subtitulos", {}).get("uppercase", True),
        "subtitle_max_words_per_line": profile_data.get("subtitulos", {}).get("max_words_per_line", 5),
        "subtitle_keywords": frozenset(profile_data.get("subtitulos", {}).get("keywords", [])),
        "subtitle_font_path": profile_data.get("subtitulos", {}).get("font_path", ""),
        "subtitle_font_resource_id": profile_data.get("subtitulos", {}).get("font_resource_id", ""),
        "subtitle_font_name": profile_data.get("subtitulos", {}).get("font_name", ""),
        "enable_transitions": True,
        "enable_color_grading": True,
        "enable_hsl": True,
        "enable_paneos": True,
        "enable_camera_shake": True,
        "enable_sfx": True,
        "enable_imagina_esto": profile_data.get("imagina_esto", {}).get("enabled", False),
        "zoom_end_min": profile_data.get("zoom", {}).get("final_min", 1.10),
        "zoom_end_max": profile_data.get("zoom", {}).get("final_max", 1.15),
        "pan_ratio": profile_data.get("paneos", {}).get("ratio", 0.6),
        "pan_amplitude": tuple(profile_data.get("paneos", {}).get("amplitude", [0.04, 0.08])),
        "shake_ratio": profile_data.get("shake", {}).get("ratio", 1.0),
        "shake_amplitude": tuple(profile_data.get("shake", {}).get("amplitude", [0.010, 0.020])),
        "shake_zoom_boost": profile_data.get("shake", {}).get("zoom_boost", 1.06),
        "fade_in_duration_us": profile_data.get("fade_in", {}).get("duration_us", 0),
        "transition_names": tuple(profile_data.get("transiciones", {}).get("pool", [])),
        "transition_ratio": profile_data.get("transiciones", {}).get("ratio", 0.98),
        "grading_contrast": profile_data.get("color_grading", {}).get("contrast"),
        "grading_shadows": profile_data.get("color_grading", {}).get("shadow"),
        "grading_brightness": profile_data.get("color_grading", {}).get("brightness"),
        "grading_random": profile_data.get("color_grading", {}).get("random", False),
        "hsl_channels": profile_data.get("hsl", {}).get("entries", []),
        "vignette_intensity": profile_data.get("color_grading", {}).get("vignetting", 0.0),
        "glow_keywords": profile_data.get("glow", {}).get("enabled", False),
        "grid_overlay_enabled": profile_data.get("overlays", {}).get("grid_enabled", False),
        "grid_overlay_keywords": tuple(profile_data.get("overlays", {}).get("grid_keywords", [])),
        "neon_text_enabled": profile_data.get("overlays", {}).get("neon_enabled", False),
        "sfx_dir": None,
        "bgm_dir": None,
        "bgm_volume_db": profile_data.get("audio", {}).get("bgm_volume_db", -20.0),
        "ducking_depth_db": profile_data.get("audio", {}).get("ducking_depth_db", -8.0),
        "ducking_active": profile_data.get("audio", {}).get("ducking_active", False),
        "dyc_assets_dir": profile_data.get("assets", {}).get("folder"),
        "dyc_start_animations": (),
        "dyc_end_animation": None,
        "dyc_color_effects": (),
        "dyc_hsl_channels": (),
        "dyc_subtitle_font": "",
        "dyc_subtitle_font_resource_id": None,
        "sync_audio_to_real_end": False,
        "cta_enabled": profile_data.get("cta", {}).get("enabled", False),
        "cta_patterns": tuple(profile_data.get("cta", {}).get("final", {}).get("patterns", [])),
        "cta_avoid_overlap": bool(profile_data.get("cta", {}).get("avoid_overlap_with_end", False)),
        "match_threshold": profile_data.get("pipeline", {}).get("matching", {}).get("match_threshold", 75.0),
        "default_project_name": profile_data.get("meta", {}).get("default_project_name", ""),
        "chroma_enabled": profile_data.get("chroma", {}).get("enabled", False),
        "chroma_color": profile_data.get("chroma", {}).get("color", "#00FF00"),
        "chroma_intensity": profile_data.get("chroma", {}).get("intensity", 0.25),
        "chroma_shadow": profile_data.get("chroma", {}).get("shadow", 0.0),
        "chroma_edge_smooth": profile_data.get("chroma", {}).get("edge_smooth", 0.0),
        "chroma_spill": profile_data.get("chroma", {}).get("spill", 0.0),
    }

    dyc = profile_data.get("dyc", {})
    if meta_id == "datos_y_cafe" or dyc:
        defaults["dyc_subtitle_font"] = dyc.get("subtitle_font", "")
        defaults["dyc_subtitle_font_resource_id"] = dyc.get("subtitle_font_resource_id")
        defaults["dyc_start_animations"] = tuple(dyc.get("start_animations", []))
        defaults["dyc_end_animation"] = dyc.get("end_animation")
        defaults["dyc_color_effects"] = tuple(dyc.get("color_effects", []))
        defaults["dyc_hsl_channels"] = tuple(dyc.get("hsl_channels", []))
        defaults["dyc_glitch_transitions"] = tuple(dyc.get("glitch_transitions", []))

    # v3.0.0 — Motor de reglas desde JSON
    transition_rules_raw = profile_data.get("transition_rules")
    defaults["transition_rules"] = parse_transition_rules(transition_rules_raw)
    defaults["extra_assets"] = parse_extra_assets(profile_data.get("extra_assets"))
    defaults["layout_rules"] = parse_layout_rules(profile_data.get("layout_rules"))
    defaults["min_duration_us"] = defaults["layout_rules"].get("min_duration_us", 1500000)

    return EditProfile(**defaults)
