"""Configuracion central y rutas de la aplicacion CapCut Auto."""

import json
import logging
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

CACHE_DIR = ROOT_DIR / "cache"
LOGS_DIR = ROOT_DIR / "logs"
BACKUPS_DIR = ROOT_DIR / "backups"
BIN_DIR = ROOT_DIR / "bin"
MODELS_DIR = ROOT_DIR / "models"
SCHEMA_FILE = LOGS_DIR / "schema_plantilla.json"
SCHEMA_FULL_FILE = LOGS_DIR / "schema_plantilla_full.json"
APP_LOG_FILE = LOGS_DIR / "app.log"

USER_CONFIG_FILE = ROOT_DIR / "config_user.json"

DRAFT_CONTENT_FILE = "draft_content.json"
DRAFT_META_FILE = "draft_meta_info.json"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

DEFAULT_USER_CONFIG = {
    "capcut_drafts_dir": "",
    "last_template_name": "",
    "last_video_dir": "",
    # FASE 2 — archivo .srt elegido para los subtítulos (nombre, no ruta).
    "last_srt_name": "",
}

# --- Forced alignment con CrispASR (binario + modelo espanol GGUF, Q4_K) ----
CRISPASR_VERSION = "v0.8.35"
CRISPASR_BASE_URL = "https://github.com/CrispStrobe/CrispASR/releases/download"
CRISPASR_ZIP_NAME = "crispasr-windows-x86_64-cpu.zip"
CRISPASR_EXE = BIN_DIR / "crispasr.exe"

# URLs de descarga usadas por src/core/bootstrap.ensure_dependencies() (primer
# uso): el .zip oficial de CrispASR (contiene crispasr.exe, crispasr-quantize,
# openblas.dll, LICENSE y THIRD_PARTY_NOTICES.txt) y el modelo espanol GGUF.
CRISPASR_DOWNLOAD_URL = f"{CRISPASR_BASE_URL}/{CRISPASR_VERSION}/{CRISPASR_ZIP_NAME}"

ALIGN_MODEL_REPO = "cstr/stt-es-fastconformer-hybrid-ctc-large-GGUF"
ALIGN_MODEL_FILENAME = "stt-es-fastconformer-hybrid-ctc-large-q4_k.gguf"
ALIGN_MODEL_PATH = MODELS_DIR / ALIGN_MODEL_FILENAME
MODEL_DOWNLOAD_URL = (
    f"https://huggingface.co/{ALIGN_MODEL_REPO}/resolve/main/{ALIGN_MODEL_FILENAME}"
)

# --- Canvas del proyecto (1920x1080 horizontal) ------------------------------
# CapCut multiplica transform.x por el ancho COMPLETO del canvas y transform.y
# por el alto COMPLETO: la escala UI = JSON * (ancho/alto). NOTA: el numero que
# aparece en el panel de posicion de CapCut es el resultado de multiplicar el
# JSON por el canvas completo. Escalas confirmadas empiricamente (v1.4.0):
#   - transform.x:  JSON = UI_X / 1920   (UI -1098 -> -0.571875)
#   - transform.y:  JSON = UI_Y / 1080   (UI 896 -> 0.8296296)
#   - subtitle  y:  JSON = UI_Y / 1080   (UI -660 -> -0.6111111)
#   - strokes[0].width / border_width:   UI = JSON * 500 (UI 30 -> 0.06)
#   - text_alpha (opacidad):             UI = text_alpha * fill.alpha * 100
#     (40% con fill.alpha 1.0 -> text_alpha 0.40; sin alpha en el fill CapCut
#      aplica ~0.75 y 0.40 se muestra como 30%).
#   - letter_spacing:                    JSON = UI * 0.05 (UI 2 -> 0.10)
CANVAS_WIDTH = 1920
CANVAS_HEIGHT = 1080
HALF_W = CANVAS_WIDTH / 2.0   # 960.0
HALF_H = CANVAS_HEIGHT / 2.0  # 540.0

# --- Marca de agua persistente (solo config; no tocar la UI) -----------------
# Texto tenue tipo marca de agua que cubre todo el video. Con WATERMARK_ENABLED
# en False no se anade nada al proyecto generado.
#
# ESCALAS JSON <-> UI de CapCut (CONFIRMADAS empiricamente; docs en
# docs/capcut_json_scales.md). Canvas del proyecto 1920x1080:
#   - transform.x:                             JSON = UI_X / 1920
#                                               (UI -1098 -> -0.571875)
#   - transform.y:                             JSON = UI_Y / 1080
#                                               (UI 896 -> 0.8296296)
#   - text_alpha (opacidad):                   JSON = UI / 100 con fill.alpha
#                                               1.0 explicito (40% -> 0.40)
#   - letter_spacing:                          JSON = UI * 0.05 (UI 2 -> 0.10)
# !!! VERIFICACION EMPIRICA OBLIGATORIA: abrir el proyecto en CapCut y
# comprobar que la UI muestra EXACTAMENTE los valores deseados. Si no, ajustar
# el JSON proporcionalmente y documentar la correccion en el README.
WATERMARK_ENABLED = True
WATERMARK_TEXT = "NEXUS PARADOJA"
WATERMARK_FONT_SIZE = 8.0

# --- Opacidad: pares UI / JSON (escala: JSON = UI / 100; 40% -> 0.40) -------
# El builder escribe TAMBIEN styles[0].fill.alpha = 1.0: sin ese alpha CapCut
# aplica un factor ~0.75 y 0.40 se muestra como 30% (verificado en v1.3.0).
WATERMARK_ALPHA_UI = 40
WATERMARK_ALPHA_JSON = 0.40
# Alias historicos (misma escala float 0-1 que los subtitulos; text_alpha).
WATERMARK_OPACITY_UI = WATERMARK_ALPHA_UI
WATERMARK_OPACITY_JSON = WATERMARK_ALPHA_JSON
WATERMARK_OPACITY = WATERMARK_ALPHA_JSON

# --- Espaciado de caracteres: pares UI / JSON (escala: JSON = UI * 0.05) ----
# UI "2" de CapCut == 0.10 en el JSON (0.05 por unidad, igual que subtitulos).
WATERMARK_LETTER_SPACING_UI = 2
WATERMARK_LETTER_SPACING_JSON = 0.10
# Valor efectivo en unidades de la UI (referencia; el builder escribe el JSON).
WATERMARK_LETTER_SPACING = 2

# --- Posicion: pares UI / JSON (escala: JSON = UI / canvas COMPLETO) --------
# CONFIRMADO EMPIRICAMENTE (v1.4.0): CapCut multiplica transform por el canvas
# completo (1920x1080), no por su mitad. Calibrado contra el draft real del
# usuario y tus mediciones: JSON x=-1.14375 -> UI -2196; el JSON correcto para
# UI X=-1098 es -1098/1920 = -0.571875, y para UI Y=896 es 896/1080 = 0.8296296.
# Convenio de signo: POSITIVO = ARRIBA, NEGATIVO = ABAJO.
WATERMARK_POS_X_UI = -1098
WATERMARK_POS_Y_UI = 896
WATERMARK_POS_X_JSON = -1098 / CANVAS_WIDTH   # -0.571875
WATERMARK_POS_Y_JSON = 896 / CANVAS_HEIGHT    # 0.8296296...
# Valores UI en pixeles (referencia/documentacion del convenio de signo).
WATERMARK_POS_X = -1098
WATERMARK_POS_Y = 896
WATERMARK_BOLD = True
WATERMARK_ITALIC = True

# Posicion vertical del centro de los subtitulos. UI Y=-660 px (abajo del
# centro; convenio verificado: NEGATIVO = abajo). Escala CONFIRMADA
# empiricamente: JSON = UI_Y / CANVAS_HEIGHT = -660/1080 = -0.6111111. Valores
# JSON se aplican SIN calculo dinamico a todos los subtitulos
# (config.SUBTITLE_POS_Y_JSON).
SUBTITLE_POS_Y = -660
SUBTITLE_POS_Y_JSON = -660 / CANVAS_HEIGHT      # -0.6111111...
SUBTITLE_POS_Y_JSON_HALF = -660 / HALF_H        # referencia antigua, NO usar

# Grosor del trazo (stroke) de los subtitulos. ESCALA CONFIRMADA empiricamente
# (v1.4.0): UI = JSON * 500 -> UI 30 = JSON 0.06 (border_width y strokes[].width).
# El valor viejo 0.30 se mostraba como 150 en CapCut (0.30 * 500). Trazo
# SIEMPRE activado (strokes[].enable true, border_mode 1) y color negro puro
# (ver BORDER_* en subtitles.py).
SUBTITLE_STROKE_WIDTH_UI = 30
SUBTITLE_STROKE_WIDTH_JSON = 30 / 500.0         # 0.06
SUBTITLE_STROKE_WIDTH = SUBTITLE_STROKE_WIDTH_JSON


def ensure_dirs() -> None:
    """Crea las carpetas de trabajo si no existen."""
    for d in (CACHE_DIR, LOGS_DIR, BACKUPS_DIR, BIN_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def crispasr_zip_url() -> str:
    return CRISPASR_DOWNLOAD_URL


def align_model_url() -> str:
    return MODEL_DOWNLOAD_URL


def capcut_projects_dir() -> Path:
    """Devuelve la ruta base de proyectos CapCut de Windows.

    %LOCALAPPDATA%\\CapCut\\User Data\\Projects\\com.lveditor.draft
    """
    local = os.path.expandvars(r"%LOCALAPPDATA%")
    return Path(local) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"


def load_user_config() -> dict:
    """Carga config_user.json (con valores por defecto para claves ausentes)."""
    cfg = dict(DEFAULT_USER_CONFIG)
    if not USER_CONFIG_FILE.is_file():
        return cfg
    try:
        raw = json.loads(USER_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.getLogger("capcutauto").warning(
            "No se pudo leer %s (%s); se usan valores por defecto.",
            USER_CONFIG_FILE, exc,
        )
        return cfg
    if not isinstance(raw, dict):
        return cfg
    for key in DEFAULT_USER_CONFIG:
        value = raw.get(key)
        if isinstance(value, str):
            cfg[key] = value
    return cfg


def save_user_config(user_config: dict) -> None:
    """Persiste config_user.json conservando unicamente las claves conocidas."""
    data = dict(DEFAULT_USER_CONFIG)
    for key in DEFAULT_USER_CONFIG:
        value = (user_config or {}).get(key)
        if isinstance(value, str):
            data[key] = value
    try:
        USER_CONFIG_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logging.getLogger("capcutauto").warning(
            "No se pudo guardar %s (%s).", USER_CONFIG_FILE, exc,
        )