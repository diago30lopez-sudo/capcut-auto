"""Construccion del timeline imagen <-> escena a partir del SRT alineado.

Cada cue del SRT corresponde, en orden de aparicion, a una escena con VOZ EN
OFF: el start/end reales del cue i se usan como intervalo de la escena i.
Las escenas sin cue (o sin texto) quedan con duracion 0 (no sincronizadas).

Cada imagen i ocupa [start_i, end_i] en microsegundos; el audio ocupa [0, total].
"""

from __future__ import annotations

import logging
import re
import threading
import wave
from dataclasses import dataclass, field, replace
from pathlib import Path

from src.core.scene_parser import Scene

log = logging.getLogger("capcutauto")

US_PER_S = 1_000_000

_TIME_RE = re.compile(
    r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)"
)


class GenerationCancelled(Exception):
    """Lanzada cuando el usuario cancela la generacion en curso."""


@dataclass
class TimelineItem:
    order: int
    image_path: Path
    scene_text: str
    segment_text: str
    score: float
    start_us: int
    end_us: int
    duration_us: int = field(default=0)

    @property
    def is_synced(self) -> bool:
        return self.duration_us > 0


def _group_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(srt_path: Path) -> list[tuple[float, float, str]]:
    """Devuelve [(start, end, texto)] en orden, ignorando numeracion y saltos."""
    entries: list[tuple[float, float, str]] = []
    if not srt_path.is_file():
        return entries
    start = end = None
    text: list[str] = []
    for raw in srt_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if start is None:
            match = _TIME_RE.search(line)
            if match:
                start = _group_to_seconds(*match.group(1, 2, 3, 4))
                end = _group_to_seconds(*match.group(5, 6, 7, 8))
                text = []
            continue
        if not line:
            if text:
                entries.append((start, end, " ".join(text).strip()))
            start = end = None
            text = []
            continue
        if line.isdigit() and not text:
            continue
        text.append(line)
    if start is not None and text:
        entries.append((start, end, " ".join(text).strip()))
    return entries


def build_timeline(
    scenes: list[Scene],
    srt_path: str | Path,
    image_paths: list[Path],
    cancel_event: threading.Event | None = None,
) -> tuple[list[TimelineItem], int]:
    """Devuelve (items_del_timeline, duracion_audio_us) alineando escenas <-> cues SRT."""
    entries = parse_srt(Path(srt_path))
    if not entries:
        log.warning("No hay cues SRT alineados; el timeline quedara sin sincronizar.")

    items: list[TimelineItem] = []
    pos = 0
    for i, scene in enumerate(scenes):
        if cancel_event is not None and cancel_event.is_set():
            raise GenerationCancelled("Generación cancelada por el usuario.")
        image_path = image_paths[i] if i < len(image_paths) else None
        key = scene.key_text

        if not key:
            log.warning("Escena #%d sin texto VOZ EN OFF para alinear.", scene.number)
            items.append(TimelineItem(i, image_path, "", "", 0.0, 0, 0))
            continue

        if pos >= len(entries):
            log.warning(
                "Escena #%d sin cue en el SRT (alineacion incompleta) — duracion 0.",
                scene.number,
            )
            items.append(TimelineItem(i, image_path, key, "", 0.0, 0, 0))
            continue

        start, end, cue_text = entries[pos]
        pos += 1
        start_us = int(round(start * US_PER_S))
        end_us = int(round(end * US_PER_S))
        duration_us = max(end_us - start_us, 0)
        log.info(
            "Escena #%d OK — [%s .. %s] (%d us) — %s",
            scene.number, f"{start:.2f}s", f"{end:.2f}s", duration_us, cue_text,
        )
        items.append(
            TimelineItem(i, image_path, key, cue_text, 1.0, start_us, end_us, duration_us)
        )

    total_us = max((it.end_us for it in items), default=0)
    return items, total_us


def measure_audio_duration_us(path: str | Path) -> int | None:
    """Duración REAL del archivo de audio en microsegundos (solo WAV/PCM).
    Devuelve None para otros formatos (el caller usará la duración de los cues)."""
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
        if rate <= 0:
            return None
        return int(round(frames / rate * US_PER_S))
    except Exception:  # noqa: BLE001 - formato no soportado
        return None


def redistribute_gap(items: list[TimelineItem], target_us: int) -> list[TimelineItem]:
    """Punto 5: si la suma de las duraciones de las imágenes es menor que la
    duración total del audio, reparte el excedente PROPORCIONALMENTE entre todas
    las imágenes (nunca estira solo la última) y reacomoda los inicios de forma
    contigua, de modo que el video termine exactamente junto con el audio."""
    synced = [it for it in items if it.duration_us > 0]
    if not synced:
        return items
    sum_synced = sum(it.duration_us for it in synced)
    if target_us <= sum_synced:
        return items
    factor = target_us / sum_synced

    out: list[TimelineItem] = []
    cursor: int | None = None
    for it in items:
        if it.duration_us > 0:
            duration_us = max(int(round(it.duration_us * factor)), 1)
            start_us = cursor if cursor is not None else it.start_us
        else:
            duration_us = 1_000_000
            start_us = cursor if cursor is not None else 0
        cursor = start_us + duration_us
        out.append(TimelineItem(
            it.order, it.image_path, it.scene_text, it.segment_text, it.score,
            start_us, cursor, duration_us,
        ))

    # Corrección por redondeo (diferencia de pocos µs): encaja el final en target.
    last = out[-1]
    if last.duration_us > 0 and target_us > cursor:
        out[-1] = replace(last, end_us=target_us, duration_us=last.duration_us + (target_us - cursor))
    elif last.duration_us > 0 and target_us < cursor:
        out[-1] = replace(last, end_us=target_us, duration_us=max(target_us - last.start_us, 1))

    log.info(
        "Redistribución proporcional del excedente: %s -> %s µs (factor %.6f).",
        sum_synced, target_us, factor,
    )
    return out