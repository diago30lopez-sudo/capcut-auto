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
import json
import logging
import random
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image

from src.core import capcut_canonical as canonical
from src.core import config
from src.core.subtitles import (
    SUBTITLE_KEYWORDS,
    build_subtitle_track,
    build_watermark_material_and_track,
)
from src.core.timeline_builder import (
    GenerationCancelled,
    TimelineItem,
    measure_audio_duration_us,
    redistribute_gap,
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
    {"hsl_color_type": 2, "hue": 0.0, "saturation": 0.15, "lightness": 0.05,
     "custom_color": "#FFA227"},    # Naranja
    {"hsl_color_type": 5, "hue": -0.15, "saturation": 0.20, "lightness": -0.10,
     "custom_color": "#00E5FF"},    # Cian
    {"hsl_color_type": 6, "hue": -0.15, "saturation": 0.20, "lightness": -0.10,
     "custom_color": "#2D6BFF"},    # Azul
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


def _color_keyframes(duration_us: int) -> list[dict]:
    """Color grading por imagen como keyframes estáticos (un solo keyframe de
    valor constante = ajuste fijo, no animación). FASE 3: cada parámetro del
    rango de la guía se aleatoriza por escena dentro de COLOR_GRADE_RANGES; los
    fijos (Exposición, Destacados, Sombras, Temperatura) usan el valor exacto."""
    if not COLOR_GRADE_ENABLED:
        return []
    entries = []
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

    # -- helpers de construccion -------------------------------------------------
    def _timeline_id(self, content: dict) -> str | None:
        """Id del timeline raiz = content['id']; el mismo que nombra la carpeta
        Timelines/<id>/ (que CapCut tambien lee)."""
        return content.get("id") or None

    def _build_photo_material(self, content: dict, abs_path: str, width: int,
                              height: int, duration_us: int, name: str) -> dict:
        mat = copy.deepcopy(canonical.PHOTO_MATERIAL)
        mat["id"] = new_id()
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
                             extra_refs: list | None = None) -> dict:
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
        # 2. Los keyframes de zoom (aumento del 10% o 15%) parten EXACTAMENTE de
        #    la escala 'cover' de ESTA imagen (primer keyframe = zoom_base =
        #    cover_scale, ultimo = cover_scale * zoom_mult), asi que la escala
        #    final SIEMPRE cubre el lienzo sin bordes negros en ningun momento.
        # 3. Color grading (FASE 3, 10 parámetros con rango por escena).
        # 4. Position (FASE 3): paneo Ken Burns y/o camera shake.
        kfs = _zoom_keyframes(duration_us, zoom_mult, base=zoom_base)
        kfs.extend(_color_keyframes(duration_us))
        kfs.extend(_position_entries(position_points))
        seg["common_keyframes"] = kfs
        # FASE 3: HSL por canal activado + referencias a materials.hsl.
        seg["enable_hsl"] = bool(enable_hsl)
        seg["extra_material_refs"] = list(extra_refs or [])
        return seg

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
                             volume: float = AUDIO_GAIN_LINEAR) -> dict:
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
        real); CapCut reutiliza esa caché, no descarga nada nuevo."""
        effect_path = (
            Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache"
            / "effect" / HSL_EFFECT_ID / HSL_EFFECT_HASH
        ).as_posix()
        return {
            "id": new_id(),
            "constant_material_id": new_id(),
            "hsl_color_type": channel["hsl_color_type"],
            "hue": channel["hue"],
            "saturation": channel["saturation"],
            "lightness": channel["lightness"],
            "interacting": True,
            "version": "1",
            "path": effect_path,
            "type": "hsl",
            "lumi_hub_path": effect_path + "/lumi_hub_path",
            "custom_color": channel["custom_color"],
            "resource_id": "",
            "source_platform": 0,
        }

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
        new_dir = base / project_name
        if new_dir.exists():
            raise CapCutProjectError(
                f"Ya existe un proyecto llamado '{project_name}' en {base}"
            )

        def _check_cancelled() -> None:
            if cancel_event is not None and cancel_event.is_set():
                log.info("Generación cancelada por el usuario.")
                shutil.rmtree(new_dir, ignore_errors=True)
                raise GenerationCancelled("Generación cancelada por el usuario.")

        _check_cancelled()

        # 1) clonado de la plantilla
        log.info("Proyecto se creará en: %s", new_dir)
        shutil.copytree(self.template_dir, new_dir)
        _check_cancelled()

        # 2) deep-copy: el JSON final es superconjunto del de la plantilla
        content = copy.deepcopy(self.content)
        materials = content.setdefault("materials", {})

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

        canvas_w, canvas_h = _canvas_size(content)

        # 3) materials.videos (fotos) + segments de la pista de video.
        #    Se referencian las rutas ABSOLUTAS de los archivos fuente (mismo
        #    formato que el draft real 0921: D:/.../escenas 2/xxx.jpg), nunca
        #    rutas relativas que CapCut no resuelve y muestra como "Media Not Found".
        photo_materials: list[dict] = []
        video_segments: list[dict] = []
        hsl_materials: list[dict] = []
        prev_end = 0
        for it in items:
            _check_cancelled()
            if it.image_path is None:
                log.warning("Escena %d sin imagen; se omite material.", it.order)
                continue

            # Evita segmentos de duracion 0 (CapCut no muestra bien 0 us)
            start_us = it.start_us if it.duration_us > 0 else prev_end
            duration_us = it.duration_us if it.duration_us > 0 else 1_000_000
            prev_end = start_us + duration_us

            width, height = _image_size(it.image_path)
            abs_path = it.image_path.resolve().as_posix()

            # Punto 2: escala 'cover' INDIVIDUAL por imagen (cubre el lienzo sin
            # deformar). Se analiza cada imagen con sus propias dimensiones: una
            # vertical se amplía mucho; una 16:9 queda cubierta con escala 1.0.
            cover_scale = _cover_scale(canvas_w, canvas_h, width, height)
            # Punto 3: zoom aleatorio por imagen (10% o 15%) al final de la misma,
            # calculado SIEMPRE sobre su escala base individual (cover_scale).
            zoom_mult = random.choice(ZOOM_END_OPTIONS)

            # FASE 3 — paneo Ken Burns opcional (60% de las escenas) y camera
            # shake 0.2s en las escenas con palabras de ACCIÓN (SUBTITLE_KEYWORDS
            # sobre el texto de la subescena / la escena).
            action = _has_action_keyword(it.scene_text) or _has_action_keyword(it.segment_text)
            pan_dx = pan_dy = 0.0
            if action:
                if random.random() < PAN_RATIO:
                    amp = random.uniform(*PAN_AMPLITUDE)
                    pan_dx = round(random.choice((-1, 1)) * amp, 4)
                    pan_dy = round(random.choice((0, 0, 1, -1)) * amp * 0.5, 4)
            else:
                if random.random() < PAN_RATIO:
                    amp = random.uniform(*PAN_AMPLITUDE)
                    pan_dx = round(random.choice((-1, 1)) * amp, 4)
                    pan_dy = round(random.choice((-1, 1)) * amp * 0.5, 4)
            if pan_dx or pan_dy or action:
                if action:
                    shake_amp_x = random.uniform(*SHAKE_AMPLITUDE)
                    shake_amp_y = shake_amp_x * 0.7
                    position_points = _shake_points(
                        duration_us, shake_amp_x, shake_amp_y, pan_dx, pan_dy)
                else:
                    position_points = _pan_points(duration_us, pan_dx, pan_dy)
            else:
                position_points = None
            # Boost de zoom inicial solo en escenas con shake (da overscan desde
            # t=0 para que el temblor no destape nunca los bordes del lienzo).
            # TAREA 2: la escala base de los keyframes es SIEMPRE la escala
            # 'cover' INDIVIDUAL de ESTA imagen (max/min), nunca 1.0: primero se
            # fija clip.scale=cover y los keyframes de zoom (10/15%) parten de
            # esa cover (cover → cover*mult) para que NINGUNA imagen, sea cual
            # sea su proporcion, quede con bordes negros.
            zoom_base = cover_scale * (SHAKE_ZOOM_BOOST if action else 1.0)

            # FASE 3 — HSL por canal (guía): cada segmento referencia sus
            # materials.hsl (Naranja + Cian + Azul), mismo mecanismo que el
            # draft real del usuario.
            refs: list[str] = []
            if HSL_ENABLED:
                for channel in HSL_CHANNELS:
                    mat = self._hsl_material(channel)
                    hsl_materials.append(mat)
                    refs.append(mat["id"])

            log.info(
                "Escena %02d · %s: %dx%d → cover=%.3f · zoom=+%.0f%% · %s%s%s",
                it.order, it.image_path.name, width, height,
                cover_scale, (zoom_mult - 1.0) * 100,
                "shake+pan" if action else ("pan" if position_points is not None else "fija"),
                (f" ({pan_dx},{pan_dy})" if position_points is not None else ""),
                " · hsl" if HSL_ENABLED else "",
            )

            mat = self._build_photo_material(
                content, abs_path, width, height, duration_us, it.image_path.stem)
            photo_materials.append(mat)
            video_segments.append(
                self._build_photo_segment(
                    content, mat["id"], start_us, duration_us, cover_scale, zoom_mult,
                    zoom_base=zoom_base, position_points=position_points,
                    enable_hsl=HSL_ENABLED, extra_refs=refs))

        # Transiciones: se aplican sobre el 98% de los bordes internos entre
        # imágenes (el 2% restante queda con corte limpio). Cada transición se
        # referencia desde extra_material_refs del segmento que RECIBE el corte,
        # exactamente igual que en el draft 0921; los timeranges no se tocan.
        # FASE 3: se ANEXA el id de la transición a los refs ya presentes (HSL).
        transitions: list[dict] = []
        boundaries = len(video_segments) - 1
        if boundaries > 0:
            keep = int(round(boundaries * TRANSITION_RATIO))
            skip_count = boundaries - keep
            skips: set[int] = set()
            if skip_count:
                skips = set(random.sample(range(boundaries), skip_count))
            for b in range(boundaries):
                if b in skips:
                    continue
                mat = self._build_transition_material(random.choice(TRANSITIONS))
                transitions.append(mat)
                video_segments[b + 1]["extra_material_refs"] = (
                    list(video_segments[b + 1].get("extra_material_refs") or []) + [mat["id"]])
            log.info(
                "Transiciones: %d/%d bordes (%d%%); %d corte(s) limpio(s).",
                len(transitions), boundaries,
                round(100 * TRANSITION_RATIO), skip_count,
            )

        # 4) materials.audios + pista de audio (ruta absoluta, sin recortar)
        audio_mat = self._build_audio_material(
            content, audio_src.resolve().as_posix(), target_us, audio_src.stem)
        # track_render_index del audio: 1 sin subtítulos, 2 si la pista text
        # va en medio (mismo orden que el draft 0921: video[0], text[1], audio[2]).
        audio_segs = [self._build_audio_segment(
            content, audio_mat["id"], target_us,
            track_index=2 if subtitle_srt is not None else 1)]

        # FASE 3 — BGM opcional con ducking: VO a +6 dB, BGM a -20 dB (volumen
        # lineal 0.1). Lógica lista; solo se activa si se pasa bgm_path.
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
            audio_segs.append(self._build_audio_segment(
                content, bgm_mat["id"], bgm_dur,
                track_index=2 if subtitle_srt is not None else 1,
                volume=BGM_GAIN_LINEAR))
            log.info("BGM: %s a %.0f dB (ducking bajo la VO a +%.0f dB).",
                     Path(bgm_path).name, BGM_GAIN_DB, AUDIO_GAIN_DB)
        else:
            log.info("BGM: sin ruta (o no existe); ducking -20 dB omitido.")

        # FASE 3 — SFX: sin carpeta configurada se omite con aviso; si sfx_dir
        # trae audio, se coloca un SFX corto en cada corte interno (impacto).
        sfx_track: dict | None = None
        sfx_materials: list[dict] = []
        if sfx_dir is not None and Path(sfx_dir).is_dir():
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

        # 5) materials.texts + pista de subtitulos (opcional). La pista text va
        #    ENTRE video y audio (track_render_index 1), como en el draft 0921,
        #    para que el texto quede sobre las imágenes y debajo de la mezcla
        #    de sonido. Cada fragmento de 2-5 palabras = un segmento.
        text_track: dict | None = None
        text_materials: list[dict] = []
        if subtitle_srt is not None and Path(subtitle_srt).is_file():
            text_track, text_materials, text_segments = (
                build_subtitle_track(subtitle_srt, track_render_index=1)
            )
            log.info(
                "Subtítulos: %d materiales · %d segmentos (track text).",
                len(text_materials), len(text_segments),
            )
        else:
            log.info("Subtítulos: sin SRT (o ruta no encontrada); se omite la pista text.")

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
        materials["texts"] = text_materials
        if hsl_materials:
            materials["hsl"] = hsl_materials
        if sfx_materials:
            materials["audios"].extend(sfx_materials)

        # 6) tracks: video(fotos) + [text] + audio + [sfx] generados (los
        #    segmentos ya llevan su track_render_index: video=0, text=1, audio=1
        #    o 2, sfx=2 o 3; la posición en tracks[] marca el orden visual).
        video_track = copy.deepcopy(canonical.VIDEO_TRACK)
        video_track["id"] = new_id()
        video_track["segments"] = video_segments
        audio_track = copy.deepcopy(canonical.AUDIO_TRACK)
        audio_track["id"] = new_id()
        audio_track["segments"] = audio_segs
        # Pistas de la obra en orden: video (0), subtitulos (1 si los hay),
        # audio (2/1), sfx (3/2). El watermark (si esta activo,
        # config.WATERMARK_ENABLED) va al final en su propia pista, separado
        # de la de subtitulos.
        tracks = [video_track]
        if text_track is not None:
            tracks.append(text_track)
        tracks.append(audio_track)
        if sfx_track is not None:
            tracks.append(sfx_track)
        if config.WATERMARK_ENABLED:
            wm_mat, wm_track = build_watermark_material_and_track(
                config.WATERMARK_TEXT, len(tracks), target_us)
            materials["texts"].append(wm_mat)
            tracks.append(wm_track)
        content["tracks"] = tracks

        # 6) duración raiz = duración total del audio (real del archivo si existe)
        content["duration"] = target_us
        content["update_time"] = _now_ms()

        # 7) escribir JSON en RAÍZ y en Timelines/<id>/ (CapCut lee ambos)
        _check_cancelled()
        self._write_draft_content(new_dir, content)

        # 8) draft_meta_info.json (rutas coherentes con la carpeta padre)
        _check_cancelled()
        meta = copy.deepcopy(self.meta)
        now_ms = _now_ms()
        meta["draft_id"] = str(uuid.uuid4())
        meta["draft_name"] = project_name
        meta["draft_fold_path"] = new_dir.as_posix()
        meta["draft_root_path"] = base.as_posix()
        meta["tm_draft_create"] = now_ms
        meta["tm_draft_modified"] = now_ms
        for k in ("tm_draft_last_modified", "tm_draft_last_open"):
            if k in meta:
                meta[k] = now_ms
        (new_dir / META_JSON).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 9) validacion post-generacion: nunca dejar un proyecto vacío
        _check_cancelled()
        final = json.loads((new_dir / CONTENT_JSON).read_text(encoding="utf-8"))
        n_tracks = len(final.get("tracks") or [])
        n_segments = sum(
            len(t.get("segments") or []) for t in (final.get("tracks") or [])
        )
        if n_tracks == 0 or n_segments == 0:
            shutil.rmtree(new_dir, ignore_errors=True)
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
            shutil.copy2(new_dir / CONTENT_JSON, bak / f"{CONTENT_JSON}.generado")
            shutil.copy2(new_dir / META_JSON, bak / f"{META_JSON}.generado")
        except Exception as exc:  # noqa: BLE001 - copia de inspeccion no critica
            log.warning("No se pudo copiar JSON generado a backups (%s)", exc)

        log.info("PROYECTO GENERADO: %s", new_dir)
        return new_dir

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