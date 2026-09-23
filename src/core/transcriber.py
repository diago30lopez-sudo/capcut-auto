"""Forced alignment del audio con el guion mediante CrispASR.

Genera un SRT donde cada linea del guion se alinea contra el audio (1 linea de
texto = 1 cue con sus timestamps reales). El binario de CrispASR y el modelo
espanol (GGUF Q4_K ~70 MB) se descargan automaticamente en la primera
ejecucion dentro de bin/ y models/; en las siguientes se cargan desde disco.
"""

from __future__ import annotations

import http.client
import logging
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from src.core import config
from src.core.timeline_builder import GenerationCancelled

log = logging.getLogger("capcutauto")

_CHUNK = 1 << 20
_USER_AGENT = {"User-Agent": "capcut-auto"}
_DOWNLOAD_ATTEMPTS = 3


def _download(url: str, dest: Path, cancel_event=None) -> None:
    """Descarga ``url`` a ``dest`` (via .part) con reintentos en errores de red."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_exc: Exception | None = None
    for attempt in range(1, _DOWNLOAD_ATTEMPTS + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise GenerationCancelled("Generación cancelada por el usuario.")
        tmp = dest.with_name(dest.name + ".part")
        try:
            req = urllib.request.Request(url, headers=_USER_AGENT)
            with urllib.request.urlopen(req) as resp:  # noqa: S310 - URLs fijas de config
                total = int(resp.headers.get("Content-Length") or 0)
                log.info("   ↓ %s (%.1f MB)", dest.name, total / 1_000_000)
                received = 0
                with open(tmp, "wb") as fh:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            tmp.unlink(missing_ok=True)
                            raise GenerationCancelled("Generación cancelada por el usuario.")
                        block = resp.read(_CHUNK)
                        if not block:
                            break
                        fh.write(block)
                        received += len(block)
            tmp.replace(dest)
            return
        except GenerationCancelled:
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError,
                http.client.HTTPException) as exc:
            last_exc = exc
            tmp.unlink(missing_ok=True)
            log.warning("Descarga interrumpida (intento %d/%d): %s",
                        attempt, _DOWNLOAD_ATTEMPTS, exc)
            time.sleep(2 * attempt)
    raise RuntimeError(
        f"No se pudo descargar {dest.name} tras {_DOWNLOAD_ATTEMPTS} intentos: {last_exc}"
    )


def _flatten_bin() -> None:
    """Aplana bin/: sube todos los archivos extraidos a la raiz de bin/."""
    root = config.BIN_DIR
    for entry in sorted(list(root.rglob("*")), key=lambda p: (p.is_dir(), str(p))):
        if entry.is_file() and entry.parent != root:
            target = config.CRISPASR_EXE if entry.name.lower() == "crispasr.exe" \
                else root / entry.name
            if target.exists() and target != entry:
                target.unlink(missing_ok=True)
            entry.replace(target)
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass


def _ensure_crispasr_exe(cancel_event=None) -> Path:
    _flatten_bin()
    if config.CRISPASR_EXE.is_file():
        return config.CRISPASR_EXE
    log.info("CrispASR no esta instalado. Descargando binario (primera ejecucion)...")
    _download(config.crispasr_zip_url(), config.CACHE_DIR / config.CRISPASR_ZIP_NAME, cancel_event)
    with zipfile.ZipFile(config.CACHE_DIR / config.CRISPASR_ZIP_NAME) as zf:
        zf.extractall(config.BIN_DIR)
    (config.CACHE_DIR / config.CRISPASR_ZIP_NAME).unlink(missing_ok=True)
    _flatten_bin()
    if not config.CRISPASR_EXE.is_file():
        raise RuntimeError("El .zip de CrispASR no contenia crispasr.exe.")
    log.info("Binario listo: %s", config.CRISPASR_EXE)
    return config.CRISPASR_EXE


def _ensure_align_model(cancel_event=None) -> Path:
    if config.ALIGN_MODEL_PATH.is_file():
        return config.ALIGN_MODEL_PATH
    log.info("Modelo de alineacion no encontrado. Descargando modelo espanol (primera ejecucion)...")
    _download(config.align_model_url(), config.ALIGN_MODEL_PATH, cancel_event)
    log.info("Modelo listo: %s", config.ALIGN_MODEL_PATH)
    return config.ALIGN_MODEL_PATH


def align_audio_to_text(
    audio_path: str | Path,
    text_lines: list[str],
    output_srt_path: str | Path,
    cancel_event=None,
) -> Path:
    """Alinea el audio con las lineas del guion y escribe el SRT; devuelve su ruta."""
    audio_path = Path(audio_path)
    output_srt_path = Path(output_srt_path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"No se encuentra el archivo de audio: {audio_path}")

    lines = [t.strip() for t in text_lines if t.strip()]
    if not lines:
        raise ValueError("No hay texto de guion (VOZ EN OFF) para alinear.")

    _ensure_crispasr_exe(cancel_event)
    _ensure_align_model(cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        raise GenerationCancelled("Generación cancelada por el usuario.")

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    text_file = config.CACHE_DIR / f"guion_alinear_{audio_path.stem}.txt"
    text_file.write_text("\n".join(lines), encoding="utf-8")
    output_srt_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(config.CRISPASR_EXE),
        "--align-only",
        "-am", str(config.ALIGN_MODEL_PATH),
        "-f", str(audio_path),
        "--text-file", str(text_file),
        "--align-granularity", "segment",
        "--align-output", str(output_srt_path),
    ]
    log.info("Alineando audio con el guion (%d lineas)...", len(lines))
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if cancel_event is not None and cancel_event.is_set():
        raise GenerationCancelled("Generación cancelada por el usuario.")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"CrispASR fallo (rc={proc.returncode}): {err[-1500:]}")
    if not output_srt_path.is_file():
        raise RuntimeError("CrispASR termino pero no genero el SRT.")
    log.info("Alineacion completada -> %s (%d cues).",
             output_srt_path, output_srt_path.read_text(encoding="utf-8", errors="replace").count("-->"))
    return output_srt_path