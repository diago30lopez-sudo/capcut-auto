"""Subtitulos dinamicos al estilo de la guia "Plotinary".

Convierte un archivo .srt en la pista de texto de CapCut:

1. PROCESAMIENTO: cada cue del SRT se divide en fragmentos de 2-5 palabras
   (regla de oro para moviles) y el tiempo del cue se reparte PROPORCIONALMENTE
   al numero de palabras de cada fragmento.
2. ESTILO (valores EXACTOS de la captura de CapCut): fuente
   montserrat/bebas/impact si estan en el sistema (si no, SystemFont), tamano
   12, Negrita + Italica activos, espaciado de caracteres 1, texto blanco puro
   (palabras clave en amarillo #FFD700), trazo negro 42%, sombra negra con
   desenfoque 20% y distancia 15, posicion Y = -795 (normalizada al alto del
   canvas 1080: -795/1080).
3. ANIMACION pop-up: los fragmentos entran con escalas 0.8 -> 1.0 en 0.1 s
   mediante keyframes de escala (KFTypeScaleX/KFTypeScaleY) y DESPUES se
   mantienen ESTATICOS en su escala base (1.0) durante toda la duracion del
   texto (no hay zoom continuo).

El `content` del material de texto es un JSON dentro de un string con un
`styles[]`: cada palabra lleva su range [inicio, fin) en offsets UTF-16 LE
(para texto espanol sin emojis el offset de caracter == offset en bytes LE).
"""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path

from src.core import capcut_canonical as canonical
from src.core.timeline_builder import parse_srt

log = logging.getLogger("capcutauto")


def _new_id() -> str:
    """Id unico hexadecimal de 32 chars (formato usado por CapCut). Local para
    evitar el import circular capcut_project <-> subtitles."""
    import uuid
    return uuid.uuid4().hex.upper()

# Palabras "fuertes" de accion/eno de la guia: se resaltan en amarillo.
SUBTITLE_KEYWORDS = frozenset({
    "ataque", "ataca", "golpe", "explos", "bomba", "peligro", "muerte",
    "poder", "poderosa", "invencible", "imposible", "traicion", "secreto",
    "revel", "final", "nunca", "siempre", "guerra", "venganza", "heroe",
    "villano", "salvar", "sacrificio", "memoria", "renacer", "renace",
})

# Palette de la guia.
KEYWORD_COLOR = [1.0, 0.8431373, 0.0]      # #FFD700
BASE_COLOR = [1.0, 1.0, 1.0]               # blanco puro

# Posicion vertical del centro del texto. En el panel de CapCut la app muestra
# "Y = -795" (px sobre el centro de un lienzo 1080 de alto); el draft lo guarda
# NORMALIZADO por la altura del canvas: -795/1080 = -0.7361... (signo NEGATIVO
# sube el texto, igual que el draft real del usuario: -0.7359683794466405).
SUBTITLE_Y = -795.0 / 1080.0

# Espaciado de caracteres EXACTO = 1 en la UI de CapCut. CapCut guarda el
# valor NORMALIZADO en el JSON: 1.0 en el JSON se muestra como "20" en el
# panel; 0.05 se muestra como "1" (mismo default del draft real #1 Nexus
# Paradoja).
FONT_SIZE = 12.0           # content.styles[].size
TEXT_SIZE = 30             # material.text_size
LETTER_SPACING = 0.05      # material.letter_spacing (= UI "1")
STYLE_BOLD = True          # Negrita
STYLE_ITALIC = True        # Italica

# Trazo (stroke): grosor EXACTO de 40 en la UI de CapCut = border_width 0.4
# normalizado (nuestros 0.42 previos aparecian como "42" en el panel).
# Color negro puro, opacidad total. border_mode 1 es el "checkbox" del trazo
# en CapCut (0 = desactivado); con 1 la casilla "Trazo" queda activada. El
# color/grosor se reflejan TAMBIEN en cada estilo del content (strokes[]) que
# es lo que el motor de render consume. Sombra: desenfoque 20% =
# shadow_smoothing 0.2, distancia 15 = shadow_distance.
BORDER_ALPHA = 1.0
BORDER_WIDTH = 0.4         # material.border_width (= UI "40")
BORDER_COLOR = "#000000"
BORDER_MODE = 1            # trazo ACTIVADO en la UI de CapCut
STROKE_MODE = 0            # modo del trazo en el content (solid normal)
SHADOW_ALPHA = 1.0
SHADOW_SMOOTHING = 0.2
SHADOW_DISTANCE = 15.0

# Animacion pop-up: el fragmento arranca al 80% de tamano y llega al 100%
# en 0.1 s (100000 us). Mismo sistema de coordenadas que clip.scale (1=100%).
POPUP_START_SCALE = 0.8
POPUP_RAMP_US = 100_000

# Minimo/maximo de palabras por fragmento (regla de oro para moviles).
_MIN_WORDS = 2
_MAX_WORDS = 5


def _utf16_len(text: str) -> int:
    """Longitud del texto en unidades UTF-16 (offsets de range de CapCut)."""
    return len(text.encode("utf-16-le")) // 2


FONT_CANDIDATES = (
    # Montserrat / Bebas Neue / Impact: si estan instaladas se usan, si no se
    # cae a la SystemFont de CapCut (la que usa el draft real 0921).
    Path("C:/Windows/Fonts/Montserrat-SemiBold.ttf"),
    Path("C:/Windows/Fonts/BebasNeue-Regular.ttf"),
    Path("C:/Windows/Fonts/impact.ttf"),
)


def resolve_subtitle_font() -> dict:
    """Resuelve la fuente de los subtitulos: montserrat/bebas/impact si estan
    en el sistema; si no, la SystemFont de CapCut (mismo que el draft 0921).
    Devuelve {'path':..., 'name':..., 'title':...}."""
    for p in FONT_CANDIDATES:
        if p.is_file():
            return {"path": p.as_posix(), "name": p.stem, "title": p.stem}
    for app in sorted(
        (Path.home() / "AppData" / "Local" / "CapCut" / "Apps").glob(
            "*/Resources/Font/SystemFont/en.ttf"),
        reverse=True,
    ):
        return {"path": app.as_posix(), "name": "", "title": "none"}
    return {"path": "", "name": "", "title": "none"}


def clean_srt_text(raw: str) -> str:
    """Limpia una linea de SRT: quita tags HTML (<i>,<b>,<font...>) y normaliza
    espacios. Mantiene la puntuacion (necesaria para los range offsets)."""
    text = re.sub(r"<[^>]+>", "", raw or "")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()


def split_into_fragments(text: str) -> list[list[str]]:
    """Divide el texto en fragmentos de 2-5 palabras (regla de oro).

    Si la linea tiene <= 5 palabras devuelve un solo fragmento; si no, agrupa
    de a bloques aleatorios entre 2 y 5 que suman el total (nunca deja solo 1
    palabra al final: la ultima palabra se suma al bloque anterior)."""
    words = text.split()
    if not words:
        return []
    if len(words) <= _MAX_WORDS:
        return [words]
    if len(words) == 6:
        # 3+3 (evita dejar 1 sola palabra).
        return [words[:3], words[3:]]
    fragments: list[list[str]] = []
    i = 0
    while i < len(words):
        remaining = len(words) - i
        if remaining <= _MAX_WORDS:
            fragments.append(words[i:])
            break
        if remaining == 6:
            fragment = words[i:i + 3]
            i += 3
        else:
            size = min(_MAX_WORDS, remaining - 1)
            size = max(size, _MIN_WORDS)
            fragment = words[i:i + size]
            i += size
        fragments.append(fragment)
    return fragments


def build_text_content(
    text: str,
    font_path: str,
    font_size: float,
) -> str:
    """Construye el `content` JSON (string) con un estilo POR PALABRA.

    El `range` de cada estilo es [inicio, fin) en offsets UTF-16 dentro de
    `text`. Las palabras reservadas (SUBTITLE_KEYWORDS) van en amarillo #FFD700;
    el resto en blanco puro. Los offsets se calculan con _utf16_len para no
    desalinear con acentos."""
    def normalize_word(w: str) -> str:
        return w.lower().strip("¿?¡!,.;:()\"«»")

    styles: list[dict] = []
    cursor = 0
    for word in text.split():
        end = cursor + _utf16_len(word)
        color = KEYWORD_COLOR if normalize_word(word) in SUBTITLE_KEYWORDS else BASE_COLOR
        styles.append({
            "range": [cursor, end],
            "fill": {"content": {"solid": {"color": color}}},
            "font": {"id": "", "path": font_path},
            "size": font_size,
            "bold": STYLE_BOLD,
            "italic": STYLE_ITALIC,
            "underline": False,
            "strokes": [{
                "content": {"render_type": "solid", "solid": {"color": [0.0, 0.0, 0.0]}},
                "width": BORDER_WIDTH,
                "mode": STROKE_MODE,
            }],
        })
        cursor = end + 1  # el espacio entre palabras
    return json.dumps({
        "text": text,
        "styles": styles,
        "layer_weight": 1,
        "effect": [],
    }, ensure_ascii=False, separators=(",", ":"))


def build_text_material(text: str) -> dict:
    """Material de texto con el estilo de la guia (trazo negro, sombra negra,
    fuente resuelta, color blanco base + keywords amarillos)."""
    font = resolve_subtitle_font()
    mat = copy.deepcopy(canonical.TEXT_MATERIAL)
    mat["id"] = _new_id()
    mat["name"] = text[:40]
    mat["content"] = build_text_content(text, font["path"], FONT_SIZE)
    mat["text_color"] = "#FFFFFF"
    mat["text_alpha"] = 1.0
    mat["font_path"] = font["path"]
    mat["font_name"] = font["name"]
    mat["font_title"] = font["title"]
    mat["font_size"] = FONT_SIZE
    mat["text_size"] = TEXT_SIZE
    mat["letter_spacing"] = LETTER_SPACING
    mat["alignment"] = 1  # centro
    mat["line_feed"] = 1
    mat["line_spacing"] = 0.02
    mat["line_max_width"] = 0.82
    mat["check_flag"] = 7
    # Trazo negro ACTIVADO (casilla "Trazo" en la UI) con grosor 40 = 0.4.
    mat["border_mode"] = BORDER_MODE
    mat["border_alpha"] = BORDER_ALPHA
    mat["border_color"] = BORDER_COLOR
    mat["border_width"] = BORDER_WIDTH
    # Sombra negra 100% / desenfoque 20% / distancia 15.
    mat["has_shadow"] = True
    mat["shadow_alpha"] = SHADOW_ALPHA
    mat["shadow_smoothing"] = SHADOW_SMOOTHING
    mat["shadow_distance"] = SHADOW_DISTANCE
    mat["shadow_color"] = "#000000"
    mat["shadow_angle"] = -45.0
    return mat


def _popup_keyframes() -> list[dict]:
    """Keyframes de la animacion pop-up: el texto entra del 80% al 100% en
    0.1 s (escalas X e Y). Un keyframe inicial deja `clip.scale` desactivado;
    CapCut interpola desde el primer keyframe."""
    kf0 = {
        "id": _new_id(),
        "curveType": "Line",
        "time_offset": 0,
        "left_control": {"x": 0.0, "y": 0.0},
        "right_control": {"x": 0.0, "y": 0.0},
        "values": [POPUP_START_SCALE],
        "string_value": "",
        "graphID": "",
    }
    kf1 = {
        "id": _new_id(),
        "curveType": "Line",
        "time_offset": POPUP_RAMP_US,
        "left_control": {"x": 0.0, "y": 0.0},
        "right_control": {"x": 0.0, "y": 0.0},
        "values": [1.0],
        "string_value": "",
        "graphID": "",
    }
    return [
        {"id": _new_id(), "material_id": "", "property_type": "KFTypeScaleX",
         "keyframe_list": [kf0, kf1]},
        {"id": _new_id(), "material_id": "", "property_type": "KFTypeScaleY",
         "keyframe_list": [kf0, kf1]},
    ]


def build_text_segment(mat_id: str, start_us: int, duration_us: int,
                       track_render_index: int) -> dict:
    """Segmento de una pista de subtitulos, posicionado en centro-inferior y
    con la animacion pop-up de escala."""
    seg = copy.deepcopy(canonical.TEXT_SEGMENT)
    seg["id"] = _new_id()
    seg["material_id"] = mat_id
    seg["render_index"] = 14000
    seg["track_render_index"] = track_render_index
    seg["target_timerange"] = {"start": start_us, "duration": duration_us}
    seg["source_timerange"] = {"start": 0, "duration": duration_us}
    seg["clip"]["transform"] = {"x": 0.0, "y": SUBTITLE_Y}
    seg["clip"]["scale"] = {"x": 1.0, "y": 1.0}
    seg["common_keyframes"] = _popup_keyframes()
    return seg


def build_subtitle_track(
    srt_path: str | Path,
    track_render_index: int = 1,
) -> tuple[dict | None, list[dict], list[dict]]:
    """Parsea el SRT y construye (track, texts_materials, text_segments).

    Cada cue se divide en fragmentos de 2-5 palabras; el tiempo del cue se
    reparte PROPORCIONALMENTE al numero de palabras de cada fragmento (el
    ultimo ocupa siempre el resto del cue). Devuelve la estructura completa
    lista para insertar en `content["tracks"]` y materials["texts"]."""
    cues = parse_srt(Path(srt_path))
    if not cues:
        return None, [], []

    materials: list[dict] = []
    segments: list[dict] = []
    for start_s, end_s, text_raw in cues:
        text = clean_srt_text(text_raw)
        if not text:
            continue
        fragments = split_into_fragments(text)
        if not fragments:
            continue
        cue_start_us = int(round(start_s * 1_000_000))
        cue_end_us = int(round(end_s * 1_000_000))
        cue_dur_us = max(cue_end_us - cue_start_us, 1)
        total_words = sum(len(f) for f in fragments)
        cursor_us = cue_start_us
        for i, fragment in enumerate(fragments):
            mat = build_text_material(" ".join(fragment))
            materials.append(mat)
            if i == len(fragments) - 1:
                # Ultimo fragmento: ocupa exactamente el resto del cue.
                frag_dur_us = max(cue_end_us - cursor_us, 1)
            else:
                frag_dur_us = max(
                    int(round(cue_dur_us * len(fragment) / total_words)), 1)
            segments.append(build_text_segment(
                mat["id"], cursor_us, frag_dur_us, track_render_index))
            cursor_us += frag_dur_us

    track = copy.deepcopy(canonical.TEXT_TRACK)
    track["id"] = _new_id()
    track["segments"] = segments
    track["is_default_name"] = True
    return track, materials, segments
