"""Clonado y edicion de un proyecto plantilla de CapCut.

La plantilla del usuario es un esqueleto 100% vacio (tracks: [], materials: []
en draft_content.json y en Timelines/<id>/draft_content.json), asi que no hay
estructura que copiar. Este modulo usa las estructuras canonicas de
capcut_canonical.py (extraidas de un draft real del usuario que SI renderiza)
y adapta ids, rutas, timeranges y duraciones con el contenido generado.

Cambios recientes:
- El proyecto se crea en la carpeta PADRE de la plantilla (junto a ella), no en
  %LOCALAPPDATA%\\CapCut\\...
- Las pistas usan tracks[].segments = [ ... ] (array), como CapCut actual.
- El draft_content.json final es un superconjunto del de la plantilla: se hace
  deep-copy del original y solo se sobreescriben los campos que cambian.
- Se escribe el mismo contenido en la RAIZ y en Timelines/<timeline_id>/.
- Guardia anti-tests: nombres con prefijo Test/Smoke/Autosync/Tmp/_test solo
  con allow_test_names=True. Ademas, si el JSON resultante queda sin pistas o
  segmentos, se borra el proyecto y se lanza error.
- Escala 'cover' por imagen (cubre el lienzo sin deformar) + zoom final
  aleatorio x1.10/x1.15 vía keyframes reales (common_keyframes), RELATIVOS a
  clip.scale (primer keyframe = 1.0), como el draft real 0921.
- FASE 3: color grading avanzado (10 parámetros "Basic colour" de la guía,
  KFType confirmados en la DLL), paneos Ken Burns (KFTypePositionX/Y), camera
  shake 0.2s en escenas con palabras de acción, y HSL por canal
  (materials.hsl + enable_hsl + extra_material_refs, mecanismo del draft real).
- Si la suma de duraciones de las imágenes es menor que el audio total, el
  excedente se reparte proporcionalmente entre TODAS las imágenes (nunca se
  estira la última) para terminar a la vez con el audio.
"""

from __future__ import annotations

import copy
import dataclasses
import getpass
import json
import logging
import random
import shutil
import struct
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image

from src.core import capcut_canonical as canonical
from src.core import config
from src.core.edit_types import EditProfile, NEXUS_PARADOJA
from src.core.imagina_esto import aplicar, ImaginaEstoError
from src.core.subtitles import (
    SUBTITLE_KEYWORDS,
    build_subtitle_track,
    build_watermark_material_and_track,
)
from src.core.timeline_builder import (
    DYC_CHROMA_INTENSITY,
    GenerationCancelled,
    TimelineItem,
    measure_audio_duration_us,
    redistribute_gap,
    get_last_srt_end_us,
    filter_dyc_transitions,
    pick_dyc_glitch_transition,
    pick_dyc_transition,
    sync_last_item_to_audio_end,
)

log = logging.getLogger("capcutauto")

CONTENT_JSON = "draft_content.json"
META_JSON = "draft_meta_info.json"

# Prefijos reservados: un proyecto con estos prefijos solo se genera en tests.
TEST_NAME_PREFIXES = ("test", "smoke", "autosync", "tmp", "_test")

# Multiplicadores de zoom al final de cada imagen (nunca valores intermedios).
ZOOM_END_OPTIONS = (1.10, 1.15)
# Canvas por defecto si la plantilla no declara canvas_config.
CANVAS_FALLBACK = (1920, 1080)

# Transiciones REALES extraídas del draft 0921 (el que sí renderiza):
# (effect_id, nombre, subcarpeta de caché, duración_us, is_overlap, third_resource_id)
TRANSITIONS = (
    ("7620344224734629138", "Estiramiento a la izquierda",
     "11a4f53df0e49e1ce7a5736a7ccac0c2", 1333333, True, "0"),
    ("6724227330190873100", "Abajo",
     "a61ca47476e8bdcde0a2cfc229b264cd", 466666, False, "6724227330190873100"),
    ("6724230577211314695", "Abajo a la izquierda",
     "c76650d4ea9bc4e3b0530c9b9f05f28e", 466666, False, "6724230577211314695"),
    ("6724227870559834635", "Arriba a la derecha",
     "f64b7fb5d42576af0bd47958d18d9ebe", 466666, False, "6724227870559834635"),
    ("6724228621742903815", "Abajo a la derecha",
     "4689db416f0f78ae5530a9bc08d09b1d", 466666, False, "6724228621742903815"),
    ("7291513615989871105", "Abajo a la izquierda II",
     "e0296196f0ec6666a33b33fead4f63d6", 666666, True, "7291513615989871105"),
    # Variación sutil del estilo "Abajo" para que no se sienta repetitivo.
    ("6724849276100284942", "Abajo II",
     "9c042543d4846e7c17e8f950ce6f91c2", 466667, False, "6724849276100284942"),
    # FASE 1 — transiciones cinematográficas añadidas al pool de aleatoriedad.
    # IDs/md5 verificados contra el catálogo de capcut-cli (reenzander030)
    # enums.json: CapCut namespace, 116 transiciones reales, todas libres
    # (is_vip=false). CapCut descarga el efecto por resource_id si no está en
    # la caché local (mismo mecanismo con el que se pobló la caché del 0921).
    ("6724846004274729480", "Cross Dissolve (Dissolve)",
     "986161b2af25f7aa752278aa8b39c7b7", 466666, False, "0"),
    ("6724239388189921806", "Fade to Black (Black Fade)",
     "3bca53e9f3dfa2c184fbee96438ea097", 466666, False, "0"),
    # "Light Leaks" no existe como transición en el catálogo (es scene effect);
    # la opción libre más cinematográfica de estética "luz cruzando el corte".
    ("7224393850444321282", "Light Leaks (Light Sweep II)",
     "1941195d514a2078634b4132f1127f7d", 800000, True, "0"),
    # Whip Pan = "Barrido con inclinación" (del propio draft 0921, Y va en la
    # caché local con de137f0ce9570fe6fff0baa55cb3ab05).
    ("7563310372044983557", "Whip Pan (Barrido con inclinación)",
     "de137f0ce9570fe6fff0baa55cb3ab05", 1000000, True, "0"),
)
# Porcentaje de bordes con transición (el resto queda como corte limpio).
TRANSITION_RATIO = 0.98

# ---------------------------------------------------------------------------
# v1.7.0 — Pool de 28 transiciones DYC con effect_id reales.
# El hash se deja vacío; CapCut resuelve por resource_id al abrir.
# is_overlap=true para todas (requerido para que se vean en preview).
# ---------------------------------------------------------------------------
_DYC_TRANSITIONS = (
    ("7563293278083403013", "Parpadeo espeluznante",           2000000, True),
    ("7549111468348673341", "Parpadeo invertido",              2000000, True),
    ("7569892679333530898", "Eco de parpadeo",                 2000000, True),
    ("7656729516693310741", "Corte de escena",                  466666,  True),
    ("7514119481837227325", "Píxeles deformados",              2000000, True),
    ("7627056546643545365", "Choque invertido en blanco y negro", 1066666, True),
    ("7595248214505164037", "Error distópico",                 1466666, True),
    ("6724239785205961228", "Error de color",                   466666,  True),
    ("7651580719034125589", "Cortes de señal",                 1000000, True),
    ("6725771847444468236", "Falla",                            466666,  True),
    ("7674809212127481095", "Glitch lateral",                  1000000, True),
    ("7612632016265284871", "Fallo de blanco y negro",          2000000, True),
    ("7488157742956350737", "Deslizamiento con zoom",           1000000, True),
    ("7666004747580673301", "Zoom falso",                      2000000, True),
    ("7612088207236189458", "Zoom hiperdistorsionado",          1066666, True),
    ("7612555794336288016", "Neón estroboscópico",             2000000, True),
    ("7687933150131080466", "Estrobo láser",                   2000000, True),
    ("7245192723077009921", "Estroboscopio II",                 400000,  True),
    ("7248940490211463681", "Estroboscopio en blanco y negro",  600000,  True),
    ("7622957889271024901", "Secuencia en blanco y negro",     2000000, True),
    ("7618337228942707973", "Apertura con rasgado",            1933333, True),
    ("7617043237525523730", "Rasgado grunge",                  2000000, True),
    ("6886275127743353346", "Humo oscuro",                      466666,  True),
    ("7563262619713326389", "Sorpresa de sangre",              1266666, True),
    ("7607661645040553234", "Barrido ardiente",                1533333, True),
    ("7682968334454852865", "Escaneo de haz",                  2000000, True),
    ("7584014501696081153", "Pulso fragmentado",               2000000, True),
)

# ---------------------------------------------------------------------------
# El subconjunto GLITCH del corte final vive en edit_types.DYC_GLITCH_TRANSITIONS
# y se elige con timeline_builder.pick_dyc_glitch_transition().
# ---------------------------------------------------------------------------

# FASE 1 — audio SIEMPRE a exactamente 6.0 dB. CapCut guarda el volumen de forma
# LINEAL (1.0 = 0 dB, valores >1 amplifican), así que 6 dB = 10^(6/20) ≈ 1.9953.
AUDIO_GAIN_DB = 6.0
AUDIO_GAIN_LINEAR = 10 ** (AUDIO_GAIN_DB / 20)

# FASE 1 — color grading por imagen vía los "Basic colour" del Ajustar de
# CapCut: common_keyframes de un solo keyframe estático (valor constante),
# igual que el zoom ya usa. Rango normalizado -1..1 = %/100 (mismo convenio que
# el draft real 0921: KFTypeContrast 0.12 ≈ +12%). Si CapCut ignorara alguno a
# la hora de renderizar, no rompe la sintaxis del JSON ni el popup; el resto
# del color sigue aplicándose.
COLOR_GRADE_ENABLED = True

# FASE 3 — color grading AVANZADO según la guía (Plotinary): 10 parámetros,
# todos confirmados en lyra_cli_client.dll de la app instalada. Valores fijos
# = centro del rango de la guía; el dict COLOR_GRADE_RANGES aleatoriza el valor
# por escena (mismo convenio /100: Brillo -5..-8 → -0.05..-0.08, etc.).
#   Brillo, Exposición, Sombras, Temperatura y Matiz tocan TODA la imagen.
#   "Exposición" de la app = "光感/Light Sensation" → KFTypeLightSensatione
#   (no existe KFTypeExposure). "Matiz" = KFTypeHue (no existe KFTypeTint).
COLOR_GRADE = (
    ("KFTypeBrightness", -0.065),     # Brillo -5 a -8
    ("KFTypeContrast", 0.175),        # Contraste +15 a +20
    ("KFTypeLightSensatione", -0.05), # Exposición -5
    ("KFTypeSaturation", -0.10),      # Saturación -8 a -12
    ("KFTypeSharpen", 0.30),          # Enfocar +25 a +35
    ("KFTypeHightLight", 0.10),       # Destacados +10 (typo oficial de la app)
    ("KFTypeShadow", -0.10),          # Sombras -10
    ("KFTypeTemperature", -0.05),     # Temperatura -5
    ("KFTypeHue", 0.03),              # Matiz +2 a +4
    ("KFTypeVignetting", 0.215),      # Viñeta +18 a +25
)
COLOR_GRADE_RANGES = {
    "KFTypeBrightness": (-0.08, -0.05),
    "KFTypeContrast": (0.15, 0.20),
    "KFTypeSaturation": (-0.12, -0.08),
    "KFTypeSharpen": (0.25, 0.35),
    "KFTypeHue": (0.02, 0.04),
    "KFTypeVignetting": (0.18, 0.25),
}

# FASE 3 — paneos Ken Burns (KFTypePositionX/Y; 0 = centro del lienzo, -1..1).
# La deriva lineal 0 → amp debe quedarse por debajo del overscan que el zoom va
# ganando (0 → ±15%) para no revelar bordes: 0.04..0.08 es seguro.
PAN_RATIO = 0.6                    # % de escenas con paneo (el resto, fijas)
PAN_AMPLITUDE = (0.04, 0.08)

# FASE 3 — camera shake en escenas de ACCIÓN (palabras SUBTITLE_KEYWORDS):
# 0.2s de temblor alternante con decaimiento, extraído del keyframe final de
# paneo. El boost de zoom inicial (SHAKE_ZOOM_BOOST) da overscan desde t=0 para
# que el temblor nunca destape los bordes del lienzo.
SHAKE_DURATION_US = 200_000
SHAKE_STEP_US = 33_000
SHAKE_AMPLITUDE = (0.010, 0.020)
SHAKE_ZOOM_BOOST = 1.06

# FASE 3 — HSL por canal (mecanismo del draft real del usuario: una entrada
# materials.hsl por segmento + enable_hsl:True + extra_material_refs). Canales
# hsl_color_type de CapCut: 1=Rojo 2=Naranja 3=Amarillo 4=Verde 5=Cian 6=Azul
# 7=Púrpura 8=Magenta. La guía pide Naranja (Sat +15/Lum +5) y Azul/Cian
# (Hue -15/Sat +20/Lum -10). El recurso 7501974767453474064 es el de los
# drafts reales del usuario (ya descargado en esta máquina).
HSL_ENABLED = True
HSL_EFFECT_ID = "7501974767453474064"
HSL_EFFECT_HASH = "20cd8db6531c21bf7e4053026d20e395"
HSL_CHANNELS = (
    {"hsl_color_type": 2, "hue": 0.0, "saturation": 0.0, "lightness": 0.0,
     "custom_color": "#FFA227"},    # Naranja
    {"hsl_color_type": 5, "hue": 0.0, "saturation": 0.0, "lightness": 0.0,
     "custom_color": "#00E5FF"},    # Cian
    {"hsl_color_type": 6, "hue": 0.0, "saturation": 0.0, "lightness": 0.0,
     "custom_color": "#2D6BFF"},    # Azul
)

# FASE 3 — Color Grading (Adjust) — efectos de ajuste tipo CapCut.
# Basado en diff real: materials.effects[] con type="saturation"/"temperature"/"tint"
# y value normalizado (-1.0 a 1.0). effect_id = 7501974767453474064 (mismo que HSL).
ADJUST_ENABLED = True
ADJUST_EFFECT_ID = "7501974767453474064"
ADJUST_EFFECT_HASH = "20cd8db6531c21bf7e4053026d20e395"
# Canales de ajuste: saturation, temperature, tint (valores normalizados -1.0 a 1.0)
ADJUST_CHANNELS = (
    {"type": "saturation", "value": 0.15, "custom_color": "#FFFFFF"},   # Saturación +15%
    {"type": "temperature", "value": -0.02, "custom_color": "#FFFFFF"}, # Temperatura -2
    {"type": "tint", "value": 0.01, "custom_color": "#FFFFFF"},         # Tinte +1
)

# FASE 3 — SFX/BGM con ducking según la guía: VO a +6 dB y BGM a -20 dB cuando
# hay BGM (volumen LINEAL de CapCut: 10^(dB/20)). La lógica queda lista; sin un
# archivo/carpeta no se activa (params opcionales de generate()). SFX: sin
# carpeta configurada, se omite con aviso.
BGM_GAIN_DB = -20.0
BGM_GAIN_LINEAR = 10 ** (BGM_GAIN_DB / 20)   # ≈ 0.1
SFX_DURATION_US = 600_000


class CapCutProjectError(Exception):
    pass


def is_test_name(name: str) -> bool:
    """True si el nombre del proyecto coincide con los prefijos reservados a tests."""
    low = (name or "").strip().lower()
    return any(low.startswith(p) for p in TEST_NAME_PREFIXES)


def new_id() -> str:
    """Id unico hexadecimal de 32 chars (formato usado por CapCut)."""
    return uuid.uuid4().hex.upper()


def _now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


def _image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as im:
            return im.width, im.height
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo leer dimensiones de %s (%s); default 1920x1080.", path, exc)
        return 1920, 1080


def _mp4_duration_us(path: Path) -> int | None:
    """Lee la duracion de un .mp4/.mov/.m4v desde el átomo 'mvhd'. Python puro."""
    try:
        with open(path, "rb") as f:
            file_size = f.seek(0, 2)
            f.seek(0)
            moov_offset = None
            while f.tell() < file_size:
                header = f.read(8)
                if len(header) < 8:
                    break
                size = struct.unpack(">I", header[:4])[0]
                atom = header[4:8]
                if size == 1:
                    size = struct.unpack(">Q", f.read(8))[0]
                elif size == 0:
                    size = file_size - f.tell() + 8
                if atom == b"moov":
                    moov_offset = f.tell()
                    moov_size = size
                    break
                f.seek(size - 8, 1)
            if moov_offset is None:
                return None
            f.seek(moov_offset)
            moov_end = moov_offset + moov_size
            while f.tell() < moov_end:
                header = f.read(8)
                if len(header) < 8:
                    return None
                sub_size = struct.unpack(">I", header[:4])[0]
                sub_atom = header[4:8]
                if sub_atom == b"mvhd":
                    version = f.read(1)[0]
                    f.read(3)  # flags
                    if version == 1:
                        f.read(16)  # creation + modif (64-bit each)
                        timescale = struct.unpack(">I", f.read(4))[0]
                        duration = struct.unpack(">Q", f.read(8))[0]
                    else:
                        f.read(8)   # creation + modif (32-bit each)
                        timescale = struct.unpack(">I", f.read(4))[0]
                        duration = struct.unpack(">I", f.read(4))[0]
                    if timescale == 0:
                        return None
                    return int(duration * 1_000_000 / timescale)
                f.seek(sub_size - 8, 1)
    except Exception:  # noqa: BLE001
        return None
    return None


def _video_duration_us(path: Path) -> int | None:
    """Mide la duracion real de un archivo multimedia en microsegundos.

    Metodo 1: parser MP4 en Python puro (átomo mvhd) para .mp4/.mov/.m4v.
    Metodo 2: ffprobe (subprocess) si el binario está disponible.
    Metodo 3: measure_audio_duration_us (WAV/PCM via wave module).
    Devuelve None si no se pudo medir (log WARNING con ruta exacta).
    """
    if not path.is_file():
        log.info("_video_duration_us: no existe %s", path)
        return None

    suffix = path.suffix.lower()
    if suffix in (".mp4", ".mov", ".m4v"):
        dur = _mp4_duration_us(path)
        if dur is not None:
            log.info("Duración medida %s: %.2f s (método: mp4_atom)", path.name, dur / 1_000_000)
            return dur

    # Metodo 2: ffprobe
    import shutil as _shutil
    import subprocess as _subprocess
    ffprobe_bin: str | None = _shutil.which("ffprobe")
    if ffprobe_bin is None:
        _repo = Path(__file__).resolve().parent.parent
        for _candidate in (_repo / "tools" / "ffprobe.exe",
                           _repo / "bin" / "ffprobe.exe"):
            if _candidate.is_file():
                ffprobe_bin = str(_candidate)
                break
        if ffprobe_bin is None:
            _local = Path.home() / "AppData" / "Local" / "CapCut" / "Apps"
            for _app_dir in _local.glob("*"):
                _fp = _app_dir / "ffprobe.exe"
                if _fp.is_file():
                    ffprobe_bin = str(_fp)
                    break
    if ffprobe_bin is not None:
        try:
            result = _subprocess.run(
                [ffprobe_bin, "-v", "error",
                 "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1",
                 str(path)],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                dur_s = float(result.stdout.strip())
                dur = int(round(dur_s * 1_000_000))
                log.info("Duración medida %s: %.2f s (método: ffprobe)", path.name, dur / 1_000_000)
                return dur
        except Exception as exc:  # noqa: BLE001
            log.warning("_video_duration_us: ffprobe fallo para %s (%s)", path, exc)
    else:
        log.info("_video_duration_us: ffprobe no encontrado en PATH ni rutas conocidas")

    # Metodo 3: fallback audio WAV/PCM
    dur = measure_audio_duration_us(path)
    if dur is not None:
        log.info("Duración medida %s: %.2f s (método: audio)", path.name, dur / 1_000_000)
        return dur

    log.warning("DYC %s: no se pudo medir '%s' (existe=%s); se omite.",
                path.name, str(path), path.is_file())
    return None


def _canvas_size(content: dict) -> tuple[int, int]:
    """Dimensiones del lienzo (canvas_config), con fallback 1920x1080."""
    cc = content.get("canvas_config") or {}
    try:
        w = int(cc.get("width") or CANVAS_FALLBACK[0])
        h = int(cc.get("height") or CANVAS_FALLBACK[1])
    except (TypeError, ValueError):
        w, h = CANVAS_FALLBACK
    return w, h


def _cover_scale(canvas_w: int, canvas_h: int, img_w: int, img_h: int) -> float:
    """Escala 'cover' para CapCut: el clip.scale de CapCut se aplica SOBRE el
    ajuste por defecto 'fit' (contain) de la imagen en el lienzo, asi que el
    multiplicador necesario para cubrir el 100% del lienzo sin bandas negras
    (aunque sobre por los lados y se recorte) es la razon entre el factor mas
    exigente ('max') y el que ya cubre CapCut por defecto ('min'). Escala
    uniforme: jamas deforma la imagen."""
    if img_w <= 0 or img_h <= 0:
        return 1.0
    fit_x = canvas_w / img_w
    fit_y = canvas_h / img_h
    if fit_x == fit_y:
        return 1.0
    return max(fit_x, fit_y) / min(fit_x, fit_y)


def _keyframe(t_us: int, value: float) -> dict:
    """Keyframe individual de CapCut (mismo formato que el draft 0921)."""
    return {
        "id": new_id(),
        "curveType": "Line",
        "time_offset": t_us,
        "left_control": {"x": 0.0, "y": 0.0},
        "right_control": {"x": 0.0, "y": 0.0},
        "values": [value],
        "string_value": "",
        "graphID": "",
    }


def _zoom_keyframes(duration_us: int, mult: float, base: float = 1.0) -> list[dict]:
    """Keyframes REALES de CapCut (mismo formato que el draft 0921) para animar
    la escala uniforme. Los valores son ABSOLUTOS en el mismo sistema de
    coordenadas que clip.scale: el primer keyframe arranca EXACTAMENTE en la
    escala base 'cover' (base) y el ultimo llega a base * mult (zoom final del
    10% o 15% calculado SOBRE esa nueva escala base)."""
    return [
        {
            "id": new_id(),
            "material_id": "",
            "property_type": "KFTypeScaleX",
            "keyframe_list": [_keyframe(0, base), _keyframe(duration_us, base * mult)],
        },
        {
            "id": new_id(),
            "material_id": "",
            "property_type": "KFTypeScaleY",
            "keyframe_list": [_keyframe(0, base), _keyframe(duration_us, base * mult)],
        },
    ]


def _fade_in_keyframes(duration_us: int, fade_us: int) -> list[dict]:
    """Keyframes de fade in: alpha de 0.0 a 1.0 en fade_us microsegundos."""
    if fade_us <= 0 or fade_us >= duration_us:
        return []
    return [
        {
            "id": new_id(),
            "material_id": "",
            "property_type": "KFTypeAlpha",
            "keyframe_list": [
                _keyframe(0, 0.0),
                _keyframe(fade_us, 1.0),
                _keyframe(duration_us, 1.0),
            ],
        },
    ]


def _color_keyframes(duration_us: int, profile: EditProfile | None = None) -> list[dict]:
    """Color grading por imagen como keyframes estáticos (un solo keyframe de
    valor constante = ajuste fijo, no animación).

    Para Nexus Paradoja: valores aleatorios por escena dentro de los rangos
    definidos en COLOR_GRADE_RANGES (comportamiento existente).

    Para Datos Y Cafe: valores fijos derivados del perfil
    (grading_contrast, grading_shadows, grading_brightness, vignette_intensity).
    """
    if profile is None:
        profile = NEXUS_PARADOJA  # type: ignore[assignment]

    entries: list[dict] = []

    if not profile.enable_color_grading:
        return entries

    # --- DYC: valores fijos del perfil ---
    if profile.grading_contrast is not None:
        entries.append(
            {
                "id": new_id(),
                "material_id": "",
                "property_type": "KFTypeContrast",
                "keyframe_list": [_keyframe(0, profile.grading_contrast)],
            }
        )
    if profile.grading_shadows is not None:
        entries.append(
            {
                "id": new_id(),
                "material_id": "",
                "property_type": "KFTypeShadow",
                "keyframe_list": [_keyframe(0, profile.grading_shadows)],
            }
        )
    if profile.grading_brightness is not None:
        entries.append(
            {
                "id": new_id(),
                "material_id": "",
                "property_type": "KFTypeBrightness",
                "keyframe_list": [_keyframe(0, profile.grading_brightness)],
            }
        )
    if profile.vignette_intensity > 0:
        entries.append(
            {
                "id": new_id(),
                "material_id": "",
                "property_type": "KFTypeVignetting",
                "keyframe_list": [_keyframe(0, profile.vignette_intensity)],
            }
        )

    # --- Nexus: valores aleatorios (comportamiento existente) ---
    if profile is NEXUS_PARADOJA:
        for property_type, center in COLOR_GRADE:
            lo, hi = COLOR_GRADE_RANGES.get(property_type, (center, center))
            value = round(random.uniform(lo, hi), 3)
            entries.append(
                {
                    "id": new_id(),
                    "material_id": "",
                    "property_type": property_type,
                    "keyframe_list": [_keyframe(0, value)],
                }
            )

    return entries


# --------------------------------------------------------------------------
# FASE 3 — paneos y camera shake (KFTypePositionX/Y)
# --------------------------------------------------------------------------
def _pan_points(duration_us: int, end_x: float, end_y: float) -> list[tuple[int, float, float]]:
    """Paneo Ken Burns: deriva lineal desde el centro (0,0) hasta (end_x,end_y)
    al cierre de la escena, en sincronía con el zoom (ambos crecen lineales;
    la amplitud se mantiene bajo el overscan final ±15% para no destapar bordes)."""
    return [(0, 0.0, 0.0), (duration_us, round(end_x, 4), round(end_y, 4))]


def _shake_points(duration_us: int, amp_x: float, amp_y: float,
                  end_x: float, end_y: float) -> list[tuple[int, float, float]]:
    """Camera shake de 0.2s: keyframes cada ~33ms alternando el signo con
    decaimiento (impacto), cerrando en la deriva final del paneo (end_x,end_y)."""
    limit = min(SHAKE_DURATION_US, duration_us)
    pts: list[tuple[int, float, float]] = []
    sx, sy = 1.0, -1.0
    decay = 1.0
    t = 0
    while t < limit:
        pts.append((t, round(amp_x * sx * decay, 4), round(amp_y * sy * decay, 4)))
        t += SHAKE_STEP_US
        sx, sy = -sx, -sy
        decay *= 0.85
    pts.append((duration_us, round(end_x, 4), round(end_y, 4)))
    return pts


def _position_entries(points: list[tuple[int, float, float]]) -> list[dict]:
    """Convierte la lista (t_us, x, y) en las dos entradas common_keyframes
    KFTypePositionX / KFTypePositionY (mismo formato que el zoom y el color)."""
    if not points:
        return []
    return [
        {
            "id": new_id(),
            "material_id": "",
            "property_type": "KFTypePositionX",
            "keyframe_list": [_keyframe(t, x) for t, x, _ in points],
        },
        {
            "id": new_id(),
            "material_id": "",
            "property_type": "KFTypePositionY",
            "keyframe_list": [_keyframe(t, y) for t, _, y in points],
        },
    ]


def _has_action_keyword(text: str | None) -> bool:
    """True si la frase de la escena contiene alguna palabra de acción/energía
    de la guía (SUBTITLE_KEYWORDS). Estas escenas reciben camera shake."""
    if not text:
        return False
    low = text.lower()
    return any(kw in low for kw in SUBTITLE_KEYWORDS)


# --------------------------------------------------------------------------
# Esquema / muestra (para logs/schema_plantilla.json y schema_plantilla_full.json)
# --------------------------------------------------------------------------
def _describe(value, depth: int = 0, max_depth: int = 3):
    if value is None:
        return {"tipo": "null"}
    if isinstance(value, bool):
        return {"tipo": "bool", "ejemplo": value}
    if isinstance(value, (int, float)):
        return {"tipo": type(value).__name__, "ejemplo": value}
    if isinstance(value, str):
        return {"tipo": "str", "longitud": len(value), "ejemplo": value[:80]}
    if isinstance(value, list):
        d: dict = {"tipo": "list", "longitud": len(value)}
        if value and depth < max_depth:
            d["elemento_0"] = _describe(value[0], depth + 1, max_depth)
        return d
    if isinstance(value, dict):
        if depth >= max_depth:
            return {"tipo": "object", "claves": sorted(value.keys())}
        return {
            "tipo": "object",
            "claves": {k: _describe(v, depth + 1, max_depth) for k, v in value.items()},
        }
    return {"tipo": type(value).__name__}


def _muestra(value, depth: int = 0):
    """Copia sanitizada (listas acotadas, strings acotados) para inspeccion."""
    if isinstance(value, dict):
        return {k: _muestra(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if depth > 3:
            return f"<lista de {len(value)} elementos>"
        body = [_muestra(v, depth + 1) for v in value[:2]]
        if len(value) > 2:
            body.append(f"... ({len(value) - 2} mas)")
        return body
    if isinstance(value, str):
        return value[:120]
    return value


# --------------------------------------------------------------------------
# Proyecto CapCut
# --------------------------------------------------------------------------
class CapCutProject:
    def __init__(self, template_dir: str | Path):
        self.template_dir = Path(template_dir)
        self.content_path = self.template_dir / CONTENT_JSON
        self.meta_path = self.template_dir / META_JSON
        if not self.content_path.is_file():
            raise CapCutProjectError(
                f"La plantilla no contiene {CONTENT_JSON}: {self.template_dir}"
            )
        if not self.meta_path.is_file():
            raise CapCutProjectError(
                f"La plantilla no contiene {META_JSON}: {self.template_dir}"
            )
        self.content = json.loads(self.content_path.read_text(encoding="utf-8"))
        self.meta = json.loads(self.meta_path.read_text(encoding="utf-8"))

    # -- backup + esquema ----------------------------------------------------
    def backup_originals(self) -> Path:
        """Copia los JSON originales de la plantilla a backups/<timestamp>/."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        bak_dir = config.BACKUPS_DIR / stamp
        bak_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.content_path, bak_dir / f"{CONTENT_JSON}.original")
        shutil.copy2(self.meta_path, bak_dir / f"{META_JSON}.original")
        log.info("Backup de la plantilla guardado en %s", bak_dir)
        return bak_dir

    def dump_schema(self) -> Path:
        """Vuelca esquema (profundidad 3) + muestra a logs/schema_plantilla.json."""
        return self.dump_schema_to(config.SCHEMA_FILE, max_depth=3, sample=True)

    def dump_full_schema(self) -> Path:
        """Vuelca esquema COMPLETO (todas las claves, hasta nivel 5) a
        logs/schema_plantilla_full.json."""
        return self.dump_schema_to(config.SCHEMA_FULL_FILE, max_depth=5, sample=False)

    def dump_schema_to(self, target: Path, max_depth: int, sample: bool) -> Path:
        config.ensure_dirs()
        payload = {
            "generado_el": datetime.now().isoformat(timespec="seconds"),
            "plantilla": self.template_dir.name,
            "profundidad_maxima": max_depth,
            "esquema": _describe(self.content, max_depth=max_depth),
        }
        if sample:
            payload["muestra"] = _muestra(self.content)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        log.info("Esquema de la plantilla volcado a %s", target)
        return target

    def _check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            log.info("Generación cancelada por el usuario.")
            shutil.rmtree(self.new_dir, ignore_errors=True)
            raise GenerationCancelled("Generación cancelada por el usuario.")

    # -- helpers de construccion -------------------------------------------------
    def _timeline_id(self, content: dict) -> str | None:
        """Id del timeline raiz = content['id']; el mismo que nombra la carpeta
        Timelines/<id>/ (que CapCut tambien lee)."""
        return content.get("id") or None

    def _build_photo_material(self, content: dict, abs_path: str, width: int,
                              height: int, duration_us: int, name: str) -> dict:
        mat = copy.deepcopy(canonical.PHOTO_MATERIAL)
        mat["id"] = new_id()
        mat["unique_id"] = new_id()
        mat["path"] = abs_path
        mat["duration"] = duration_us
        mat["width"] = width
        mat["height"] = height
        mat["material_name"] = name
        return mat

    def _build_photo_segment(self, content: dict, mat_id: str, start_us: int,
                              duration_us: int, cover_scale: float = 1.0,
                              zoom_mult: float = 1.0, zoom_base: float = 1.0,
                              position_points: list | None = None,
                              enable_hsl: bool = True,
                              enable_adjust: bool = True,
                              extra_refs: list | None = None,
                              fade_in_duration_us: int = 0,
                              profile: EditProfile | None = None,
                              dyc_effect_refs: list | None = None) -> dict:
        seg = copy.deepcopy(canonical.PHOTO_SEGMENT)
        seg["id"] = new_id()
        seg["material_id"] = mat_id
        seg["render_index"] = 0
        seg["track_render_index"] = 0
        seg["source_timerange"] = {"start": 0, "duration": duration_us}
        seg["target_timerange"] = {"start": start_us, "duration": duration_us}
        # ORDEN ESTRICTO DE OPERACIONES:
        # 1. Primero la escala 'cover' como escala base del clip: la imagen
        #    cubre el lienzo sin bordes negros.
        seg["clip"]["scale"] = {"x": cover_scale, "y": cover_scale}
        seg["uniform_scale"] = {"on": True, "value": 1.0}
        # 2. Los keyframes de zoom (aumento) parten EXACTAMENTE de la escala
        #    'cover' de ESTA imagen.
        # 3. Color grading (FASE 3, valores segun perfil).
        # 4. Position (FASE 3): paneo Ken Burns y/o camera shake.
        # 5. Fade in (v1.7.0 DYC): alpha 0.0 → 1.0 al inicio.
        kfs = _zoom_keyframes(duration_us, zoom_mult, base=zoom_base)
        kfs.extend(_color_keyframes(duration_us, profile))
        kfs.extend(_position_entries(position_points))
        kfs.extend(_fade_in_keyframes(duration_us, fade_in_duration_us))
        seg["common_keyframes"] = kfs
        # FASE 3: HSL por canal activado + referencias a materials.hsl.
        # FASE 3 — Color Grading (Adjust): enable_adjust para activar efectos.
        seg["enable_hsl"] = bool(enable_hsl)
        seg["enable_adjust"] = bool(enable_adjust)
        all_refs = list(dyc_effect_refs or []) + list(extra_refs or [])
        seg["extra_material_refs"] = all_refs
        return seg


    def _build_transition_material_from_name(self, name: str) -> dict:
        """Crea un material de transicion a partir SOLO del nombre (para DYC,
        donde los effect_id no se conocen ainda). CapCut resuelve por nombre al
        abrir el proyecto; los campos vacios no rompen la sintaxis del JSON."""
        cache = Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache" / "effect"
        return {
            "id": new_id(),
            "type": "transition",
            "name": name,
            "effect_id": "",
            "resource_id": "",
            "third_resource_id": "0",
            "source_platform": 1,
            "path": "",
            "duration": 300_000,
            "is_overlap": False,
            "platform": "all",
            "category_id": "123456",
            "category_name": "Transiciones",
            "request_id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "is_ai_transition": False,
            "video_path": "",
            "task_id": "",
        }

    def _build_audio_material(self, content: dict, abs_path: str,
                              duration_us: int, name: str) -> dict:
        mat = copy.deepcopy(canonical.AUDIO_MATERIAL)
        mat["id"] = new_id()
        mat["music_id"] = str(uuid.uuid4())
        mat["local_material_id"] = str(uuid.uuid4())
        mat["path"] = abs_path
        mat["duration"] = duration_us
        mat["name"] = name
        return mat

    def _build_audio_segment(self, content: dict, mat_id: str,
                              duration_us: int, track_index: int,
                              volume: float = AUDIO_GAIN_LINEAR,
                              common_keyframes: list[dict] | None = None) -> dict:
        seg = copy.deepcopy(canonical.AUDIO_SEGMENT)
        seg["id"] = new_id()
        seg["material_id"] = mat_id
        seg["render_index"] = 0
        seg["track_render_index"] = track_index
        seg["source_timerange"] = {"start": 0, "duration": duration_us}
        seg["target_timerange"] = {"start": 0, "duration": duration_us}
        # FASE 1: audio SIEMPRE a exactamente 6.0 dB (volumen LINEAL de CapCut:
        # 1.0 = 0 dB, así que 6 dB = 10^(6/20) ≈ 1.9953), tanto en volume como en
        # last_nonzero_volume (el que CapCut restaura si se enmudece el clip).
        # FASE 3: BGM usa el mismo aparato con ducking a -20 dB (volume ≈ 0.1).
        seg["volume"] = volume
        seg["last_nonzero_volume"] = volume
        seg["common_keyframes"] = list(common_keyframes or [])
        return seg

    def _build_transition_material(self, entry: tuple) -> dict:
        """Material de transición con el MISMO formato que el draft 0921.

        La ruta se construye dinámicamente contra la caché local de CapCut
        (efecto ya descargado en este equipo). Las transiciones NO alteran los
        timeranges de los segmentos: solo se referencian desde extra_material_refs
        del segmento que RECIBE el corte, por lo que la sincronización del audio
        y las duraciones de cada escena quedan intactas."""
        effect_id, name, hash_dir, duration_us, is_overlap, third_id = entry
        cache = Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache" / "effect"
        resource_dir = cache / effect_id
        # FASE 1: aviso si el recurso de caché no está descargado aún. CapCut
        # auto-descarga el efecto por resource_id al abrir el proyecto (mismo
        # mecanismo con el que se pobló la caché del 0921); no rompe sintaxis.
        if not resource_dir.is_dir() or not any(resource_dir.iterdir()):
            log.warning(
                "Transición '%s' (%s) no está en la caché local: %s · CapCut la "
                "descargará automáticamente al abrir el proyecto.",
                name, effect_id, resource_dir,
            )
        return {
            "id": new_id(),
            "type": "transition",
            "name": name,
            "effect_id": effect_id,
            "resource_id": effect_id,
            "third_resource_id": third_id,
            "source_platform": 1,
            "path": (cache / effect_id / hash_dir).as_posix(),
            "duration": duration_us,
            "is_overlap": is_overlap,
            "platform": "all",
            "category_id": "123456",
            "category_name": "Transiciones",
            "request_id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "is_ai_transition": False,
            "video_path": "",
            "task_id": "",
        }

    def _hsl_material(self, channel: dict) -> dict:
        """Material HSL por canal, con el MISMO formato que los drafts reales
        del usuario (#1 Nexus Paradoja / Nexus Paradoja video 1). El efecto
        7501974767453474064 ya está descargado en esta máquina (path del draft
        real); CapCut reutiliza esa caché, no descarga nada nuevo.
        IMPORTANTE: hue/saturation/lightness base = 0 (keyframes animan)."""
        effect_path = (
            Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache"
            / "effect" / HSL_EFFECT_ID / HSL_EFFECT_HASH
        ).as_posix()
        return {
            "id": new_id(),
            "unique_id": new_id(),
            "constant_material_id": new_id(),
            "hsl_color_type": channel["hsl_color_type"],
            "hue": 0.0,
            "saturation": 0.0,
            "lightness": 0.0,
            "interacting": True,
            "version": "1",
            "path": effect_path,
            "type": "hsl",
            "lumi_hub_path": effect_path,
            "custom_color": channel["custom_color"],
            "resource_id": "",
            "source_platform": 0,
        }

    # -- generacion ----------------------------------------------------------
    def _adjust_material(self, channel: dict) -> dict:
        """Material Adjust (Color Grading) por canal, con el MISMO formato que los drafts reales.
        Basado en diff real: materials.effects[] con type saturation/temperature/tint."""
        effect_path = (
            Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache"
            / "effect" / ADJUST_EFFECT_ID / ADJUST_EFFECT_HASH
        ).as_posix()
        return {
            "id": new_id(),
            "unique_id": new_id(),
            "effect_id": ADJUST_EFFECT_ID,
            "resource_id": ADJUST_EFFECT_ID,
            "third_resource_id": "",
            "name": "",
            "report_name": "",
            "type": channel["type"],
            "sub_type": "none",
            "path": effect_path,
            "value": channel["value"],
            "visible": True,
            "item_effect_type": 0,
            "category_id": "",
            "category_name": "",
            "category_key": "",
            "sub_category_id": "",
            "sub_category_name": "",
        }

    def _build_dyc_cached_audio_material(
        self, content: dict, effect_id: str, duration_us: int,
        name: str, cache_music_hash: str, app_id: int = 1775,
    ) -> tuple[dict | None, str | None]:
        """Construye un material de audio desde la caché de CapCut por effect_id.

        Busca el archivo en estos ordenes:
        1. Path.home() / ... / music / <hash> (sin extension) — formato antiguo.
        2. Path.home() / ... / music / <hash>.mp3 — formato real del disco.
        3. Glob "ffa2e50a*.mp3" dentro de la carpeta music (hash cambiado).
        4. Carpeta effect/ <effect_id> / <hash>/* .mp3 (audio clasificado como efecto).
        Devuelve (material, error_message). Si el archivo no existe, devuelve (None, msg)."""
        user = getpass.getuser()
        candidates: list[Path] = []

        # 1) Ruta directa (sin extension, formato antiguo de la implementacion)
        candidates.append(
            Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache"
            / "music" / cache_music_hash)
        # 2) Ruta directa con .mp3
        candidates.append(
            Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache"
            / "music" / f"{cache_music_hash}.mp3")
        # 3) Busqueda por glob en la carpeta music
        music_dir = (
            Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache"
            / "music")
        if music_dir.is_dir():
            for p in music_dir.glob(f"{cache_music_hash}*.mp3"):
                if p.is_file():
                    candidates.append(p)
        # 4) Carpeta effect/<effect_id>/<hash>/* .mp3
        effect_dir = (
            Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache"
            / "effect" / effect_id)
        if effect_dir.is_dir():
            for ext in (".mp3", ".wav", ".m4a", ".aac"):
                for p in effect_dir.glob(f"*{ext}"):
                    if p.is_file():
                        candidates.append(p)

        for candidate in candidates:
            if candidate.is_file():
                mat = copy.deepcopy(canonical.AUDIO_MATERIAL)
                mat["id"] = new_id()
                mat["unique_id"] = new_id()
                mat["type"] = "sound"
                mat["name"] = name
                mat["duration"] = duration_us
                mat["path"] = candidate.as_posix()
                mat["category_name"] = "heycan_search_sound"
                mat["music_id"] = ""
                mat["app_id"] = app_id
                mat["effect_id"] = effect_id
                mat["source_platform"] = 0
                mat["check_flag"] = 1
                return mat, None

        checked_paths = [str(c) for c in candidates[:3]]
        return None, (
            f"Audio '{name}' (effect_id={effect_id}, hash={cache_music_hash}): "
            "no encontrado en ninguna ruta comprobada."
        )

    # --------------------------------------------------------------------------
    # v1.7.0 — Helpers para assets avanzados de Datos Y Cafe
    # --------------------------------------------------------------------------
    def _build_start_animation_material(self, anim: dict) -> dict:
        """Material de animación de entrada (sticker_animation, type=in)."""
        user = Path.home()
        cache_path = (
            user / "AppData" / "Local" / "CapCut" / "User Data" / "Cache"
            / "effect" / anim["resource_id"] / anim["hash"]
        ).as_posix()
        return {
            "id": new_id(),
            "type": "sticker_animation",
            "animations": [{
                "id": anim["resource_id"],
                "type": "in",
                "start": 0,
                "duration": anim["duration_us"],
                "path": cache_path,
                "platform": "all",
                "resource_id": anim["resource_id"],
                "third_resource_id": "0",
                "source_platform": 1,
                "name": anim["name"],
                "category_id": "in",
                "category_name": "in",
                "panel": "video",
                "material_type": "video",
                "anim_adjust_params": None,
                "request_id": "",
            }],
            "multi_language_current": "none",
        }

    def _build_end_animation_material(self, anim: dict) -> dict:
        """Material de animación de salida (sticker_animation, type=out)."""
        user = Path.home()
        cache_path = (
            user / "AppData" / "Local" / "CapCut" / "User Data" / "Cache"
            / "effect" / anim["resource_id"] / anim["hash"]
        ).as_posix()
        return {
            "id": new_id(),
            "type": "sticker_animation",
            "animations": [{
                "id": anim["resource_id"],
                "type": "out",
                "start": 0,
                "duration": anim["duration_us"],
                "path": cache_path,
                "platform": "all",
                "resource_id": anim["resource_id"],
                "third_resource_id": "0",
                "source_platform": 1,
                "name": anim["name"],
                "category_id": "out",
                "category_name": "out",
                "panel": "video",
                "material_type": "video",
                "anim_adjust_params": None,
                "request_id": "",
            }],
            "multi_language_current": "none",
        }

    def _build_chroma_material(self) -> dict:
        """Material de chroma key negro. FIX 4 bloque 6: SOLO para los 2 CTA
        (CTA INTERMEDIO y CTA FINAL), con intensity_value=0.25."""
        user = Path.home()
        chroma_path = (
            user / "AppData" / "Local" / "CapCut" / "Apps" / "9.4.0.4015" / "Resources" / "Chroma2"
        ).as_posix()
        return {
            "id": new_id(),
            "type": "chroma",
            "color": "#000000ff",
            "intensity_value": DYC_CHROMA_INTENSITY,
            "shadow_value": 0.0,
            "path": chroma_path,
            "resource_id": "",
            "should_transfer_color": True,
            "edge_smooth_value": 0.0,
            "spill_value": 0.0,
            "version": "v2",
        }

    def _build_video_overlay_material(self, content: dict, abs_path: str,
                                       width: int, height: int, duration_us: int,
                                       name: str) -> dict:
        """Material de video para overlay (pista nueva, flag=2)."""
        mat = copy.deepcopy(canonical.PHOTO_MATERIAL)
        mat["id"] = new_id()
        mat["unique_id"] = new_id()
        mat["path"] = abs_path
        mat["duration"] = duration_us
        mat["width"] = width
        mat["height"] = height
        mat["material_name"] = name
        mat["type"] = "video"
        return mat

    def _build_video_overlay_segment(self, content: dict, mat_id: str,
                                      start_us: int, duration_us: int) -> dict:
        """Segmento de video overlay (pista nueva, flag=2)."""
        seg = copy.deepcopy(canonical.PHOTO_SEGMENT)
        seg["id"] = new_id()
        seg["material_id"] = mat_id
        seg["render_index"] = 0
        seg["track_render_index"] = 2
        seg["source_timerange"] = {"start": 0, "duration": duration_us}
        seg["target_timerange"] = {"start": start_us, "duration": duration_us}
        seg["clip"]["scale"] = {"x": 1.0, "y": 1.0}
        seg["uniform_scale"] = {"on": True, "value": 1.0}
        seg["common_keyframes"] = []
        seg["enable_hsl"] = False
        seg["enable_adjust"] = False
        seg["extra_material_refs"] = []
        return seg

    def _build_dyc_color_effect_materials(self, profile: EditProfile) -> list[dict]:
        """Construye los 7 materiales de effects para color grading DYC."""
        effect_id = "7501974767453474064"
        effect_hash = "20cd8db6531c21bf7e4053026d20e395"
        effect_path = (
            Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache"
            / "effect" / effect_id / effect_hash
        ).as_posix()
        materials = []
        for channel in profile.dyc_color_effects:
            mat = {
                "id": new_id(),
                "unique_id": new_id(),
                "effect_id": effect_id,
                "resource_id": effect_id,
                "third_resource_id": "0",
                "name": "",
                "report_name": "",
                "type": channel["type"],
                "sub_type": "none",
                "path": effect_path,
                "value": channel["value"],
                "visible": True,
                "item_effect_type": 0,
                "category_id": "",
                "category_name": "",
                "category_key": "",
                "sub_category_id": "",
                "sub_category_name": "",
            }
            materials.append(mat)
        return materials

    def _build_dyc_hsl_materials(self, profile: EditProfile) -> list[dict]:
        """Construye los 2 materiales HSL para color grading DYC."""
        effect_id = "7501974767453474064"
        effect_hash = "20cd8db6531c21bf7e4053026d20e395"
        effect_path = (
            Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache"
            / "effect" / effect_id / effect_hash
        ).as_posix()
        materials = []
        for channel in profile.dyc_hsl_channels:
            mat = {
                "id": new_id(),
                "unique_id": new_id(),
                "constant_material_id": new_id(),
                "hsl_color_type": channel["hsl_color_type"],
                "hue": channel.get("hue", 0.0),
                "saturation": channel.get("saturation", 0.0) / 100.0,
                "lightness": channel.get("lightness", 0.0) / 100.0,
                "interacting": True,
                "version": "1",
                "path": effect_path,
                "type": "hsl",
                "lumi_hub_path": effect_path,
                "custom_color": channel["custom_color"],
                "resource_id": "",
                "source_platform": 0,
            }
            materials.append(mat)
        return materials

    # -- generacion ----------------------------------------------------------
    def generate(
        self,
        project_name: str,
        items: list[TimelineItem],
        audio_path: str | Path,
        audio_duration_us: int,
        cancel_event: threading.Event | None = None,
        allow_test_names: bool = False,
        subtitle_srt: str | Path | None = None,
        bgm_path: str | Path | None = None,
        sfx_dir: str | Path | None = None,
        edit_profile: EditProfile | None = None,
    ) -> Path:
        project_name = project_name.strip()
        if not project_name:
            raise CapCutProjectError("El nombre del proyecto no puede estar vacío.")
        if is_test_name(project_name) and not allow_test_names:
            raise CapCutProjectError(
                f"El nombre '{project_name}' coincide con los prefijos de pruebas "
                f"{TEST_NAME_PREFIXES}. Genera con allow_test_names=True solo en tests."
            )

        # BUG 2: el proyecto se crea en la carpeta PADRE de la plantilla
        base = self.template_dir.parent
        base.mkdir(parents=True, exist_ok=True)
        self.new_dir = base / project_name
        if self.new_dir.exists():
            raise CapCutProjectError(
                f"Ya existe un proyecto llamado '{project_name}' en {base}"
            )

        self.cancel_event = cancel_event
        self._check_cancelled()

        # 1) clonado de la plantilla
        log.info("Proyecto se creará en: %s", self.new_dir)
        shutil.copytree(self.template_dir, self.new_dir)
        self._check_cancelled()

        # 2) deep-copy: el JSON final es superconjunto del de la plantilla
        content = copy.deepcopy(self.content)
        materials = content.setdefault("materials", {})
        # Habilitar color grading (adjust) en la config
        content.setdefault("config", {})["adjust_max_index"] = 1

        audio_src = Path(audio_path)

        audio_duration_us = max(int(audio_duration_us), 0)
        if audio_duration_us <= 0:
            audio_duration_us = max((it.end_us for it in items), default=1_000_000)
        target_us = audio_duration_us

        # Duración REAL del archivo (WAV): si hay silencio final los cues pueden
        # quedarse cortos; el video y el audio deben terminar a la vez.
        measured_us = measure_audio_duration_us(audio_src)
        if measured_us is not None:
            target_us = max(measured_us, audio_duration_us)

        # Punto 5: si la suma de duraciones de las imágenes es menor que el
        # audio total, reparte el excedente proporcionalmente entre TODAS (nunca
        # estira solo la última). Entra una sola vez, antes de crear segmentos.
        items = redistribute_gap(items, target_us)

        # FIX 5 — NUNCA recortar el audio de narración.
        # El audio termina en su duración real; la última imagen se ajusta para
        # terminar junto con él. La pantalla final empieza en el fin del audio.
        if edit_profile is not NEXUS_PARADOJA and items:
            log.info("Sync: audio mantiene duración real %.2f s", target_us / 1_000_000)
            # FIX 3: la ÚLTIMA imagen termina EXACTAMENTE en target_us (fin real
            # del audio). Solo se redistribute esa imagen; la cadena anterior no
            # se toca, así que no queda hueco hasta el final del audio.
            items = sync_last_item_to_audio_end(items, target_us)

        canvas_w, canvas_h = _canvas_size(content)

        # Resolver perfil de edicion (default: Nexus Paradoja)
        if edit_profile is None:
            edit_profile = NEXUS_PARADOJA

        # 3) materials.videos (fotos + videos) + segments de la pista de video.
        #    Se referencian las rutas ABSOLUTAS de los archivos fuente (mismo
        #    formato que el draft real 0921: D:/.../escenas 2/xxx.jpg), nunca
        #    rutas relativas que CapCut no resuelve y muestra como "Media Not Found".
        photo_materials: list[dict] = []
        video_segments: list[dict] = []
        hsl_materials: list[dict] = []
        adjust_materials: list[dict] = []
        prev_end = 0

        # v1.7.0 — Materiales compartidos DYC (effects + HSL): crear UNA sola vez
        # antes del bucle de segmentos. Los IDs se referencian en cada segmento.
        dyc_shared_effect_refs: list[str] = []
        if getattr(edit_profile, 'dyc_color_effects', None):
            for mat in self._build_dyc_color_effect_materials(edit_profile):
                adjust_materials.append(mat)
                dyc_shared_effect_refs.append(mat["id"])
        if getattr(edit_profile, 'dyc_hsl_channels', None):
            for mat in self._build_dyc_hsl_materials(edit_profile):
                hsl_materials.append(mat)
                dyc_shared_effect_refs.append(mat["id"])
        log.info("DYC shared refs: %d effects + %d HSL", len(dyc_shared_effect_refs),
                 len([m for m in hsl_materials if m.get("type") == "hsl"]))

        for it in items:
            self._check_cancelled()
            if it.image_path is None:
                log.warning("Escena %d sin imagen; se omite material.", it.order)
                continue

            # Evita segmentos de duracion 0 (CapCut no muestra bien 0 us)
            start_us = it.start_us if it.duration_us > 0 else prev_end
            duration_us = it.duration_us if it.duration_us > 0 else 1_000_000
            prev_end = start_us + duration_us

            abs_path = it.image_path.resolve().as_posix()
            is_video = it.image_path.suffix.lower() in config.VIDEO_EXTENSIONS

            if is_video:
                # VIDEO: medir duracion real y aplicar speed si es mas corto que la frase
                width, height = 1920, 1080  # fallback si no se puede medir
                try:
                    import subprocess
                    result = subprocess.run(
                        ["ffprobe", "-v", "error",
                         "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1",
                         str(it.image_path)],
                        capture_output=True, text=True, timeout=10,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        vid_dur_s = float(result.stdout.strip())
                        vid_dur_us = int(round(vid_dur_s * 1_000_000))
                        if vid_dur_us < duration_us:
                            speed = round(vid_dur_us / duration_us, 4)
                            log.info(
                                "Escena %d · video %s: dur=%d us < frase=%d us → speed=%.4f",
                                it.order, it.image_path.name, vid_dur_us, duration_us, speed,
                            )
                        else:
                            speed = 1.0
                    else:
                        speed = 1.0
                except Exception:  # noqa: BLE001
                    speed = 1.0

                # Para videos: cover_scale = 1.0 (el video ya tiene resolucion propia)
                # y zoom_mult = 1.0 (sin zoom Ken Burns en videos).
                cover_scale = 1.0
                zoom_mult = 1.0
                zoom_base = 1.0
                position_points = None
                refs: list[str] = []
                enable_hsl = False
                enable_adjust = False

                mat = self._build_photo_material(
                    content, abs_path, width, height, duration_us, it.image_path.stem)
                mat["type"] = "video"
                photo_materials.append(mat)
                seg = copy.deepcopy(canonical.VIDEO_TRACK["segments"][0])
                seg["id"] = new_id()
                seg["material_id"] = mat["id"]
                seg["render_index"] = 0
                seg["track_render_index"] = 0
                seg["source_timerange"] = {"start": 0, "duration": duration_us}
                seg["target_timerange"] = {"start": start_us, "duration": duration_us}
                seg["speed"] = speed
                seg["clip"]["scale"] = {"x": cover_scale, "y": cover_scale}
                seg["uniform_scale"] = {"on": True, "value": 1.0}
                seg["common_keyframes"] = []
                seg["enable_hsl"] = False
                seg["enable_adjust"] = False
                seg["extra_material_refs"] = []
                video_segments.append(seg)
            else:
                # IMAGEN: comportamiento existente (cover scale + zoom + efectos)
                width, height = _image_size(it.image_path)

                # Punto 2: escala 'cover' INDIVIDUAL por imagen (cubre el lienzo sin
                # deformar). Se analiza cada imagen con sus propias dimensiones: una
                # vertical se amplía mucho; una 16:9 queda cubierta con escala 1.0.
                cover_scale = _cover_scale(canvas_w, canvas_h, width, height)
                # Punto 3: zoom aleatorio por imagen al final de la misma,
                # calculado SIEMPRE sobre su escala base individual (cover_scale).
                # El rango proviene del perfil de edicion (DYC: 1.00-1.05, Nexus: 1.10-1.15).
                zoom_min = edit_profile.zoom_end_min
                zoom_max = edit_profile.zoom_end_max
                zoom_mult = random.uniform(zoom_min, zoom_max)

                # FASE 3 — paneo Ken Burns opcional y camera shake.
                # Los valores (ratio, amplitud, boost) provienen del perfil de edicion.
                action = _has_action_keyword(it.scene_text) or _has_action_keyword(it.segment_text)
                pan_ratio = getattr(edit_profile, 'pan_ratio', PAN_RATIO)
                pan_amp = getattr(edit_profile, 'pan_amplitude', PAN_AMPLITUDE)
                shake_ratio = getattr(edit_profile, 'shake_ratio', 1.0)
                shake_amp = getattr(edit_profile, 'shake_amplitude', SHAKE_AMPLITUDE)
                shake_boost = getattr(edit_profile, 'shake_zoom_boost', SHAKE_ZOOM_BOOST)
                pan_dx = pan_dy = 0.0
                if edit_profile.enable_camera_shake and action:
                    if random.random() < pan_ratio:
                        amp = random.uniform(*pan_amp)
                        pan_dx = round(random.choice((-1, 1)) * amp, 4)
                        pan_dy = round(random.choice((0, 0, 1, -1)) * amp * 0.5, 4)
                elif edit_profile.enable_paneos:
                    if random.random() < pan_ratio:
                        amp = random.uniform(*pan_amp)
                        pan_dx = round(random.choice((-1, 1)) * amp, 4)
                        pan_dy = round(random.choice((-1, 1)) * amp * 0.5, 4)
                if pan_dx or pan_dy or (edit_profile.enable_camera_shake and action):
                    if edit_profile.enable_camera_shake and action:
                        shake_amp_x = random.uniform(*shake_amp)
                        shake_amp_y = shake_amp_x * 0.7
                        position_points = _shake_points(
                            duration_us, shake_amp_x, shake_amp_y, pan_dx, pan_dy)
                    else:
                        position_points = _pan_points(duration_us, pan_dx, pan_dy)
                else:
                    position_points = None
                # Boost de zoom inicial solo en escenas con shake (da overscan desde
                # t=0 para que el temblor no destape nunca los bordes del lienzo).
                zoom_base = cover_scale * (shake_boost if (edit_profile.enable_camera_shake and action) else 1.0)

                # FASE 3 — HSL por canal: cada segmento referencia sus
                # materials.hsl, mismo mecanismo que el draft real del usuario.
                # El perfil define los canales (Nexus: Naranja+Cian+Azul; DYC: Rojo+Amarillo).
                refs: list[str] = []
                dyc_effect_refs: list[str] = list(dyc_shared_effect_refs)
                if edit_profile.enable_hsl and not dyc_shared_effect_refs:
                    hsl_channels = getattr(edit_profile, 'hsl_channels', HSL_CHANNELS)
                    for channel in hsl_channels:
                        mat = self._hsl_material(channel)
                        hsl_materials.append(mat)
                        refs.append(mat["id"])

                # FASE 3 — Color Grading (Adjust): cada segmento referencia sus
                # materials.effects (saturación, temperatura, tinte), mismo mecanismo
                # que el draft real. Se añaden a los refs del segmento.
                # DYC usa 7 entries de materials.effects con valores exactos.
                if edit_profile.enable_color_grading and not dyc_shared_effect_refs:
                    for channel in ADJUST_CHANNELS:
                        mat = self._adjust_material(channel)
                        adjust_materials.append(mat)
                        refs.append(mat["id"])

                log.info(
                    "Escena %02d · %s: %dx%d → cover=%.3f · zoom=+%.0f%% · %s%s%s",
                    it.order, it.image_path.name, width, height,
                    cover_scale, (zoom_mult - 1.0) * 100,
                    "shake+pan" if (edit_profile.enable_camera_shake and action) else ("pan" if position_points is not None else "fija"),
                    (f" ({pan_dx},{pan_dy})" if position_points is not None else ""),
                    " · hsl" if edit_profile.enable_hsl else "",
                )

                mat = self._build_photo_material(
                    content, abs_path, width, height, duration_us, it.image_path.stem)
                photo_materials.append(mat)
                video_segments.append(
                    self._build_photo_segment(
                        content, mat["id"], start_us, duration_us, cover_scale, zoom_mult,
                        zoom_base=zoom_base, position_points=position_points,
                        enable_hsl=edit_profile.enable_hsl,
                        enable_adjust=edit_profile.enable_color_grading,
                        extra_refs=refs,
                        fade_in_duration_us=edit_profile.fade_in_duration_us,
                        profile=edit_profile,
                        dyc_effect_refs=dyc_effect_refs))

        # FIX 4 — Logs de sincronización tras construir los segmentos.
        if edit_profile is not NEXUS_PARADOJA and prev_end > 0:
            log.info("Sync: última imagen termina en t=%.2f s (== fin audio)", prev_end / 1_000_000)
            log.info("Sync: audio termina en t=%.2f s", target_us / 1_000_000)

        # Transiciones: se aplican sobre un porcentaje de los bordes internos entre
        # imagenes (el resto queda con corte limpio). Cada transición se referencia
        # desde extra_material_refs del segmento que RECIBE el corte, exactamente
        # igual que en el draft 0921; los timeranges no se tocan.
        transitions: list[dict] = []
        boundaries = len(video_segments) - 1
        if boundaries > 0 and edit_profile.enable_transitions:
            transition_ratio = getattr(edit_profile, 'transition_ratio', TRANSITION_RATIO)
            keep = int(round(boundaries * transition_ratio))
            skip_count = boundaries - keep
            skips: set[int] = set()
            if skip_count:
                skips = set(random.sample(range(boundaries), skip_count))
            # Pool de transiciones: usar las del perfil (DYC tiene 20 nombres;
            # Nexus usa las IDs reales). Si el perfil solo tiene nombres, se crean
            # transiciones por nombre (CapCut las resuelve al abrir).
            transition_pool = getattr(edit_profile, 'transition_names', ())
            if transition_pool:
                # Pool por nombres (DYC legacy)
                last_name = ""
                for b in range(boundaries):
                    if b in skips:
                        continue
                    # Evitar repetir la misma transicion consecutivamente
                    name = last_name
                    while name == last_name and len(set(transition_pool)) > 1:
                        name = random.choice(transition_pool)
                    last_name = name
                    mat = self._build_transition_material_from_name(name)
                    transitions.append(mat)
                    # Referencia en el segmento ANTERIOR al corte (fix v1.7.0)
                    video_segments[b]["extra_material_refs"] = (
                        list(video_segments[b].get("extra_material_refs") or []) + [mat["id"]])
            elif hasattr(edit_profile, 'dyc_start_animations') and edit_profile.dyc_start_animations:
                # Pool DYC con effect_ids reales (27 transiciones; FIX 1 filtra
                # "Elige otro" siempre, aunque alguien lo reintroduzca).
                dyc_pool = filter_dyc_transitions(_DYC_TRANSITIONS)
                last_id = ""
                for b in range(boundaries):
                    if b in skips:
                        continue
                    effect_id, name, duration_us, is_overlap = pick_dyc_transition(
                        dyc_pool, last_id)
                    last_id = effect_id
                    cache = Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache" / "effect"
                    resource_dir = cache / effect_id
                    if not resource_dir.is_dir() or not any(resource_dir.iterdir()):
                        log.warning(
                            "Transición '%s' (%s) no está en la caché local; CapCut la descargará automáticamente.",
                            name, effect_id,
                        )
                    mat = {
                         "id": new_id(),
                         "type": "transition",
                         "name": name,
                         "effect_id": effect_id,
                         "resource_id": effect_id,
                         "third_resource_id": "0",
                         "source_platform": 1,
                         "path": (cache / effect_id).as_posix(),
                         "duration": duration_us,
                         "is_overlap": is_overlap,
                         "platform": "all",
                         "category_id": "123456",
                         "category_name": "Transiciones",
                         "request_id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                         "is_ai_transition": False,
                         "video_path": "",
                         "task_id": "",
                    }
                    transitions.append(mat)
                    # Referencia en el segmento ANTERIOR al corte (fix v1.7.0)
                    video_segments[b]["extra_material_refs"] = (
                         list(video_segments[b].get("extra_material_refs") or []) + [mat["id"]])
                    log.info("Transición #%d '%s' dur=%ds → extra_refs seg %d",
                             len(transitions), name, duration_us // 1_000_000, b)
            else:
                # Pool con IDs (Nexus)
                for b in range(boundaries):
                    if b in skips:
                        continue
                    mat = self._build_transition_material(random.choice(TRANSITIONS))
                    transitions.append(mat)
                    # Referencia en el segmento ANTERIOR al corte (fix v1.7.0)
                    video_segments[b]["extra_material_refs"] = (
                        list(video_segments[b].get("extra_material_refs") or []) + [mat["id"]])
            log.info(
                "Transiciones: %d/%d bordes (%d%%); %d corte(s) limpio(s).",
                len(transitions), boundaries,
                round(100 * transition_ratio), skip_count,
            )

        # v1.7.0 — Animaciones de inicio y final para Datos Y Cafe.
        start_anim_mat: dict | None = None
        end_anim_mat: dict | None = None
        # FIX 4: inicio absoluto del agujero negro (última imagen).
        dyc_black_hole_abs_start_us: int | None = None
        dyc_assets_dir: Path | None = getattr(edit_profile, 'dyc_assets_dir', None) and Path(getattr(edit_profile, 'dyc_assets_dir')) or None
        if edit_profile is not NEXUS_PARADOJA:
            # Animación de inicio aleatoria (1 de 3) en la PRIMERA imagen.
            from src.core.timeline_builder import DYC_INTRO_ANIMATIONS
            start_anim = random.choice(DYC_INTRO_ANIMATIONS)
            start_anim_mat = self._build_start_animation_material(start_anim)
            if video_segments:
                video_segments[0]["extra_material_refs"] = (
                    list(video_segments[0].get("extra_material_refs") or []) + [start_anim_mat["id"]])
            log.info("Animación de inicio (aleatoria): %s (%s)", start_anim["name"], start_anim["resource_id"])

        if edit_profile is not NEXUS_PARADOJA and hasattr(edit_profile, 'dyc_end_animation') and edit_profile.dyc_end_animation:
            # Animación de final "Agujero negro" sobre la ÚLTIMA imagen (NO pantalla final).
            end_anim = edit_profile.dyc_end_animation
            end_anim_mat = self._build_end_animation_material(end_anim)
            # v1.7.0 Fix 3: duration = 0.8s exacto, start = dur_segmento - 0.8s
            _END_ANIM_DURATION_US = 800_000
            # Guardar referencia a la ultima IMAGEN antes de que se anada pantalla final
            last_image_idx = len(video_segments) - 1
            if video_segments:
                last_seg = video_segments[last_image_idx]
                last_dur = last_seg["target_timerange"]["duration"]
                last_start = last_seg["target_timerange"]["start"]
                end_start = last_start + last_dur - _END_ANIM_DURATION_US
                # Modificar keyframes de animación: start = offset dentro del segmento
                for anim_entry in end_anim_mat.get("animations", []):
                    anim_entry["duration"] = _END_ANIM_DURATION_US
                    anim_entry["start"] = max(end_start - last_start, 0)
                video_segments[last_image_idx]["extra_material_refs"] = (
                    list(last_seg.get("extra_material_refs") or []) + [end_anim_mat["id"]])
                # Añadir keyframe de animación out al segmento
                end_kf = {
                    "id": new_id(),
                    "material_id": "",
                    "property_type": "KFTypeAnimationOut",
                    "keyframe_list": [{
                        "id": new_id(),
                        "curveType": "Line",
                        "time_offset": max(end_start - last_start, 0),
                        "left_control": {"x": 0.0, "y": 0.0},
                        "right_control": {"x": 0.0, "y": 0.0},
                        "values": [1.0],
                        "string_value": "",
                        "graphID": "",
                    }],
                }
                last_seg["common_keyframes"].append(end_kf)
                # FIX 4: inicio ABSOLUTO del agujero negro, para sincronizar el
                # audio final y el glitch con este punto exacto.
                dyc_black_hole_abs_start_us = end_start
                log.info("Animación final (agujero negro): %s en img #%d (start=%d us, dur=%d us)",
                         end_anim["name"], last_image_idx, max(end_start - last_start, 0), _END_ANIM_DURATION_US)
            log.info("Animación de final: %s (%s)", end_anim["name"], end_anim["resource_id"])

        # 4) materials.audios + pista de audio (ruta absoluta, sin recortar)
        audio_mat = self._build_audio_material(
            content, audio_src.resolve().as_posix(), target_us, audio_src.stem)
        # track_render_index del audio: 1 sin subtítulos, 2 si la pista text
        # va en medio (mismo orden que el draft 0921: video[0], text[1], audio[2]).
        audio_segs = [self._build_audio_segment(
            content, audio_mat["id"], target_us,
            track_index=2 if subtitle_srt is not None else 1)]

        # FASE 3 — BGM opcional con ducking: VO a +6 dB, BGM al volumen del perfil.
        # Lógica lista; solo se activa si se pasa bgm_path.
        bgm_materials: list[dict] = []
        bgm_track: dict | None = None
        if bgm_path is not None and Path(bgm_path).is_file():
            bgm_dur = target_us
            measured_bgm = measure_audio_duration_us(Path(bgm_path))
            if measured_bgm is not None:
                bgm_dur = measured_bgm
            bgm_mat = self._build_audio_material(
                content, Path(bgm_path).resolve().as_posix(), bgm_dur,
                Path(bgm_path).stem)
            bgm_materials.append(bgm_mat)
            bgm_vol_db = getattr(edit_profile, 'bgm_volume_db', BGM_GAIN_DB)
            bgm_vol_linear = 10 ** (bgm_vol_db / 20)
            audio_segs.append(self._build_audio_segment(
                content, bgm_mat["id"], bgm_dur,
                track_index=2 if subtitle_srt is not None else 1,
                volume=bgm_vol_linear))
            log.info("BGM: %s a %.0f dB (ducking bajo la VO a +%.0f dB).",
                     Path(bgm_path).name, bgm_vol_db, AUDIO_GAIN_DB)
        else:
            log.info("BGM: sin ruta (o no existe); ducking omitido.")

        # FASE 3 — SFX: sin carpeta configurada se omite con aviso; si sfx_dir
        # trae audio, se coloca un SFX corto en cada corte interno (impacto).
        sfx_track: dict | None = None
        sfx_materials: list[dict] = []
        if sfx_dir is not None and Path(sfx_dir).is_dir() and edit_profile.enable_sfx:
            audio_exts = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
            sfx_files = [p for p in sorted(Path(sfx_dir).iterdir())
                         if p.suffix.lower() in audio_exts]
            if sfx_files:
                sfx_track = copy.deepcopy(canonical.AUDIO_TRACK)
                sfx_track["id"] = new_id()
                sfx_track["segments"] = []
                for b in range(boundaries):
                    cut_start = video_segments[b + 1]["target_timerange"]["start"]
                    sfx_path = random.choice(sfx_files)
                    sfx_mat = self._build_audio_material(
                        content, sfx_path.resolve().as_posix(), SFX_DURATION_US,
                        sfx_path.stem + f"_b{b + 1}")
                    sfx_materials.append(sfx_mat)
                    sfx_seg = self._build_audio_segment(
                        content, sfx_mat["id"], SFX_DURATION_US,
                        track_index=3 if subtitle_srt is not None else 2)
                    sfx_seg["target_timerange"] = {"start": min(cut_start, target_us - SFX_DURATION_US),
                                                   "duration": SFX_DURATION_US}
                    sfx_track["segments"].append(sfx_seg)
                log.info("SFX: %d impactos (uno por corte) desde %s.",
                         len(sfx_files) and len(sfx_track["segments"]), Path(sfx_dir))
            else:
                log.info("SFX: %s sin audio; se omite.", Path(sfx_dir))
        else:
            log.info("SFX: sin carpeta configurada; se omiten los impactos.")

        # v1.7.0 — Assets de Datos Y Cafe (audio inicio/final, suscríbete, pantalla final).
        dyc_assets_dir: Path | None = getattr(edit_profile, 'dyc_assets_dir', None) and Path(getattr(edit_profile, 'dyc_assets_dir')) or None
        dyc_audio_intro_mat: dict | None = None
        dyc_audio_outro_mat: dict | None = None
        dyc_suscribete_short_seg: dict | None = None
        dyc_suscribete_long_segs: list[dict] = []
        # FIX 8: los CTA (intermedio + final) van en un MISMO track de video CTA.
        dyc_cta_segments: list[dict] = []
        # FIX 7: materiales de video del track CTA (intermedio + final). Sin esto
        # los segmentos apuntan a materiales inexistentes y CapCut no los pinta.
        dyc_cta_video_mats: list[dict] = []
        dyc_final_screen_mat: dict | None = None
        dyc_final_screen_seg: dict | None = None
        dyc_chroma_mat: dict | None = None
        dyc_audio_intro_seg: dict | None = None
        dyc_audio_outro_seg: dict | None = None

        # v1.7.0 — Audio inicio/final desde caché de CapCut (independiente de assets_dir)
        if edit_profile is not NEXUS_PARADOJA:
            dyc_audio_intro_mat, _ = self._build_dyc_cached_audio_material(
                content,
                effect_id="7200479771514374146",
                duration_us=2566666,
                name="Clink the wine glass.(1400022)",
                cache_music_hash="ffa2e50a6860bad19a44ff0eba5b703d",
            )
            if dyc_audio_intro_mat is not None:
                dyc_audio_intro_seg = self._build_audio_segment(
                    content, dyc_audio_intro_mat["id"], dyc_audio_intro_mat["duration"],
                    track_index=3)
                log.info("Audio inicio: Clink the wine glass (caché CapCut)")
            else:
                log.info("Audio inicio: no disponible en caché de CapCut; se omite.")

            dyc_audio_outro_mat, _ = self._build_dyc_cached_audio_material(
                content,
                effect_id="6974428544046729218",
                duration_us=1000000,
                name="Switch on / off(1041290)",
                cache_music_hash="ab6fae0779ba9e29e77ca3145a78d014",
            )
            if dyc_audio_outro_mat is not None:
                # FIX 4: sincronizado con el INICIO ABSOLUTO del agujero negro y
                # a -10 dB (10 ** (-10/20) ≈ 0.31622776601683794).
                outro_dur = dyc_audio_outro_mat["duration"]
                bh_start = (dyc_black_hole_abs_start_us
                            if dyc_black_hole_abs_start_us is not None
                            else max(target_us - outro_dur, 0))
                outro_volume = 10 ** (-10 / 20)
                dyc_audio_outro_seg = self._build_audio_segment(
                    content, dyc_audio_outro_mat["id"], outro_dur,
                    track_index=3, volume=outro_volume)
                dyc_audio_outro_seg["target_timerange"] = {
                    "start": max(bh_start, 0), "duration": outro_dur}
                dyc_audio_outro_seg["source_timerange"] = {"start": 0, "duration": outro_dur}
                dyc_audio_outro_seg["volume"] = outro_volume
                dyc_audio_outro_seg["last_nonzero_volume"] = outro_volume
                log.info("Audio final sincronizado con agujero negro en %.2f s, vol=-10dB",
                         max(bh_start, 0) / 1_000_000)
            else:
                log.info("Audio final: no disponible en caché de CapCut; se omite.")

        if edit_profile is not NEXUS_PARADOJA and dyc_assets_dir and dyc_assets_dir.is_dir():
            # Buscar archivos por patrón de nombre (case-insensitive)
            all_assets = {p.name.lower(): p for p in dyc_assets_dir.iterdir() if p.is_file()}

            # Audio inicio: nombre contiene "audio" Y ("inicio" O "intro") Y NO "final"
            audio_intro_path = None
            for name_lower, path in all_assets.items():
                if "audio" in name_lower and ("inicio" in name_lower or "intro" in name_lower) and "final" not in name_lower:
                    audio_intro_path = path
                    break
            # Audio final: nombre contiene "audio" Y "final" Y NO "inicio"
            audio_final_path = None
            for name_lower, path in all_assets.items():
                if "audio" in name_lower and "final" in name_lower and "inicio" not in name_lower:
                    audio_final_path = path
                    break
            # Pantalla final: nombre contiene ("pantalla" O "end") Y "final"
            final_screen_path = None
            for name_lower, path in all_assets.items():
                if ("pantalla" in name_lower or "end" in name_lower) and "final" in name_lower and "cta" not in name_lower:
                    final_screen_path = path
                    break
            # Fallback pantalla final: contiene "pantalla" o "final" (sin "audio" ni "cta")
            if final_screen_path is None:
                for name_lower, path in all_assets.items():
                    if ("pantalla" in name_lower or "final" in name_lower) and "audio" not in name_lower and "cta" not in name_lower:
                        final_screen_path = path
                        break
            # CTA intermedio (suscríbete corto): contiene "cta" Y ("intermedio" O "mid" O "medio" O "corto")
            suscribete_short_path = None
            for name_lower, path in all_assets.items():
                if "cta" in name_lower and any(kw in name_lower for kw in ("intermedio", "mid", "medio", "corto")):
                    suscribete_short_path = path
                    break
            # Fallback corto: contiene "suscrib" Y NO ("largo" ni "cta" ni "final")
            if suscribete_short_path is None:
                for name_lower, path in all_assets.items():
                    if "suscrib" in name_lower and "largo" not in name_lower and "cta" not in name_lower and "final" not in name_lower:
                        suscribete_short_path = path
                        break
            # CTA final (suscríbete largo): contiene "cta" Y "final"
            suscribete_long_path = None
            for name_lower, path in all_assets.items():
                if "cta" in name_lower and "final" in name_lower:
                    suscribete_long_path = path
                    break
            # Fallback largo: contiene "suscrib" Y ("largo" O "cta")
            if suscribete_long_path is None:
                for name_lower, path in all_assets.items():
                    if "suscrib" in name_lower and ("largo" in name_lower or "cta" in name_lower):
                        suscribete_long_path = path
                        break
            # Si no hay diferenciación clara, usar el mismo archivo para ambos
            if suscribete_long_path is None and suscribete_short_path is not None:
                suscribete_long_path = suscribete_short_path

            # --- Chroma key material (compartido para todos los overlays) ---
            dyc_chroma_mat = self._build_chroma_material()

            # --- Pantalla final ---
            if final_screen_path is not None:
                fs_dur = _video_duration_us(final_screen_path) or measure_audio_duration_us(final_screen_path)
                if not fs_dur:
                    log.warning(
                        "DYC Pantalla final: no se pudo medir '%s' (existe=%s); se omite.",
                        str(final_screen_path), final_screen_path.is_file(),
                    )
                    final_screen_path = None
                if final_screen_path is not None:
                    # FIX 1: la pantalla final va en el MISMO track principal de
                    # video, justo DESPUÉS de la última imagen. Se elimina el
                    # track de video que existía solo para ella.
                    if video_segments:
                        last_img_seg = video_segments[-1]
                        fs_start = (last_img_seg["target_timerange"]["start"]
                                    + last_img_seg["target_timerange"]["duration"])
                    else:
                        last_img_seg = None
                        fs_start = target_us
                    fs_abs = final_screen_path.resolve().as_posix()
                    fs_width, fs_height = 1920, 1080
                    try:
                        with Image.open(final_screen_path) as im:
                            fs_width, fs_height = im.width, im.height
                    except Exception:  # noqa: BLE001
                        pass
                    dyc_final_screen_mat = self._build_photo_material(
                        content, fs_abs, fs_width, fs_height, fs_dur, final_screen_path.stem)
                    dyc_final_screen_mat["type"] = "video"
                    dyc_final_screen_seg = self._build_video_overlay_segment(
                        content, dyc_final_screen_mat["id"], fs_start, fs_dur)
                    # FIX 1: segmento del TRACK PRINCIPAL (no overlay flag=2).
                    dyc_final_screen_seg["track_render_index"] = 0
                    # Color grading (mismos refs que las imágenes).
                    if edit_profile.enable_color_grading:
                        for ref_id in dyc_effect_refs:
                            dyc_final_screen_seg["extra_material_refs"].append(ref_id)
                        dyc_final_screen_seg["enable_adjust"] = True
                        dyc_final_screen_seg["enable_hsl"] = True
                    # FIX 4: la pantalla final NO lleva chroma (solo los 2 CTA).
                    log.info("Pantalla final: sin chroma")
                    # FIX 2: transición GLITCH entre la ÚLTIMA IMAGEN y la
                    # pantalla final. Ambos clips están ahora en el MISMO track,
                    # así que el material se referencia en el segmento ANTERIOR
                    # (la última imagen) con is_overlap=True y SIN overlap
                    # artificial: start_pantalla == end_última_imagen.
                    if last_img_seg is not None:
                        g_effect_id, g_name, g_dur, g_overlap = pick_dyc_glitch_transition()
                        g_mat = {
                            "id": new_id(),
                            "type": "transition",
                            "name": g_name,
                            "effect_id": g_effect_id,
                            "resource_id": g_effect_id,
                            "third_resource_id": "0",
                            "source_platform": 1,
                            "path": (Path.home() / "AppData" / "Local" / "CapCut" /
                                     "User Data" / "Cache" / "effect" / g_effect_id).as_posix(),
                            "duration": g_dur,
                            "is_overlap": g_overlap,
                            "platform": "all",
                            "category_id": "123456",
                            "category_name": "Transiciones",
                            "request_id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                            "is_ai_transition": False,
                            "video_path": "",
                            "task_id": "",
                        }
                        transitions.append(g_mat)
                        last_img_seg["extra_material_refs"] = (
                            list(last_img_seg.get("extra_material_refs") or []) + [g_mat["id"]])
                        log.info(
                            "Transición última imagen → pantalla final: %s",
                            g_name)
                    # FIX 1: último segmento del TRACK PRINCIPAL.
                    video_segments.append(dyc_final_screen_seg)
                    # Extendemos target_us para que la duracion del proyecto incluya
                    # la pantalla final (el audio sigue terminando en target_us original).
                    target_us = fs_start + fs_dur
                    log.info("Pantalla final añadida al track principal en %.2f s",
                             fs_start / 1_000_000)
                    log.info("Sync: pantalla final empieza en %.2f s (= fin audio)",
                             fs_start / 1_000_000)
                    log.info("Pantalla final: %s (%d us, start=%d us, nueva duracion=%d us)",
                             final_screen_path.name, fs_dur, fs_start, target_us)
            if final_screen_path is None:
                log.info("Pantalla final: no encontrada en %s", dyc_assets_dir)

            # --- Suscríbete corto (37% fijo del video, alineado a frame) ---
            if suscribete_short_path is not None:
                from src.core.timeline_builder import find_cta_intermedio_start
                ss_dur = _video_duration_us(suscribete_short_path) or measure_audio_duration_us(suscribete_short_path)
                if not ss_dur:
                    log.warning("DYC CTA: no se pudo medir la duración de %s; se omite.", suscribete_short_path)
                    suscribete_short_path = None
                else:
                    ss_start = find_cta_intermedio_start(target_us)
                    ss_abs = suscribete_short_path.resolve().as_posix()
                    ss_mat = self._build_video_overlay_material(
                        content, ss_abs, 1920, 1080, ss_dur, suscribete_short_path.stem)
                    ss_seg = self._build_video_overlay_segment(
                        content, ss_mat["id"], ss_start, ss_dur)
                    ss_seg["extra_material_refs"] = [dyc_chroma_mat["id"]]
                    dyc_suscribete_short_seg = ss_seg
                    dyc_cta_video_mats.append(ss_mat)
                    log.info("Chroma aplicado a CTA INTERMEDIO (intensity=%.2f)",
                             DYC_CHROMA_INTENSITY)
                    log.info("Suscríbete corto: %s (%d us, start=%d us)", suscribete_short_path.name, ss_dur, ss_start)
            if suscribete_short_path is None:
                log.info("Suscríbete corto: no encontrado en %s", dyc_assets_dir)

            # --- Suscríbete largo / CTA FINAL (desde SRT con fallback al 90%) ---
            if suscribete_long_path is not None:
                from src.core.timeline_builder import find_cta_final_starts
                ct_starts, found = find_cta_final_starts(subtitle_srt, target_us)
                ct_dur = _video_duration_us(suscribete_long_path) or measure_audio_duration_us(suscribete_long_path)
                if not ct_dur:
                    log.warning("DYC CTA: no se pudo medir la duración de %s; se omite.", suscribete_long_path)
                    suscribete_long_path = None
                else:
                    if not found:
                        log.warning("CTA: no se encontró 'suscríbete' en el SRT; CTA FINAL único en 90%.")
                    ct_abs = suscribete_long_path.resolve().as_posix()
                    for i, ct_start in enumerate(ct_starts, 1):
                        ct_mat = self._build_video_overlay_material(
                            content, ct_abs, 1920, 1080, ct_dur,
                            suscribete_long_path.stem + f"_cta{i}")
                        ct_seg = self._build_video_overlay_segment(
                            content, ct_mat["id"], ct_start, ct_dur)
                        ct_seg["extra_material_refs"] = [dyc_chroma_mat["id"]]
                        ct_seg["volume"] = 1.0
                        ct_seg["last_nonzero_volume"] = 1.0
                        dyc_suscribete_long_segs.append(ct_seg)
                        dyc_cta_video_mats.append(ct_mat)
                        log.info("Chroma aplicado a CTA FINAL (intensity=%.2f)",
                                 DYC_CHROMA_INTENSITY)
                        log.info("Suscríbete largo/CTA #%d: %s start=%d us dur=%d us",
                                 i, suscribete_long_path.name, ct_start, ct_dur)
            if suscribete_long_path is None:
                log.info("Suscríbete largo: no encontrado en %s", dyc_assets_dir)
        else:
            if edit_profile is not NEXUS_PARADOJA:
                log.info("DYC assets: carpeta no configurada; se omiten assets avanzados.")

        # 5) materials.texts + pista de subtitulos (opcional). La pista text va
        #    ENTRE video y audio (track_render_index 1), como en el draft 0921,
        #    para que el texto quede sobre las imágenes y debajo de la mezcla
        #    de sonido. Cada fragmento de 2-5 palabras = un segmento.
        text_track: dict | None = None
        text_materials: list[dict] = []
        if subtitle_srt is not None and Path(subtitle_srt).is_file():
            text_track, text_materials, text_segments = (
                build_subtitle_track(subtitle_srt, track_render_index=1,
                                     profile=edit_profile)
            )
            log.info(
                "Subtítulos: %d materiales · %d segmentos (track text).",
                len(text_materials), len(text_segments),
            )
        else:
            log.info("Subtítulos: sin SRT (o ruta no encontrada); se omite la pista text.")

        # v1.7.0 — Overlays (pista de texto entre video y subtítulos para DYC).
        # Incluye cuadrícula de laboratorio y textos neón flotantes.
        overlay_track: dict | None = None
        overlay_materials: list[dict] = []
        if edit_profile.grid_overlay_enabled or edit_profile.neon_text_enabled:
            overlay_track = copy.deepcopy(canonical.TEXT_TRACK)
            overlay_track["id"] = new_id()
            overlay_track["segments"] = []
            neon_colors = ["#FFFFFF", "#FF0040", "#FFD400"]
            for it in items:
                self._check_cancelled()
                if it.image_path is None:
                    continue
                scene_text = (it.scene_text or "") + " " + (it.segment_text or "")
                low = scene_text.lower()
                # Cuadrícula: aparece cuando el guion menciona datos/ciencia.
                if edit_profile.grid_overlay_enabled:
                    grid_keywords = getattr(edit_profile, 'grid_overlay_keywords', ())
                    if any(kw in low for kw in grid_keywords):
                        # Overlay de cuadrícula: fondo negro con líneas al 12%.
                        # Se usa un material de texto vacío con alpha bajo.
                        grid_mat = copy.deepcopy(canonical.TEXT_MATERIAL)
                        grid_mat["id"] = new_id()
                        grid_mat["name"] = "grid_overlay"
                        grid_mat["content"] = json.dumps({
                            "text": " ",
                            "styles": [{
                                "range": [0, 1],
                                "fill": {"content": {"solid": {"color": [1.0, 1.0, 1.0]}}, "alpha": 0.12},
                                "font": {"id": "", "path": ""},
                                "size": 1.0,
                            }],
                            "layer_weight": 1,
                            "effect": [],
                        }, ensure_ascii=False, separators=(",", ":"))
                        grid_mat["global_alpha"] = 0.12
                        grid_mat["text_alpha"] = 1.0
                        grid_mat["font_size"] = 1.0
                        grid_mat["border_mode"] = 0
                        grid_mat["has_shadow"] = False
                        overlay_materials.append(grid_mat)
                        grid_seg = copy.deepcopy(canonical.TEXT_SEGMENT)
                        grid_seg["id"] = new_id()
                        grid_seg["material_id"] = grid_mat["id"]
                        grid_seg["render_index"] = 20000
                        grid_seg["track_render_index"] = 2
                        grid_seg["target_timerange"] = {
                            "start": it.start_us, "duration": it.duration_us}
                        grid_seg["source_timerange"] = {"start": 0, "duration": it.duration_us}
                        grid_seg["clip"]["transform"] = {"x": 0.0, "y": 0.0}
                        grid_seg["clip"]["scale"] = {"x": 1.0, "y": 1.0}
                        overlay_track["segments"].append(grid_seg)
                # Textos neón: aparecen cuando el guion marca un método con nombre.
                if edit_profile.neon_text_enabled:
                    # Detectar palabras en mayúsculas o entre comillas que parezcan nombres técnicos.
                    import re as _re
                    methods = _re.findall(r'"([^"]{3,})"', scene_text)
                    methods += _re.findall(r'\b([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{2,})\b', scene_text)
                    for method in methods:
                        method = method.strip()
                        if len(method) < 3:
                            continue
                        neon_mat = copy.deepcopy(canonical.TEXT_MATERIAL)
                        neon_mat["id"] = new_id()
                        neon_mat["name"] = f"neon_{method[:20]}"
                        neon_mat["content"] = json.dumps({
                            "text": method,
                            "styles": [{
                                "range": [0, len(method.encode('utf-16-le')) // 2],
                                "fill": {"content": {"solid": {"color": [1.0, 1.0, 1.0]}}, "alpha": 0.7},
                                "font": {"id": "", "path": ""},
                                "size": 10.0,
                            }],
                            "layer_weight": 1,
                            "effect": [],
                        }, ensure_ascii=False, separators=(",", ":"))
                        neon_color = neon_colors[len(overlay_materials) % len(neon_colors)]
                        neon_mat["global_alpha"] = 0.7
                        neon_mat["text_alpha"] = 1.0
                        neon_mat["font_size"] = 10.0
                        neon_mat["border_mode"] = 0
                        neon_mat["has_shadow"] = False
                        overlay_materials.append(neon_mat)
                        neon_seg = copy.deepcopy(canonical.TEXT_SEGMENT)
                        neon_seg["id"] = new_id()
                        neon_seg["material_id"] = neon_mat["id"]
                        neon_seg["render_index"] = 20001
                        neon_seg["track_render_index"] = 2
                        neon_seg["target_timerange"] = {
                            "start": it.start_us, "duration": it.duration_us}
                        neon_seg["source_timerange"] = {"start": 0, "duration": it.duration_us}
                        neon_seg["clip"]["transform"] = {"x": 0.0, "y": 0.0}
                        neon_seg["clip"]["scale"] = {"x": 1.0, "y": 1.0}
                        overlay_track["segments"].append(neon_seg)
            if overlay_track["segments"]:
                log.info(
                    "Overlays: %d segmentos (cuadrícula + neón) en pista overlay.",
                    len(overlay_track["segments"]),
                )
            else:
                overlay_track = None

        # materials: mantener TODAS las claves de la plantilla, remplazando
        # videos/audios/transitions y vaciando el resto (presentes en el
        # esqueleto como []).
        for key in materials:
            if key in ("videos", "audios", "transitions", "hsl"):
                continue
            if isinstance(materials[key], list):
                materials[key] = []
        materials["videos"] = photo_materials
        materials["audios"] = [audio_mat] + bgm_materials
        materials["transitions"] = transitions
        materials["texts"] = text_materials + overlay_materials
        if hsl_materials:
            materials["hsl"] = hsl_materials
        if adjust_materials:
            materials["effects"] = adjust_materials
        if sfx_materials:
            materials["audios"].extend(sfx_materials)

        # v1.7.0 — Assets DYC: animaciones, chroma, audios extra, overlays video.
        dyc_overlay_tracks: list[dict] = []
        if start_anim_mat is not None:
            materials.setdefault("material_animations", []).append(start_anim_mat)
        if end_anim_mat is not None:
            materials.setdefault("material_animations", []).append(end_anim_mat)
        if dyc_chroma_mat is not None:
            materials.setdefault("chroma", []).append(dyc_chroma_mat)
        if dyc_audio_intro_mat is not None:
            materials["audios"].append(dyc_audio_intro_mat)
        if dyc_audio_outro_mat is not None:
            materials["audios"].append(dyc_audio_outro_mat)
        if dyc_final_screen_mat is not None:
            materials["videos"].append(dyc_final_screen_mat)
        # FIX 7: registrar los materiales de video del CTA en materials.videos.
        for _cm in dyc_cta_video_mats:
            materials["videos"].append(_cm)
        # FIX 1 (bloque 6): un SOLO track de video CTA con intermedio + final
        # (la pantalla final ya NO está aquí: va en el track principal).
        dyc_cta_track: dict | None = None
        if dyc_suscribete_short_seg is not None:
            dyc_cta_segments.append(dyc_suscribete_short_seg)
        dyc_cta_segments.extend(dyc_suscribete_long_segs)
        if dyc_cta_segments:
            dyc_cta_segments.sort(
                key=lambda s: (s.get("target_timerange") or {}).get("start", 0))
            dyc_cta_track = copy.deepcopy(canonical.VIDEO_TRACK)
            dyc_cta_track["id"] = new_id()
            dyc_cta_track["type"] = "video"
            dyc_cta_track["flag"] = 2
            dyc_cta_track["visible"] = True          # FIX 7
            dyc_cta_track["segments"] = dyc_cta_segments
            dyc_overlay_tracks.append(dyc_cta_track)
            # FIX 7: render_index del CTA por encima del de las imágenes.
            main_render = max(
                (s.get("render_index", 0) or 0) for s in video_segments) if video_segments else 0
            cta_render = max(main_render + 1000, 11000)
            for s in dyc_cta_segments:
                s["render_index"] = cta_render
            log.info("Verificación CTA: track=%s visible=%s render_index=%d",
                     dyc_cta_track["id"], dyc_cta_track["visible"], cta_render)

        # 6) tracks: video(fotos) + [overlay] + [text] + audio + [sfx] + watermark.
        #    El orden en tracks[] marca el orden visual (último = arriba en UI).
        video_track = copy.deepcopy(canonical.VIDEO_TRACK)
        video_track["id"] = new_id()
        video_track["segments"] = video_segments
        audio_track = copy.deepcopy(canonical.AUDIO_TRACK)
        audio_track["id"] = new_id()
        audio_track["segments"] = audio_segs
        tracks = [video_track]
        # DYC: pistas de overlay (suscríbete, etc.)
        tracks.extend(dyc_overlay_tracks)
        if overlay_track is not None:
            tracks.append(overlay_track)
        if text_track is not None:
            tracks.append(text_track)
        # DYC: audio inicio y audio final en pistas separadas
        if dyc_audio_intro_mat is not None:
            intro_seg = self._build_audio_segment(
                content, dyc_audio_intro_mat["id"], dyc_audio_intro_mat["duration"],
                track_index=len(tracks) + 1)
            intro_track = copy.deepcopy(canonical.AUDIO_TRACK)
            intro_track["id"] = new_id()
            intro_track["segments"] = [intro_seg]
            tracks.append(intro_track)
        if dyc_audio_outro_mat is not None and dyc_audio_outro_seg is not None:
            # FIX 4: el segmento ya fue sincronizado con el agujero negro y lleva
            # el volumen -10 dB; aquí solo se le asigna la pista (NO se recrea,
            # porque target_us ya incluye la pantalla final).
            dyc_audio_outro_seg["track_render_index"] = len(tracks) + 1
            outro_track = copy.deepcopy(canonical.AUDIO_TRACK)
            outro_track["id"] = new_id()
            outro_track["segments"] = [dyc_audio_outro_seg]
            tracks.append(outro_track)
        tracks.append(audio_track)
        if sfx_track is not None:
            tracks.append(sfx_track)
        if config.WATERMARK_ENABLED:
            wm_mat, dyc_watermark_track = build_watermark_material_and_track(
                edit_profile.watermark_text, len(tracks), target_us,
                profile=edit_profile)
            materials["texts"].append(wm_mat)
            tracks.append(dyc_watermark_track)
        else:
            dyc_watermark_track = None

        # FIX 8 — Limpieza de tracks fantasma del template y reorden canonico.
        # IDs concretos de tracks fantasma que aparecen en la plantilla.
        GHOST_TRACK_IDS = (
            "1CF984E2-93DC-48ee-B140-87956E28818F",
            "B390B044-D222-4490-A681-7995AB074E95",
        )
        main_video_seg_mats: set[str] = {
            s.get("material_id", "") for s in video_segments}
        cleaned_tracks: list[dict] = []
        for track in tracks:
            tid = str(track.get("id", "")).upper()
            if tid in {g.upper() for g in GHOST_TRACK_IDS}:
                log.info("Limpieza: se elimina track fantasma %s", track.get("id"))
                continue
            if track.get("type") == "video" and track is not video_track:
                # Track de video NO principal: verificar si tiene segmentos
                # cuyo material_id ya esta en el track principal.
                seg_mats = {s.get("material_id", "") for s in track.get("segments", [])}
                if seg_mats & main_video_seg_mats:
                    log.info("Limpieza: se omite track video fantasma (%d segments)", len(track.get("segments", [])))
                    continue
            cleaned_tracks.append(track)
        tracks = cleaned_tracks

        # FIX 8 — Reorden canonico de tracks[]:
        #   1) video principal (imagenes sincronizadas)
        #   2) video CTA (intermedio + final, un solo track)
        #   3) texto subtitulos   4) texto watermark
        #   5) audio narracion    6) audio inicio/final (SFX)
        main_video_tracks: list[dict] = []
        cta_video_tracks: list[dict] = []
        subtitle_text_tracks: list[dict] = []
        watermark_text_tracks: list[dict] = []
        narration_audio_tracks: list[dict] = []
        sfx_audio_tracks: list[dict] = []
        other_tracks: list[dict] = []
        for t in tracks:
            ttype = t.get("type", "")
            if t is video_track:
                main_video_tracks.append(t)
            elif ttype == "video":
                cta_video_tracks.append(t)
            elif ttype == "text":
                if t is text_track:
                    subtitle_text_tracks.append(t)
                elif t is dyc_watermark_track:
                    watermark_text_tracks.append(t)
                else:
                    (watermark_text_tracks if t.get("flag") == 2
                     else subtitle_text_tracks).append(t)
            elif ttype == "audio":
                if t is audio_track:
                    narration_audio_tracks.append(t)
                else:
                    sfx_audio_tracks.append(t)
            else:
                other_tracks.append(t)
        tracks = (
            main_video_tracks
            + cta_video_tracks
            + subtitle_text_tracks
            + watermark_text_tracks
            + narration_audio_tracks
            + sfx_audio_tracks
            + other_tracks
        )
        content["tracks"] = tracks
        log.info(
            "Orden de pistas: %d principal · %d CTA · %d subtitulos · %d watermark "
            "· %d narracion · %d audio extra",
            len(main_video_tracks), len(cta_video_tracks), len(subtitle_text_tracks),
            len(watermark_text_tracks), len(narration_audio_tracks), len(sfx_audio_tracks),
        )

        # 6) duración raiz = duración total del audio (real del archivo si existe)
        content["duration"] = target_us
        content["update_time"] = _now_ms()

        # 7) escribir JSON en RAÍZ y en Timelines/<id>/ (CapCut lee ambos)
        self._check_cancelled()
        self._write_draft_content(self.new_dir, content)

        # 7b) v1.4.0 FIX v4 "imagina esto" (POST-PROCESO, FASE B/C/D): la
        # detección se hace sobre los SUBTÍTULOS YA GENERADOS (materials.texts
        # + su target_timerange) y no sobre escenas.txt, así que no hay que
        # emparejar escenas con segmentos: el rango del bloque de subtítulo ES
        # el rango que hay que ocultar en la imagen. Se ejecuta DESPUÉS de
        # escribir el JSON, sobre el proyecto ya completo, y por eso vive en su
        # propio módulo (`src/core/imagina_esto.py`) y no aquí: la generación
        # de arriba es exactamente la de v1.3.0.
        # Se le pasa el id de la pista de SUBTÍTULOS para que la del WATERMARK
        # (también type="text") nunca se toque. Si la verificación final falla,
        # el módulo lanza excepción y aquí se aborta la generación.
        if text_track is not None and edit_profile.enable_imagina_esto:
            try:
                aplicar(
                    self.new_dir,
                    track_text_id=text_track["id"],
                    timeline_id=self._timeline_id(content),
                )
            except ImaginaEstoError:
                shutil.rmtree(self.new_dir, ignore_errors=True)
                raise

        # 8) draft_meta_info.json (rutas coherentes con la carpeta padre)
        self._check_cancelled()
        meta = copy.deepcopy(self.meta)
        now_ms = _now_ms()
        meta["draft_id"] = str(uuid.uuid4())
        meta["draft_name"] = project_name
        meta["draft_fold_path"] = self.new_dir.as_posix()
        meta["draft_root_path"] = base.as_posix()
        meta["tm_draft_create"] = now_ms
        meta["tm_draft_modified"] = now_ms
        for k in ("tm_draft_last_modified", "tm_draft_last_open"):
            if k in meta:
                meta[k] = now_ms
        (self.new_dir / META_JSON).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 9) validacion post-generacion: nunca dejar un proyecto vacío
        self._check_cancelled()
        final = json.loads((self.new_dir / CONTENT_JSON).read_text(encoding="utf-8"))
        n_tracks = len(final.get("tracks") or [])
        n_segments = sum(
            len(t.get("segments") or []) for t in (final.get("tracks") or [])
        )
        if n_tracks == 0 or n_segments == 0:
            shutil.rmtree(self.new_dir, ignore_errors=True)
            raise CapCutProjectError(
                "Proyecto generado vacío (sin pistas o sin segmentos); se eliminó."
            )
        log.info("Proyecto generado con %d pistas / %d segmentos.",
                 n_tracks, n_segments)

        # 10) copia del JSON generado a backups para inspeccion + esquema full
        try:
            self.dump_full_schema()
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo volcar schema_plantilla_full.json (%s)", exc)
        try:
            bak = self.backup_originals()
            shutil.copy2(self.new_dir / CONTENT_JSON, bak / f"{CONTENT_JSON}.generado")
            shutil.copy2(self.new_dir / META_JSON, bak / f"{META_JSON}.generado")
        except Exception as exc:  # noqa: BLE001 - copia de inspeccion no critica
            log.warning("No se pudo copiar JSON generado a backups (%s)", exc)

        log.info("PROYECTO GENERADO: %s", self.new_dir)
        return self.new_dir

    def _write_draft_content(self, project_dir: Path, content: dict) -> None:
        """Escribe draft_content.json en la raiz y en Timelines/<id>/ (si existe)."""
        text = json.dumps(content, ensure_ascii=False, indent=2)
        (project_dir / CONTENT_JSON).write_text(text, encoding="utf-8")
        timeline_id = self._timeline_id(content)
        if timeline_id:
            tdir = project_dir / "Timelines" / timeline_id
            if tdir.is_dir():
                (tdir / CONTENT_JSON).write_text(text, encoding="utf-8")
                log.info("draft_content.json escrito también en %s", tdir)
        log.info("draft_content.json generado con %d pistas de foto + 1 de audio.",
                 len(content.get("tracks") or []))


# TODO Watermark no carga en preview: bug de CapCut/caché, diagnóstico independiente.
# v1.7.0 FIX 6: patrón de transiciones verificado contra draft de referencia
# (segmentos pegados + is_overlap:true + extra_material_refs en el segmento ANTERIOR).