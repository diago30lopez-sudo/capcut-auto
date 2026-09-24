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

ALIGN_MODEL_REPO = "cstr/stt-es-fastconformer-hybrid-ctc-large-GGUF"
ALIGN_MODEL_FILENAME = "stt-es-fastconformer-hybrid-ctc-large-q4_k.gguf"
ALIGN_MODEL_PATH = MODELS_DIR / ALIGN_MODEL_FILENAME


def ensure_dirs() -> None:
    """Crea las carpetas de trabajo si no existen."""
    for d in (CACHE_DIR, LOGS_DIR, BACKUPS_DIR, BIN_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def crispasr_zip_url() -> str:
    return f"{CRISPASR_BASE_URL}/{CRISPASR_VERSION}/{CRISPASR_ZIP_NAME}"


def align_model_url() -> str:
    return f"https://huggingface.co/{ALIGN_MODEL_REPO}/resolve/main/{ALIGN_MODEL_FILENAME}"


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