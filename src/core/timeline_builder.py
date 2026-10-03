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
import unicodedata
import wave
from dataclasses import dataclass, field, replace
from pathlib import Path

from src.core.edit_types import DYC_GLITCH_TRANSITIONS
from src.core.scene_parser import Scene

log = logging.getLogger("capcutauto")

US_PER_S = 1_000_000

# Alineacion a multiplos de ~33333 us (= 1 frame a 30fps) para evitar desfases
# en el timeline de CapCut.
_FRAME_US = 33333

# Posicion del CTA INTERMEDIO: 37% del total del video (punto medio del rango 35-40%).
DYC_CTA_INTERMEDIO_PCT = 0.37

# Posicion fallback del CTA FINAL cuando no se encuentra "suscr#ED #ED" en el SRT.
CTA_FINAL_FALLBACK_RATIO = 0.90

# FIX 4 (bloque 6): intensidad del chroma key NEGRO. Se aplica SOLO a los dos CTA
# (CTA INTERMEDIO y CTA FINAL); la pantalla final va sin chroma.
DYC_CHROMA_INTENSITY = 0.25

# Patrón a buscar en el SRT para detectar el momento del CTA FINAL (accent-insensitive).
_CTA_PATTERNS = (
    r"suscribete",
    r"suscribirse",
    r"suscribete al canal",
    r"subscribete",
    r"subscribirse",
    r"suscribete si quieres",
)
_CTA_RE = re.compile("|".join(f"(?:{p})" for p in _CTA_PATTERNS), re.IGNORECASE)

# Ventana mínima entre CTA FINALs consecutivos (1 minuto).
_CTA_MIN_WINDOW_US = 60_000_000

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


# ---------------------------------------------------------------------------
# v1.7.0 — Helpers para posicionamiento de CTA (Datos Y Cafe)
# ---------------------------------------------------------------------------
def _normalize_spanish(text: str) -> str:
    """Normaliza texto espanol: quita tildes y convierte a minusculas."""
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii").lower()


def find_cta_intermedio_start(total_duration_us: int) -> int:
    """Devuelve el timestamp (us) donde debe comenzar el CTA INTERMEDIO.

    Posicion: 37% del total, alineado al multiplo mas cercano de 1 frame (33333 us).
    """
    raw = int(total_duration_us * DYC_CTA_INTERMEDIO_PCT)
    return (raw // _FRAME_US) * _FRAME_US


def find_cta_final_starts(
    srt_path: str | Path | None, total_duration_us: int,
) -> tuple[list[int], bool]:
    """Devuelve las posiciones (us) de todos los CTA FINAL encontrados en el SRT.

    Busca "suscríbete" (y variantes) de forma accent-insensitive.
    tras cada coincidencia avanza 60 s antes de buscar la siguiente.
    Retorna ([start_us, ...], encontrado_alguno).
    """
    def _norm(text: str) -> str:
        return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()

    if srt_path is None or not Path(srt_path).is_file():
        fallback = int(total_duration_us * CTA_FINAL_FALLBACK_RATIO)
        return [(fallback // _FRAME_US) * _FRAME_US], False
    try:
        srt_text = Path(srt_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        fallback = int(total_duration_us * CTA_FINAL_FALLBACK_RATIO)
        return [(fallback // _FRAME_US) * _FRAME_US], False

    entries = parse_srt(Path(srt_path))
    starts: list[int] = []
    search_from_s: float = 0.0
    for start_s, end_s, cue_text in entries:
        if start_s < search_from_s:
            continue
        normed = _norm(cue_text)
        if _CTA_RE.search(normed):
            start_us = int(round(start_s * US_PER_S))
            aligned = (start_us // _FRAME_US) * _FRAME_US
            starts.append(aligned)
            log.info("CTA FINAL #%d en t=%.2f s (match: '%s')", len(starts), start_s,
                     cue_text.strip()[:40])
            search_from_s = end_s + 60.0

    if not starts:
        fallback = int(total_duration_us * CTA_FINAL_FALLBACK_RATIO)
        log.warning("No se encontró 'suscríbete' en el SRT; CTA FINAL único en 90%%.")
        return [(fallback // _FRAME_US) * _FRAME_US], False
    return starts, True


def get_last_srt_end_us(srt_path: str | Path | None) -> int | None:
    """Devuelve el end_time (µs) del último cue en el SRT, o None si no hay."""
    if srt_path is None or not Path(srt_path).is_file():
        return None
    try:
        entries = parse_srt(Path(srt_path))
    except OSError:
        return None
    if not entries:
        return None
    return int(round(entries[-1][1] * US_PER_S))


# ---------------------------------------------------------------------------
# v1.7.0 — Pool de animaciones de entrada DYC (3 opciones, rutas completas)
# ---------------------------------------------------------------------------
def _dyc_intro_animations() -> tuple[dict, ...]:
    """Pool de 3 animaciones de entrada DYC con rutas absolutas al caché de CapCut."""
    import getpass
    user = getpass.getuser()
    base = Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache" / "effect"
    return (
        {
            "resource_id": "7575810888108756277",
            "name": "TV retro",
            "duration_us": 2_000_000,
            "hash": "b3efebc966906cd02d0ad134ba81a47b",
            "path": (base / "7575810888108756277" / "b3efebc966906cd02d0ad134ba81a47b").as_posix(),
        },
        {
            "resource_id": "7372119524465709569",
            "name": "Rompecabezas",
            "duration_us": 2_533_333,
            "hash": "4b721a1559eb3451d6cc358468537c49",
            "path": (base / "7372119524465709569" / "4b721a1559eb3451d6cc358468537c49").as_posix(),
        },
        {
            "resource_id": "7522434265225628981",
            "name": "Celular en 3D",
            "duration_us": 2_000_000,
            "hash": "d20828aeebb4ec698dee4563c80968f2",
            "path": (base / "7522434265225628981" / "d20828aeebb4ec698dee4563c80968f2").as_posix(),
        },
    )


# Acceso directo al pool (se evalúa una sola vez, después es tuple).
DYC_INTRO_ANIMATIONS: tuple[dict, ...] = _dyc_intro_animations()


# ---------------------------------------------------------------------------
# v1.7.0 — FIX 1/FIX 2 — Transiciones DYC
# ---------------------------------------------------------------------------
# FIX 1: "Elige otro" queda PROHIBIDO para DYC siempre, se filtre aunque el pool
# lo contenga por error (28 entradas) -> deben quedar 27.
DYC_EXCLUDED_TRANSITION_NAMES: tuple[str, ...] = ("Elige otro",)


def filter_dyc_transitions(pool: tuple) -> tuple:
    """Elimina del pool cualquier transición con un name prohibido.

    Se aplica SIEMPRE antes de elegir al azar, para que "Elige otro" no pueda
    salir ni siquiera aunque alguien la reintroduce en el pool."""
    return tuple(
        t for t in pool
        if (t[1] if len(t) > 1 else "") not in DYC_EXCLUDED_TRANSITION_NAMES
    )


def pick_dyc_transition(pool: tuple, last_id: str | None = None) -> tuple:
    """Elige al azar una transición del pool DYC ya filtrado, evitando repetir
    el effect_id de la transición anterior cuando hay alternativa."""
    import random as _random
    candidates = list(filter_dyc_transitions(pool))
    if not candidates:
        raise ValueError("pool de transiciones DYC vacío tras el filtro")
    if last_id is not None:
        others = [t for t in candidates if t[0] != last_id]
        if others:
            candidates = others
    return _random.choice(candidates)


def pick_dyc_glitch_transition() -> tuple:
    """FIX 2: transición entre la ÚLTIMA IMAGEN y "Pantalla final.mp4".
    Se elige SIEMPRE al azar SOLO del subconjunto GLITCH (7 opciones)."""
    import random as _random
    return _random.choice(DYC_GLITCH_TRANSITIONS)


def sync_last_item_to_audio_end(
    items: list[TimelineItem],
    fin_audio_us: int,
    min_duration_us: int = 1_000_000,
) -> list[TimelineItem]:
    """FIX 3: la ÚLTIMA imagen debe terminar EXACTAMENTE en el fin real del audio.

    Se ajusta SOLO la duración de la última imagen (las anteriores no se tocan) y
    se calcula desde su start_us real: sumar las duraciones arrastra el redondeo
    de cada item y descuadraba el final del video varios cientos de ms, dejando
    un hueco entre el fin de la última imagen y el fin del audio.
    """
    if not items:
        return items
    last = items[-1]
    if last.image_path is None or last.duration_us <= 0:
        return items
    new_dur = max(fin_audio_us - last.start_us, min_duration_us)
    return list(items[:-1]) + [
        replace(last, duration_us=new_dur, end_us=fin_audio_us)]