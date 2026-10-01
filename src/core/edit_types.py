"""Perfiles de tipos de edicion para CapCut Auto.

Cada tipo de edicion define un conjunto de valores que controlan:
- Nombre por defecto del proyecto.
- Estetica del watermark (texto, fuente, tamano, opacidad, posicion).
- Estetica de los subtítulos (fuente, color, stroke, Y, keywords).
- Feature flags (transiciones, color grading, HSL, paneos, shake, SFX, imagina).

El pipeline lee el perfil seleccionado y aplica solo lo que corresponde,
sin duplicar codigo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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
    # TODO v1.6.1: aplicar estilo personalizado Datos Y Cafe (Anton/Bebas Neue,
    #   Y=-775, keywords colores propios, stroke ~4px). Por ahora se usan los
    #   mismos valores que Nexus Paradoja para evitar regresiones.
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
    enable_transitions: bool
    enable_color_grading: bool
    enable_hsl: bool
    enable_paneos: bool
    enable_camera_shake: bool
    enable_sfx: bool
    enable_imagina_esto: bool


# ---------------------------------------------------------------------------
# Nexus Paradoja — valores actuales (sin cambios)
# ---------------------------------------------------------------------------
_NEXUS_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/Montserrat-SemiBold.ttf"),
    Path("C:/Windows/Fonts/BebasNeue-Regular.ttf"),
    Path("C:/Windows/Fonts/impact.ttf"),
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
    watermark_letter_spacing_json=0.10,   # UI "2" * 0.05
    subtitle_font_candidates=_NEXUS_FONT_CANDIDATES,
    subtitle_font_size=12.0,
    subtitle_color=[1.0, 1.0, 1.0],                  # blanco
    subtitle_keyword_color=[1.0, 0.8431373, 0.0],   # amarillo #FFD700
    subtitle_stroke_width_json=0.06,                 # UI 30 / 500
    subtitle_pos_y_json=-900 / 1080,                 # UI -900
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
)


# ---------------------------------------------------------------------------
# Datos Y Cafe — nuevo tipo (v1.6.0)
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
    watermark_alpha=0.5,
    watermark_pos_x_json=0.0,      # X=0 -> centro
    watermark_pos_y_json=0.0,      # Y=0 -> centro
    watermark_bold=True,
    watermark_italic=False,
    watermark_letter_spacing_json=0.10,   # UI "2" * 0.05
    # Estilo de subtítulos: Anton / Bebas Neue / The Bold Font (fallback).
    # Blanco #FFFFFF, contorno negro ~3.5px (UI 17-18 = JSON 0.036),
    # sombra dura, keywords amarillas #FFD400, posicion Y=-775 (UI),
    # pop-up 0.1s, MAYUSCULAS, 2-5 palabras por fragmento.
    subtitle_font_candidates=_DYC_FONT_CANDIDATES,
    subtitle_font_size=15.0,
    subtitle_color=[1.0, 1.0, 1.0],                  # blanco #FFFFFF
    subtitle_keyword_color=[1.0, 0.8313725, 0.0],    # amarillo #FFD400
    subtitle_stroke_width_json=0.036,                # UI ~18 / 500 = ~3.6px
    subtitle_pos_y_json=-775 / 1080,                 # UI -775
    subtitle_popup=True,
    subtitle_uppercase=True,
    subtitle_max_words_per_line=5,
    subtitle_keywords=frozenset({
        "ataque", "ataca", "golpe", "explos", "bomba", "peligro", "muerte",
        "poder", "poderosa", "invencible", "imposible", "traicion", "secreto",
        "revel", "final", "nunca", "siempre", "guerra", "venganza", "heroe",
        "villano", "salvar", "sacrificio", "memoria", "renacer", "renace",
    }),
    enable_transitions=False,
    enable_color_grading=False,
    enable_hsl=False,
    enable_paneos=False,
    enable_camera_shake=False,
    enable_sfx=False,
    enable_imagina_esto=False,
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
