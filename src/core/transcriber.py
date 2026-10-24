"""Forced alignment del audio con el guion mediante CrispASR.

Genera un SRT donde cada linea del guion se alinea contra el audio (1 linea de
texto = 1 cue con sus timestamps reales). El binario de CrispASR y el modelo
espanol (GGUF Q4_K ~70 MB) se descargan automaticamente la primera ejecucion
via src/core/bootstrap.ensure_dependencies() en bin/ y models/; en las
siguientes se cargan desde disco.
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
from src.core.bootstrap import ensure_dependencies
from src.core.timeline_builder import GenerationCancelled, parse_srt

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

    # Primer uso: comprueba y descarga (si falta) el binario de CrispASR y el
    # modelo espanol antes de invocar el binario.
    ensure_dependencies(cancel_event)
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


def transcribe_audio_free(
    audio_path: str | Path,
    output_srt_path: str | Path,
    cancel_event=None,
    mode: str = "sentence",
) -> Path:
    """Transcribe el audio sin texto de referencia (transcripcion libre).
    Usa CrispASR en modo transcripcion libre con salida SRT.

    mode: 'sentence' = una cue por frase (por defecto);
          'word'     = una cue por palabra (el tiempo se reparte
                       proporcionalmente dentro de cada frase).
    """
    audio_path = Path(audio_path)
    output_srt_path = Path(output_srt_path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"No se encuentra el archivo de audio: {audio_path}")
    output_srt_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_dependencies(cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        raise GenerationCancelled("Generacion cancelada por el usuario.")
    # CrispASR's -of expects a path WITHOUT extension; it appends the
    # format-specific suffix (.srt when -osrt is set). Passing a path
    # that already ends in .srt produces <path>.srt.srt and the subsequent
    # file-existence check fails with "CrispASR termino pero no genero el SRT".
    _crisp_of = str(output_srt_path.with_suffix(""))
    cmd = [
        str(config.CRISPASR_EXE),
        "-f", str(audio_path),
        "-osrt",
        "-of", _crisp_of,
        "-l", "es",
        "-m", str(config.ALIGN_MODEL_PATH),
        # Force segmentation even when the punctuation model is unavailable.
        # --max-len 50 → hard cap per segment; --split-on-punct → sentence break;
        # --chunk-seconds 30 → VAD-fallback chunk size.
        "--max-len", "50",
        "--split-on-punct",
        "--chunk-seconds", "30",
    ]
    log.info("Ejecutando CrispASR transcribe_audio_free: %s", cmd)
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    log.info("CrispASR stdout: %s", (proc.stdout or "").strip()[:500])
    log.info("CrispASR stderr: %s", (proc.stderr or "").strip()[:1000])
    if cancel_event is not None and cancel_event.is_set():
        raise GenerationCancelled("Generacion cancelada por el usuario.")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        log.error("CrispASR fallo (rc=%d): %s", proc.returncode, err[-1500:])
        raise RuntimeError(f"CrispASR fallo (rc={proc.returncode}): {err[-1500:]}")
    # CrispASR appends the format suffix itself; verify the expected file exists.
    if not output_srt_path.is_file():
        # Fallback: search for a file with the same stem in the same directory.
        candidates = list(output_srt_path.parent.glob(output_srt_path.stem + "*"))
        log.warning(
            "SRT esperado %s no encontrado; candidatos: %s",
            output_srt_path,
            [str(c) for c in candidates],
        )
        if candidates:
            output_srt_path = candidates[0]
        else:
            raise RuntimeError(
                f"CrispASR termino pero no genero el SRT: {output_srt_path}.\n"
                f"stderr: {(proc.stderr or '').strip()}"
            )
    log.info("Transcripcion libre completada -> %s", output_srt_path)
    if mode == "word":
        return _format_srt_word_level(output_srt_path)
    return output_srt_path


def _srt_time(ms: int) -> str:
    """Convierte milisegundos a formato SRT HH:MM:SS,mmm."""
    hh = ms // 3600000
    mm = (ms % 3600000) // 60000
    ss = (ms % 60000) // 1000
    mmm = ms % 1000
    return f"{hh:02d}:{mm:02d}:{ss:02d},{mmm:03d}"


def _format_srt_word_level(srt_path: Path) -> Path:
    """Reescribe el SRT para que tenga una cue por palabra en lugar de por frase.

    Cada cue original se parte en palabras; el tiempo total del cue se reparte
    proporcionalmente entre ellas. Se sobrescribe el archivo original.
    """
    entries = parse_srt(srt_path)
    if not entries:
        return srt_path

    new_entries: list[tuple[float, float, str]] = []
    for start_s, end_s, text in entries:
        words = text.split()
        if not words:
            continue
        total_dur = end_s - start_s
        if total_dur <= 0:
            new_entries.append((start_s, end_s, words[0]))
            continue
        if len(words) == 1:
            new_entries.append((start_s, end_s, words[0]))
            continue
        word_dur = total_dur / len(words)
        for i, word in enumerate(words):
            w_start = start_s + i * word_dur
            w_end = start_s + (i + 1) * word_dur if i < len(words) - 1 else end_s
            new_entries.append((w_start, w_end, word))

    new_entries.sort(key=lambda e: e[0])

    lines: list[str] = []
    for idx, (start_s, end_s, word) in enumerate(new_entries, 1):
        start_ms = int(round(start_s * 1000))
        end_ms = int(round(end_s * 1000))
        lines.append(f"{idx}\n{_srt_time(start_ms)} --> {_srt_time(end_ms)}\n{word}")

    srt_path.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    log.info("SRT reformatado a nivel de palabra: %d cues originales -> %d cues.",
             len(entries), len(new_entries))
    return srt_path