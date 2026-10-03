"""Checks de la feature v1.6.0 — Tipos de edicion (Nexus Paradoja + Datos Y Cafe).

Verifica:
1. Los perfiles de edicion existen y tienen los valores correctos.
2. El dropdown de UI tiene 2 opciones.
3. La persistencia/restauracion de last_edit_type en config_user.json.
4. Los subtítulos parametrizados con perfilDatos Y Cafe generan los valores correctos.
5. El watermark parametrizado con perfil Datos Y Cafe genera los valores correctos.
6. La deteccion de videos en auto_detect.

Ejecutar desde la raiz:
    & .venv\\Scripts\\python.exe -X utf8 tests\\edit_types_check.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.core.config import save_user_config  # noqa: E402
from src.core.edit_types import (  # noqa: E402
    EditProfile,
    get_edit_profile,
    get_edit_type_names,
    NEXUS_PARADOJA,
    DATOS_Y_CAFE,
    EDIT_TYPE_PROFILES,
    _DYC_FONT_CANDIDATES,
)
from src.core import subtitles as S  # noqa: E402

_FAIL = []
_PASS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _PASS
    if cond:
        _PASS += 1
        print(f"  ok  {name}")
    else:
        _FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


# ---------------------------------------------------------------------------
# 1. Perfiles de edicion
# ---------------------------------------------------------------------------
def test_edit_type_names() -> None:
    print("[edit-type-names]")
    names = get_edit_type_names()
    check("2 tipos de edicion", len(names) == 2)
    check("Nexus Paradoja presente", "Nexus Paradoja" in names)
    check("Datos Y Cafe presente", "Datos Y Cafe" in names)


def test_nexus_profile() -> None:
    print("[nexus-profile]")
    p = NEXUS_PARADOJA
    check("nombre", p.name == "Nexus Paradoja")
    check("suffix proyecto", p.project_name_suffix == "Nexus Paradoja video")
    check("watermark text", p.watermark_text == "NEXUS PARADOJA")
    check("watermark size 8", abs(p.watermark_font_size - 8.0) < 1e-9)
    check("watermark alpha 0.15", abs(p.watermark_alpha - 0.15) < 1e-9)
    check("watermark X -0.571875", abs(p.watermark_pos_x_json - (-1098 / 1920)) < 1e-9)
    check("watermark Y 0.8296", abs(p.watermark_pos_y_json - (896 / 1080)) < 1e-9)
    check("subtitle Y -0.8333", abs(p.subtitle_pos_y_json - (-900 / 1080)) < 1e-9)
    check("transitions ON", p.enable_transitions is True)
    check("color grading ON", p.enable_color_grading is True)
    check("HSL ON", p.enable_hsl is True)
    check("paneos ON", p.enable_paneos is True)
    check("shake ON", p.enable_camera_shake is True)
    check("SFX ON", p.enable_sfx is True)
    check("imagina ON", p.enable_imagina_esto is True)


def test_dyc_profile() -> None:
    print("[dyc-profile]")
    p = DATOS_Y_CAFE
    check("nombre", p.name == "Datos Y Cafe")
    check("suffix proyecto", p.project_name_suffix == "Datos Y Cafe Video #")
    check("watermark text", p.watermark_text == "DATOS Y CAFE")
    check("watermark size 15", abs(p.watermark_font_size - 15.0) < 1e-9)
    check("watermark alpha 0.1", abs(p.watermark_alpha - 0.1) < 1e-9)
    check("watermark X centro", abs(p.watermark_pos_x_json - 0.0) < 1e-9)
    check("watermark Y centro", abs(p.watermark_pos_y_json - 0.0) < 1e-9)
    check("watermark letter_spacing 0.10", abs(p.watermark_letter_spacing_json - 0.10) < 1e-9)
    # Estilos propios de DYC (v1.6.0): distintos a Nexus
    check("DYC subtitle Y=-775/1080", abs(p.subtitle_pos_y_json - (-775 / 1080)) < 1e-6)
    check("DYC subtitle font_size=11", abs(p.subtitle_font_size - 11.0) < 1e-9)
    check("DYC subtitle stroke = 0.06", abs(p.subtitle_stroke_width_json - 0.06) < 1e-6)
    check("DYC usa fuentes gruesas", p.subtitle_font_candidates == _DYC_FONT_CANDIDATES)
    # v1.7.0: todas las features avanzadas ACTIVADAS
    check("transitions ON", p.enable_transitions is True)
    check("color grading ON", p.enable_color_grading is True)
    check("HSL ON", p.enable_hsl is True)
    check("paneos ON", p.enable_paneos is True)
    check("shake ON", p.enable_camera_shake is True)
    check("SFX ON", p.enable_sfx is True)
    check("imagina OFF", p.enable_imagina_esto is False)
    # Zoom lento DYC: 100% → 105%
    check("zoom_end_min 1.00", abs(p.zoom_end_min - 1.00) < 1e-9)
    check("zoom_end_max 1.10", abs(p.zoom_end_max - 1.10) < 1e-9)
    # Paneos sutiles DYC
    check("pan_ratio 0.5", abs(p.pan_ratio - 0.5) < 1e-9)
    check("pan_amplitude (0.02, 0.04)", p.pan_amplitude == (0.02, 0.04))
    # Shake DYC
    check("shake_ratio 0.10", abs(p.shake_ratio - 0.10) < 1e-9)
    check("shake_amplitude (0.05, 0.10)", p.shake_amplitude == (0.05, 0.10))
    check("shake_zoom_boost 1.03", abs(p.shake_zoom_boost - 1.03) < 1e-9)
    # Fade in 0.2s
    check("fade_in_duration_us 200_000", p.fade_in_duration_us == 200_000)
    # Transiciones DYC (28 con effect_ids, nombres vacíos)
    check("transition_names 0 (usa effect_ids)", len(p.transition_names) == 0)
    check("transition_ratio 1.0", abs(p.transition_ratio - 1.0) < 1e-9)
    # Color grading DYC — valores None (usa materials.effects)
    check("grading_contrast None", p.grading_contrast is None)
    check("grading_shadows None", p.grading_shadows is None)
    check("grading_brightness None", p.grading_brightness is None)
    # HSL selectivo DYC — ahora en dyc_hsl_channels (hsl_channels legacy vacio)
    check("hsl_channels vacio (legacy)", len(p.hsl_channels) == 0)
    check("dyc_hsl_channels 2", len(p.dyc_hsl_channels) == 2)
    check("dyc_hsl[0] Rojo type=1", p.dyc_hsl_channels[0]["hsl_color_type"] == 1)
    check("dyc_hsl[1] Amarillo type=3", p.dyc_hsl_channels[1]["hsl_color_type"] == 3)
    # Viñeta
    check("vignette_intensity 0.0", abs(p.vignette_intensity - 0.0) < 1e-9)
    # Glow en keywords
    check("glow_keywords False", p.glow_keywords is False)
    # Overlays
    check("grid_overlay_enabled False", p.grid_overlay_enabled is False)
    check("neon_text_enabled False", p.neon_text_enabled is False)
    # Audio
    check("bgm_volume_db -12.0", abs(p.bgm_volume_db - (-12.0)) < 1e-9)
    check("ducking_depth_db -5.0", abs(p.ducking_depth_db - (-5.0)) < 1e-9)
    check("ducking_active True", p.ducking_active is True)
    # v1.7.0 — nuevos campos de assets DYC
    check("dyc_assets_dir None (por defecto)", p.dyc_assets_dir is None)
    check("dyc_start_animations 3 opciones", len(p.dyc_start_animations) == 3)
    check("dyc_end_animation no nulo", p.dyc_end_animation is not None)
    check("dyc_color_effects 7 entries", len(p.dyc_color_effects) == 7)
    check("dyc_hsl_channels 2 entries", len(p.dyc_hsl_channels) == 2)


def test_get_edit_profile() -> None:
    print("[get-edit-profile]")
    p1 = get_edit_profile("Nexus Paradoja")
    check("get Nexus", p1 is NEXUS_PARADOJA)
    p2 = get_edit_profile("Datos Y Cafe")
    check("get DYC", p2 is DATOS_Y_CAFE)
    try:
        get_edit_profile("Inexistente")
        check("error tipo invalido", False, "no lanzo exception")
    except ValueError:
        check("error tipo invalido", True)


# ---------------------------------------------------------------------------
# 2. UI — dropdown y persistencia
# ---------------------------------------------------------------------------
def test_ui_defaults() -> None:
    print("[ui-defaults]")
    # No importamos main_window directamente porque requiere PIL.
    # Verificamos los valores desde edit_types que es lo que usa main_window.
    from src.core.edit_types import get_edit_type_names, get_edit_profile
    names = get_edit_type_names()
    check("EDIT_TYPES 2 opciones", len(names) == 2)
    check("EDIT_TYPES contiene Nexus", "Nexus Paradoja" in names)
    check("EDIT_TYPES contiene DYC", "Datos Y Cafe" in names)
    default_name = get_edit_profile(names[0]).project_name_suffix
    check("default name Nexus", default_name == "Nexus Paradoja video")


def test_persistence() -> None:
    print("[persistence]")
    had_file = config.USER_CONFIG_FILE.exists()
    original = config.USER_CONFIG_FILE.read_text(encoding="utf-8") if had_file else None
    try:
        # Simular que el usuario eligio Datos Y Cafe
        save_user_config({"last_edit_type": "Datos Y Cafe"})
        cfg = config.load_user_config()
        check("persist last_edit_type DYC", cfg.get("last_edit_type") == "Datos Y Cafe")

        # Simular Nexus Paradoja
        save_user_config({"last_edit_type": "Nexus Paradoja"})
        cfg = config.load_user_config()
        check("persist last_edit_type Nexus", cfg.get("last_edit_type") == "Nexus Paradoja")

        # Sin clave: debe usar default
        save_user_config({})
        cfg = config.load_user_config()
        check("default last_edit_type vacio", cfg.get("last_edit_type") == "")
    finally:
        if had_file and original is not None:
            config.USER_CONFIG_FILE.write_text(original, encoding="utf-8")
        elif had_file:
            config.USER_CONFIG_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 3. Subtítulos parametrizados
# ---------------------------------------------------------------------------
def test_subtitle_profile_dyc() -> None:
    print("[subtitle-dyc]")
    work = Path(tempfile.mkdtemp(prefix="capcutauto_dyctest_"))
    srt = work / "test.srt"
    srt.write_text(
        "1\n00:00:00,100 --> 00:00:01,500\nHola mundo prueba\n\n"
        "2\n00:00:01,600 --> 00:00:03,000\nSegundo fragmento texto\n\n",
        encoding="utf-8",
    )

    track, materials, segments = S.build_subtitle_track(srt, profile=DATOS_Y_CAFE)
    check("DYC: track no nulo", track is not None)
    check("DYC: 2 materiales", len(materials) == 2)
    check("DYC: 2 segmentos", len(segments) == 2)

    # Verificar posicion Y (DYC usa -775/1080)
    ys = [seg["clip"]["transform"]["y"] for seg in segments]
    check("DYC: Y=-775/1080", all(abs(y - (-775 / 1080)) < 1e-6 for y in ys))

    # Verificar fuente y stroke
    for mat in materials:
        check("DYC: font_size=11", abs(mat["font_size"] - 11.0) < 1e-9)
        check("DYC: border_width=0.06", abs(mat["border_width"] - 0.06) < 1e-6)

    # Verificar contenido: texto en MAYUSCULAS
    for mat in materials:
        content = json.loads(mat["content"])
        check("DYC: texto en MAYUSCULAS", content["text"] == content["text"].upper())


def test_subtitle_profile_nexus() -> None:
    print("[subtitle-nexus]")
    work = Path(tempfile.mkdtemp(prefix="capcutauto_nexustest_"))
    srt = work / "test.srt"
    srt.write_text(
        "1\n00:00:00,100 --> 00:00:01,500\nHola mundo prueba\n\n",
        encoding="utf-8",
    )

    track, materials, segments = S.build_subtitle_track(srt, profile=NEXUS_PARADOJA)
    check("Nexus: track no nulo", track is not None)

    # Posicion Y de Nexus
    ys = [seg["clip"]["transform"]["y"] for seg in segments]
    check("Nexus: Y=-900/1080", all(abs(y - (-900 / 1080)) < 1e-9 for y in ys))

    # Sin profile: comportamiento por defecto (Nexus)
    track2, mats2, segs2 = S.build_subtitle_track(srt)
    ys2 = [seg["clip"]["transform"]["y"] for seg in segs2]
    check("Nexus default: Y=-900/1080", all(abs(y - (-900 / 1080)) < 1e-9 for y in ys2))


# ---------------------------------------------------------------------------
# 4. Watermark parametrizado
# ---------------------------------------------------------------------------
def test_watermark_profile_dyc() -> None:
    print("[watermark-dyc]")
    dur = 3_000_000  # 3s
    mat, track = S.build_watermark_material_and_track(
        DATOS_Y_CAFE.watermark_text, track_render_index=2, duration_us=dur, profile=DATOS_Y_CAFE)

    content = json.loads(mat["content"])
    check("DYC wm: texto DATOS Y CAFE", content["text"] == "DATOS Y CAFE")
    check("DYC wm: font_size 15", abs(mat["font_size"] - 15.0) < 1e-9)
    check("DYC wm: global_alpha 0.1", abs(mat["global_alpha"] - 0.1) < 1e-9)
    check("DYC wm: letter_spacing 0.10", abs(mat["letter_spacing"] - 0.10) < 1e-9)

    seg = track["segments"][0]
    check("DYC wm: X=0 (centro)", abs(seg["clip"]["transform"]["x"] - 0.0) < 1e-9)
    check("DYC wm: Y=0 (centro)", abs(seg["clip"]["transform"]["y"] - 0.0) < 1e-9)
    check("DYC wm: dura todo el audio",
          seg["target_timerange"]["duration"] == dur)


def test_watermark_profile_nexus() -> None:
    print("[watermark-nexus]")
    dur = 3_000_000
    mat, track = S.build_watermark_material_and_track(
        NEXUS_PARADOJA.watermark_text, track_render_index=2, duration_us=dur, profile=NEXUS_PARADOJA)

    content = json.loads(mat["content"])
    check("Nexus wm: texto NEXUS PARADOJA", content["text"] == "NEXUS PARADOJA")
    check("Nexus wm: font_size 8", abs(mat["font_size"] - 8.0) < 1e-9)
    check("Nexus wm: global_alpha 0.15", abs(mat["global_alpha"] - 0.15) < 1e-9)

    seg = track["segments"][0]
    expected_x = -1098 / 1920
    expected_y = 896 / 1080
    check("Nexus wm: X=-1098/1920", abs(seg["clip"]["transform"]["x"] - expected_x) < 1e-9)
    check("Nexus wm: Y=896/1080", abs(seg["clip"]["transform"]["y"] - expected_y) < 1e-9)


# ---------------------------------------------------------------------------
# 5. Deteccion de videos
# ---------------------------------------------------------------------------
def test_video_detection() -> None:
    print("[video-detection]")
    from src.core.auto_detect import detect_video_inputs
    from src.core import config as cfg
    check("VIDEO_EXTENSIONS no vacio", len(cfg.VIDEO_EXTENSIONS) > 0)
    check(".mp4 en VIDEO_EXTENSIONS", ".mp4" in cfg.VIDEO_EXTENSIONS)
    check(".jpg NO en VIDEO_EXTENSIONS", ".jpg" not in cfg.VIDEO_EXTENSIONS)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    config.ensure_dirs()
    tests = [
        test_edit_type_names,
        test_nexus_profile,
        test_dyc_profile,
        test_get_edit_profile,
        test_ui_defaults,
        test_persistence,
        test_subtitle_profile_dyc,
        test_subtitle_profile_nexus,
        test_watermark_profile_dyc,
        test_watermark_profile_nexus,
        test_video_detection,
    ]
    for fn in tests:
        fn()

    print(f"\nRESULTADO: {_PASS} checks ok, {len(_FAIL)} fallos.")
    if _FAIL:
        print("FALLOS:", ", ".join(_FAIL))
        sys.exit(1)
    print("EDIT_TYPES_OK")


if __name__ == "__main__":
    main()
