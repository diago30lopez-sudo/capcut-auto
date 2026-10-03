"""Perfiles de tipos de edicion para CapCut Auto.

Cada tipo de edicion define un conjunto de valores que controlan:
- Nombre por defecto del proyecto.
- Estetica del watermark (texto, fuente, tamano, opacidad, posicion).
- Estetica de los subtítulos (fuente, color, stroke, Y, keywords).
- Feature flags (transiciones, color grading, HSL, paneos, shake, SFX, imagina).
- Parametros avanzados de animacion (zoom, paneos, shake, fade in).
- Parametros de color (grading, HSL, viñeta, glow).
- Overlays (cuadrícula, textos neón).
- Assets de audio (SFX, BGM, ducking).

El pipeline lee el perfil seleccionado y aplica solo lo que corresponde,
sin duplicar codigo.
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Rutas de assets (placeholders — se rellenan cuando existan los archivos)
# ---------------------------------------------------------------------------
_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
SFX_DIR = _ASSETS_DIR / "sfx"
BGM_DIR = _ASSETS_DIR / "bgm"
OVERLAY_DIR = _ASSETS_DIR / "overlays"


@dataclass(frozen=True)
class EditProfile:
    """Perfil de un tipo de edicion. Los campos son inmutables tras crearse."""
    name: str
    project_name_suffix: str  # ej: "Nexus Paradoja video" o "Datos Y Cafe Video #"
    watermark_text: str
    watermark_font_size: float
    watermark_alpha: float       # global_alpha (0.0-1.0)
    watermark_pos_x_json: float  # JSON (UI / CANVAS_WIDTH)
    watermark_pos_y_json: float  # JSON (UI / CANVAS_HEIGHT)
    watermark_bold: bool
    watermark_italic: bool
    watermark_letter_spacing_json: float  # UI letter_spacing * 0.05
    subtitle_font_candidates: tuple[Path, ...]
    subtitle_font_size: float
    subtitle_color: list[float]       # RGB [0..1]
    subtitle_keyword_color: list[float]  # RGB [0..1]
    subtitle_stroke_width_json: float  # JSON (= UI / 500)
    subtitle_pos_y_json: float        # JSON (= UI_Y / CANVAS_HEIGHT)
    subtitle_popup: bool
    subtitle_uppercase: bool
    subtitle_max_words_per_line: int
    subtitle_keywords: frozenset[str]
    # Flags avanzados
    enable_transitions: bool
    enable_color_grading: bool
    enable_hsl: bool
    enable_paneos: bool
    enable_camera_shake: bool
    enable_sfx: bool
    enable_imagina_esto: bool
    # Zoom (multiplicador final respecto a cover_scale)
    zoom_end_min: float   # 1.00 = sin zoom, 1.05 = 5% zoom lento
    zoom_end_max: float   # 1.10 = 10% zoom, 1.15 = 15% zoom
    # Paneos
    pan_ratio: float           # % de escenas con paneo
    pan_amplitude: tuple[float, float]  # rango de deriva (X, Y) en [-1,1]
    # Shake
    shake_ratio: float         # % de escenas con shake
    shake_amplitude: tuple[float, float]  # rango de amplitud
    shake_zoom_boost: float    # overscan desde t=0 para shake
    # Fade in
    fade_in_duration_us: int   # 0 = sin fade in; 200_000 = 0.2s
    # Transiciones (lista de nombres; los IDs se resuelven en CapCut)
    transition_names: tuple[str, ...]
    transition_ratio: float    # % de bordes con transición
    # Color grading (valores fijos por canal; None = sin grading)
    grading_contrast: float | None    # -1..1 (UI /100)
    grading_shadows: float | None     # -1..1
    grading_brightness: float | None  # -1..1
    # HSL por canal: (hsl_color_type, saturation_delta, lightness_delta)
    hsl_channels: list[dict]           # [] = sin HSL
    # Viñeta (0.0 = sin viñeta, 0.10-0.25 = intensidad)
    vignette_intensity: float
    # Glow en keywords de subtítulos
    glow_keywords: bool
    # Overlays
    grid_overlay_enabled: bool
    grid_overlay_keywords: tuple[str, ...]  # palabras que activan la cuadrícula
    neon_text_enabled: bool
    # Audio
    sfx_dir: str | None          # ruta a carpeta de SFX
    bgm_dir: str | None          # ruta a carpeta de BGM
    bgm_volume_db: float         # volumen BGM en dB (-12 ≈ 0.25 linear)
    ducking_depth_db: float      # quanto baja la musica durante VO (-5 dB)
    ducking_active: bool         # True = aplicar ducking con keyframes
    # v1.7.0 — Assets de Datos Y Cafe
    dyc_assets_dir: str | None   # ruta a carpeta de assets (suscríbete, pantalla final, audios)
    dyc_start_animations: tuple[dict, ...]  # 1 de 3 animaciones de entrada
    dyc_end_animation: dict | None          # agujero negro (out) al final
    dyc_color_effects: tuple[dict, ...]     # 7 entries de materials.effects
    dyc_hsl_channels: tuple[dict, ...]      # 2 entries de materials.hsl
    dyc_subtitle_font: str                 # nombre de fuente para subtítulos DYC
    dyc_subtitle_font_resource_id: str | None  # resource_id (None = usar fallback)


# ---------------------------------------------------------------------------
# Nexus Paradoja — valores actuales (sin cambios)
# ---------------------------------------------------------------------------
_NEXUS_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/Montserrat-SemiBold.ttf"),
    Path("C:/Windows/Fonts/BebasNeue-Regular.ttf"),
    Path("C:/Windows/Fonts/impact.ttf"),
)

# Pool de transiciones cinematicas existentes (IDs reales de CapCut).
_NEXUS_TRANSITIONS = (
    "Estiramiento a la izquierda",
    "Abajo",
    "Abajo a la izquierda",
    "Arriba a la derecha",
    "Abajo a la derecha",
    "Abajo a la izquierda II",
    "Abajo II",
    "Cross Dissolve (Dissolve)",
    "Fade to Black (Black Fade)",
    "Light Leaks (Light Sweep II)",
    "Whip Pan (Barrido con inclinación)",
)

# ---------------------------------------------------------------------------
# v1.7.0 — Fuente de subtitulos DYC (datos confirmados desde draft de referencia)
# ---------------------------------------------------------------------------
DYC_SUBTITLE_FONT = "Bungee-Rg"
DYC_SUBTITLE_FONT_RESOURCE_ID = 7533527101870214401
DYC_SUBTITLE_FONT_PATH = (
    f"C:/Users/{getpass.getuser()}/AppData/Local/CapCut/User Data/Cache/"
    f"effect/7533527101870214401/ba7ae66db1b86e6a3696c6831e3fe07e/font.ttf"
)

# ---------------------------------------------------------------------------
# v1.7.0 — Subconjunto GLITCH: transicion entre la ULTIMA IMAGEN y el clip
# "Pantalla final.mp4". Se elige SIEMPRE al azar solo de aqui.
# (effect_id, name, duration_us, is_overlap)
# ---------------------------------------------------------------------------
DYC_GLITCH_TRANSITIONS = (
    ("7595248214505164037", "Error distópico",        1466666, True),
    ("6724239785205961228", "Error de color",           466666, True),
    ("7651580719034125589", "Cortes de señal",        1000000, True),
    ("6725771847444468236", "Falla",                    466666, True),
    ("7674809212127481095", "Glitch lateral",         1000000, True),
    ("7612632016265284871", "Fallo de blanco y negro", 2000000, True),
    ("7514119481837227325", "Píxeles deformados",     2000000, True),
)

NEXUS_PARADOJA = EditProfile(
    name="Nexus Paradoja",
    project_name_suffix="Nexus Paradoja video",
    watermark_text="NEXUS PARADOJA",
    watermark_font_size=8.0,
    watermark_alpha=0.15,
    watermark_pos_x_json=-1098 / 1920,
    watermark_pos_y_json=896 / 1080,
    watermark_bold=True,
    watermark_italic=True,
    watermark_letter_spacing_json=0.10,
    subtitle_font_candidates=_NEXUS_FONT_CANDIDATES,
    subtitle_font_size=12.0,
    subtitle_color=[1.0, 1.0, 1.0],
    subtitle_keyword_color=[1.0, 0.8431373, 0.0],
    subtitle_stroke_width_json=0.06,
    subtitle_pos_y_json=-900 / 1080,
    subtitle_popup=True,
    subtitle_uppercase=True,
    subtitle_max_words_per_line=5,
    subtitle_keywords=frozenset({
        "ataque", "ataca", "golpe", "explos", "bomba", "peligro", "muerte",
        "poder", "poderosa", "invencible", "imposible", "traicion", "secreto",
        "revel", "final", "nunca", "siempre", "guerra", "venganza", "heroe",
        "villano", "salvar", "sacrificio", "memoria", "renacer", "renace",
    }),
    enable_transitions=True,
    enable_color_grading=True,
    enable_hsl=True,
    enable_paneos=True,
    enable_camera_shake=True,
    enable_sfx=True,
    enable_imagina_esto=True,
    # Zoom: 10% o 15% al final (valores Nexus Paradoja)
    zoom_end_min=1.10,
    zoom_end_max=1.15,
    # Paneos
    pan_ratio=0.6,
    pan_amplitude=(0.04, 0.08),
    # Shake
    shake_ratio=1.0,  # siempre en escenas de accion
    shake_amplitude=(0.010, 0.020),
    shake_zoom_boost=1.06,
    # Fade in: ninguno
    fade_in_duration_us=0,
    # Transiciones (pool existente)
    transition_names=_NEXUS_TRANSITIONS,
    transition_ratio=0.98,
    # Color grading (valores del draft real)
    grading_contrast=None,
    grading_shadows=None,
    grading_brightness=None,
    # HSL
    hsl_channels=[
        {"hsl_color_type": 2, "saturation": 0.15, "lightness": 0.05,
         "custom_color": "#FFA227"},   # Naranja
        {"hsl_color_type": 5, "saturation": -0.15, "lightness": -0.10,
         "custom_color": "#00E5FF"},   # Cian
        {"hsl_color_type": 6, "saturation": -0.15, "lightness": -0.10,
         "custom_color": "#2D6BFF"},   # Azul
    ],
    # Viñeta
    vignette_intensity=0.215,
    # Glow
    glow_keywords=False,
    # Overlays
    grid_overlay_enabled=False,
    grid_overlay_keywords=(),
    neon_text_enabled=False,
    # Audio
    sfx_dir=str(SFX_DIR),
    bgm_dir=str(BGM_DIR),
    bgm_volume_db=-20.0,
    ducking_depth_db=-8.0,
    ducking_active=False,
    # v1.7.0 — assets (Nexus no usa estos recursos)
    dyc_assets_dir=None,
    dyc_start_animations=(),
    dyc_end_animation=None,
    dyc_color_effects=(),
    dyc_hsl_channels=(),
    dyc_subtitle_font="Montserrat",
    dyc_subtitle_font_resource_id=None,
)


# ---------------------------------------------------------------------------
# Datos Y Cafe — perfil v1.7.0 (edicion avanzada)
# ---------------------------------------------------------------------------
_DYC_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/Anton-Regular.ttf"),
    Path("C:/Windows/Fonts/BebasNeue-Regular.ttf"),
    Path("C:/Windows/Fonts/TheBoldFont.ttf"),
)

DATOS_Y_CAFE = EditProfile(
    name="Datos Y Cafe",
    project_name_suffix="Datos Y Cafe Video #",
    watermark_text="DATOS Y CAFE",
    watermark_font_size=15.0,
    watermark_alpha=0.1,
    watermark_pos_x_json=0.0,
    watermark_pos_y_json=0.0,
    watermark_bold=True,
    watermark_italic=False,
    watermark_letter_spacing_json=0.10,
    subtitle_font_candidates=_DYC_FONT_CANDIDATES,
    subtitle_font_size=11.0,
    subtitle_color=[1.0, 1.0, 1.0],
    subtitle_keyword_color=[1.0, 0.8313725, 0.0],
    subtitle_stroke_width_json=0.06,
    subtitle_pos_y_json=-775 / 1080,
    subtitle_popup=True,
    subtitle_uppercase=True,
    subtitle_max_words_per_line=5,
    subtitle_keywords=frozenset({
        "ataque", "ataca", "golpe", "explos", "bomba", "peligro", "muerte",
        "poder", "poderosa", "invencible", "imposible", "traicion", "secreto",
        "revel", "final", "nunca", "siempre", "guerra", "venganza", "heroe",
        "villano", "salvar", "sacrificio", "memoria", "renacer", "renace",
    }),
    enable_transitions=True,
    enable_color_grading=True,
    enable_hsl=True,
    enable_paneos=True,
    enable_camera_shake=True,
    enable_sfx=True,
    enable_imagina_esto=False,
    # Zoom 100 → 110
    zoom_end_min=1.00,
    zoom_end_max=1.10,
    # Paneos sutiles: ~50% de escenas, amplitud baja
    pan_ratio=0.5,
    pan_amplitude=(0.02, 0.04),
    # Shake: ~10% de escenas, intensidad baja
    shake_ratio=0.10,
    shake_amplitude=(0.05, 0.10),
    shake_zoom_boost=1.03,
    # Fade in 0.2s
    fade_in_duration_us=200_000,
    # Transiciones DYC (27 con IDs reales; "Elige otro" excluido)
    transition_names=(),
    transition_ratio=1.0,  # todas las transiciones del pool
    # Color grading DYC — 7 entries de materials.effects
    grading_contrast=None,
    grading_shadows=None,
    grading_brightness=None,
    # HSL legacy (DYC usa dyc_hsl_channels en su lugar)
    hsl_channels=[],
    # Viñeta
    vignette_intensity=0.0,
    # Glow en keywords
    glow_keywords=False,
    # Overlays
    grid_overlay_enabled=False,
    grid_overlay_keywords=(),
    neon_text_enabled=False,
    # Audio
    sfx_dir=None,
    bgm_dir=None,
    bgm_volume_db=-12.0,
    ducking_depth_db=-5.0,
    ducking_active=True,
    # v1.7.0 — Assets para Datos Y Cafe
    dyc_assets_dir=None,
    dyc_start_animations=(
        {
            "resource_id": "7575810888108756277",
            "name": "TV retro",
            "duration_us": 2000000,
            "hash": "b3efebc966906cd02d0ad134ba81a47b",
        },
        {
            "resource_id": "7372119524465709569",
            "name": "Rompecabezas",
            "duration_us": 2533333,
            "hash": "4b721a1559eb3451d6cc358468537c49",
        },
        {
            "resource_id": "7522434265225628981",
            "name": "Celular en 3D",
            "duration_us": 2000000,
            "hash": "d20828aeebb4ec698dee4563c80968f2",
        },
    ),
    dyc_end_animation={
        "resource_id": "7294461821170225666",
        "name": "Agujero negro",
        "duration_us": 733333,
        "hash": "18f0daae1bf0b7bb2fbdec2d4a3dbdcd",
    },
    dyc_color_effects=(
        {"type": "contrast", "value": 0.2, "version": "v3"},
        {"type": "saturation", "value": 0.1914285714285715, "version": "v1"},
        {"type": "sharpen", "value": 0.4047619047619048, "version": "v1"},
        {"type": "highlight", "value": 0.0, "version": "v3"},
        {"type": "shadow", "value": -0.2952380952380952, "version": "v3"},
        {"type": "light_sensation", "value": 0.0, "version": ""},
        {"type": "vignetting", "value": 0.3047619047619048, "version": "v1"},
    ),
    dyc_hsl_channels=(
        {
            "hsl_color_type": 1,
            "hue": 0.0,
            "saturation": 15.0,
            "lightness": 10.0,
            "custom_color": "#FFE64444",
        },
        {
            "hsl_color_type": 3,
            "hue": 0.0,
            "saturation": 15.0,
            "lightness": 10.0,
            "custom_color": "#FFF2F224",
        },
    ),
    dyc_subtitle_font="Bungee-Rg",
    dyc_subtitle_font_resource_id="7533527101870214401",
)


# ---------------------------------------------------------------------------
# Registros
# ---------------------------------------------------------------------------
EDIT_TYPE_PROFILES: dict[str, EditProfile] = {
    NEXUS_PARADOJA.name: NEXUS_PARADOJA,
    DATOS_Y_CAFE.name: DATOS_Y_CAFE,
}


def get_edit_profile(name: str) -> EditProfile:
    """Devuelve el perfil correspondiente al nombre de tipo de edicion."""
    profile = EDIT_TYPE_PROFILES.get(name)
    if profile is None:
        raise ValueError(f"Tipo de edicion desconocido: {name!r}")
    return profile


def get_edit_type_names() -> list[str]:
    """Devuelve la lista de nombres disponibles para el dropdown."""
    return list(EDIT_TYPE_PROFILES.keys())
