"""Primer uso: descarga automatica de las dependencias de forced alignment.

Comprueba que existen en disco todos los componentes necesarios:

* bin\\crispasr.exe, bin\\crispasr-quantize.exe, bin\\openblas.dll y los
  textos legales bin\\LICENSE y bin\\THIRD_PARTY_NOTICES.txt (todos los trae
  el .zip oficial del release de CrispASR).
* models\\<modelo GGUF espanol> (descarga directa desde Hugging Face).

Si algo falta, se descarga con progreso en el log (10% en 10%), verificando el
tamano final contra el Content-Length (https). Ante interrupcion de red se
reintenta hasta 3 veces con backoff exponencial 2s/4s/8s; si la cancelacion
esta activa se aborta, se borra el .part y se lanza GenerationCancelled.

La funcion publica es ``ensure_dependencies(cancel_event=None)``, que llaman
src/core/transcriber.align_audio_to_text (antes de usar CrispASR) y la UI al
arrancar en un hilo aparte.
"""

from __future__ import annotations

import http.client
import logging
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from src.core import config
from src.core.timeline_builder import GenerationCancelled

log = logging.getLogger("capcutauto")

_CHUNK = 1 << 20                       # 1 MB por bloque (igual que transcriber)
_USER_AGENT = {"User-Agent": "capcut-auto"}
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (2, 4, 8)           # backoff exponencial solicitado

# Archivos que deben quedar en bin/ (todos dentro del .zip oficial de CrispASR).
BIN_DEPENDENCIES = (
    "crispasr.exe",
    "crispasr-quantize.exe",
    "openblas.dll",
    "LICENSE",
    "THIRD_PARTY_NOTICES.txt",
)

# Mensaje cuando no hay internet y faltan dependencias para la primera vez.
_NO_INTERNET_MSG = (
    "Se necesita conexión a internet la primera vez para descargar los componentes. "
    "Revisa tu conexión e inténtalo de nuevo."
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


def _download_file(url: str, dest: Path, cancel_event=None) -> None:
    """Descarga ``url`` a ``dest`` (via .part) con progreso, verificacion de
    tamano y reintentos con backoff exponencial 2s/4s/8s."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise GenerationCancelled("Generación cancelada por el usuario.")
        tmp = dest.with_name(dest.name + ".part")
        try:
            req = urllib.request.Request(url, headers=_USER_AGENT)
            with urllib.request.urlopen(req) as resp:  # noqa: S310 - URLs fijas de config
                total = int(resp.headers.get("Content-Length") or 0)
                log.info("   ↓ %s (%.1f MB)", dest.name, total / 1_000_000)
                received = 0
                last_pct = 0
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
                        if total > 0:
                            pct = int(received * 100 / total)
                            if pct >= last_pct + 10:
                                last_pct = pct
                                log.info("   %s: %d%%", dest.name, pct)
            # Verificacion de tamano contra Content-Length (si vino en el header).
            if total > 0 and received != total:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Tamaño incorrecto en {dest.name}: esperado {total}, recibido {received}."
                )
            tmp.replace(dest)
            return
        except GenerationCancelled:
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError,
                http.client.HTTPException, OSError) as exc:
            last_exc = exc
            tmp.unlink(missing_ok=True)
            log.warning("Descarga interrumpida (intento %d/%d): %s",
                        attempt, _MAX_ATTEMPTS, exc)
            if cancel_event is not None and cancel_event.is_set():
                raise GenerationCancelled("Generación cancelada por el usuario.")
            time.sleep(_BACKOFF_SECONDS[attempt - 1])
    raise RuntimeError(
        f"{_NO_INTERNET_MSG} Detalle: no se pudo descargar {dest.name}"
        f" tras {_MAX_ATTEMPTS} intentos: {last_exc}"
    )


def _ensure_crispasr_bins(cancel_event=None) -> None:
    """Descarga y extrae el .zip oficial de CrispASR si falta algun binario."""
    if all((config.BIN_DIR / name).is_file() for name in BIN_DEPENDENCIES):
        return
    log.info("CrispASR no esta instalado. Descargando binario (primera ejecucion)...")
    zip_path = config.CACHE_DIR / config.CRISPASR_ZIP_NAME
    _download_file(config.CRISPASR_DOWNLOAD_URL, zip_path, cancel_event)
    config.BIN_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(config.BIN_DIR)
    zip_path.unlink(missing_ok=True)
    _flatten_bin()
    missing = [name for name in BIN_DEPENDENCIES
               if not (config.BIN_DIR / name).is_file()]
    if missing:
        raise RuntimeError(f"El .zip de CrispASR no contenia: {', '.join(missing)}.")
    log.info("Binario listo: %s", config.CRISPASR_EXE)


def ensure_dependencies(cancel_event=None) -> None:
    """Comprueba y descarga (si falta) todas las dependencias de alineacion.

    Devuelve None. Lanza GenerationCancelled si ``cancel_event`` esta activo y
    RuntimeError si no hay internet y quedan dependencias por descargar."""
    log.info("Comprobando dependencias...")
    _ensure_crispasr_bins(cancel_event)
    if not config.ALIGN_MODEL_PATH.is_file():
        log.info("Modelo de alineacion no encontrado. Descargando modelo espanol"
                 " (primera ejecucion)...")
        _download_file(config.MODEL_DOWNLOAD_URL, config.ALIGN_MODEL_PATH, cancel_event)
        log.info("Modelo listo: %s", config.ALIGN_MODEL_PATH)
    log.info("✓ Dependencias listas.")