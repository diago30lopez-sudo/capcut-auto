"""Construccion del timeline imagen <-> escena a partir del SRT alineado.
Cada cue del SRT corresponde, en orden de aparicion, a una escena con VOZ ENOFF: el start/end reales del cue i se usan como intervalo de la escena i.
Las escenas sin cue (o sin texto) quedan con duracion 0 (no sincronizadas).
Cada imagen i ocupa [start_i, end_i] en microsegundos; el audio ocupa [0, total]."""
from __future__ import annotations
import logging
import re
import threading
import unicodedata
import wave
from dataclasses import dataclass, field, replace
from pathlib import Path
from src.core.scene_parser import Scene

log = logging.getLogger("capcutauto")

US_PER_S = 1_000_000
_FRAME_US = 33333
# Default minimum scene duration: 1.5 seconds (prevents images from flashing).
DEFAULT_MIN_SCENE_DURATION_US = 1_500_000
MIN_SCENE_DURATION_US = DEFAULT_MIN_SCENE_DURATION_US
DYC_CTA_INTERMEDIO_PCT = 0.37
CTA_FINAL_FALLBACK_RATIO = 0.90
DYC_CHROMA_INTENSITY = 0.25

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


def _group_to_seconds(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(srt_path: Path):
    entries = []
    if not srt_path.is_file():
        return entries
    start = end = None
    text = []
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


def group_srt_into_sentences(entries):
    """Agrupa cues word-level del SRT en frases (sentence-level).

    Regla de agrupacion: un nuevo grupo se inicia cuando:
    - El cue actual termina con puntuacion de final de oracion (. ! ?).
    - Hay un gap de silencio mayor a SENTENCE_GAP_S segundos respecto al
      cue anterior.
    - El grupo actual ya supero MAX_PHRASE_DURATION_S (evita frases
      infinitamente largas que devorarian todas las escenas).

    Devuelve una lista de (start_s, end_s, full_text) donde full_text es la
    concatenacion de todos los cues del grupo.
    """
    if not entries:
        return []
    # Gap pequeno: crear mas frases para mejor alineacion escena-cue.
    SENTENCE_GAP_S = 0.3
    # Maximo 3s por frase para evitar que una frase larga se coma varias escenas.
    MAX_PHRASE_DURATION_S = 3.0
    PUNCT_END = re.compile(r"[.!?]$")

    grouped: list[tuple[float, float, str]] = []
    group_start = entries[0][0]
    group_end = entries[0][1]
    group_text = [entries[0][2]]

    for k in range(1, len(entries)):
        prev_end = entries[k - 1][1]
        cur_start, cur_end, cur_text = entries[k]
        gap = cur_start - prev_end
        phrase_dur = group_end - group_start

        # Iniciar nuevo grupo si hay condicion de corte.
        new_group = (
            gap > SENTENCE_GAP_S
            or PUNCT_END.search(group_text[-1])
            or phrase_dur >= MAX_PHRASE_DURATION_S
        )

        if new_group:
            grouped.append((group_start, group_end, " ".join(group_text)))
            group_start = cur_start
            group_end = cur_end
            group_text = [cur_text]
        else:
            group_end = cur_end
            group_text.append(cur_text)

    # Ultimo grupo.
    grouped.append((group_start, group_end, " ".join(group_text)))
    log.info(
        "Agrupacion SRT: %d cues word-level -> %d frases sentence-level.",
        len(entries), len(grouped),
    )
    return grouped
def measure_audio_duration_us(path):
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
        if rate <= 0:
            return None
        return int(round(frames / rate * US_PER_S))
    except Exception:
        return None


def redistribute_gap(items, target_us):
    synced = [it for it in items if it.duration_us > 0]
    orphans = [it for it in items if it.duration_us == 0]
    if not synced:
        if orphans:
            base = sum(it.duration_us for it in items)
            if target_us > base:
                factor = target_us / base if base > 0 else target_us
                out = []
                cursor = 0
                for it in items:
                    dur = max(round(it.duration_us * factor), 1)
                    out.append(TimelineItem(
                        it.order, it.image_path, it.scene_text, it.segment_text, it.score,
                        cursor, cursor + dur, dur,
                    ))
                    cursor += dur
                log.info(
                    "Redistribucion: base=%d us (%d escenas), target=%d us, factor=%.6f",
                    base, len(items), target_us, factor,
                )
                log.info(
                    "Reparto de tiempo huerfano: %d escenas sin cue, %d us repartidos. "
                    "Cada escena recibe ~%d us.",
                    len(orphans), target_us, target_us // len(orphans),
                )
                return out
        return items
    sum_synced = sum(it.duration_us for it in synced)
    if target_us <= sum_synced:
        return items
    if target_us > 0 and abs(sum_synced - target_us) < _FRAME_US:
        log.info(
            "Redistribucion omitida: delta %.0f us < 1 frame (%d us)",
            abs(sum_synced - target_us), _FRAME_US,
        )
        return items
    # When target > sum, ALWAYS scale up to fill the audio.
    # The 5% skip below only applies when target <= sum (overshoot).
    if target_us > 0 and sum_synced > target_us and abs(sum_synced - target_us) / target_us < 0.05:
        log.info(
            "Redistribucion omitida: suma %.0f us vs target %.0f us (delta %.1f%% < 5%%)",
            sum_synced, target_us, abs(sum_synced - target_us) / target_us * 100,
        )
        return items
    if orphans:
        orphan_gap = target_us - sum_synced
        if orphan_gap > 0:
            per_orphan = max(orphan_gap // len(orphans), 1)
            log.info(
                "Reparto de tiempo huerfano: %d escenas sin cue, %d us reservar. "
                "Cada escena recibe ~%d us.",
                len(orphans), orphan_gap, per_orphan,
            )
        else:
            per_orphan = 1
        items_with_orphans = []
        for it in items:
            if it.duration_us > 0:
                items_with_orphans.append(it)
            else:
                items_with_orphans.append(TimelineItem(
                    it.order, it.image_path, it.scene_text, it.segment_text, it.score,
                    0, 0, per_orphan,
                ))
        sum_all = sum(it.duration_us for it in items_with_orphans)
        if target_us > sum_all:
            factor = target_us / sum_all
        else:
            factor = 1.0
    else:
        items_with_orphans = items
        factor = target_us / sum_synced
    out = []
    cumulative_original = 0
    prev_target_end = 0
    cursor = 0
    for it in items_with_orphans:
        cumulative_original += it.duration_us
        target_end = round(cumulative_original * factor)
        duration_us = max(target_end - prev_target_end, 1)
        prev_target_end = target_end
        cursor = cursor + duration_us
        out.append(TimelineItem(
            it.order, it.image_path, it.scene_text, it.segment_text, it.score,
            cursor - duration_us, cursor, duration_us,
        ))
    cursor = sum(it.duration_us for it in out)
    if out and out[-1].duration_us > 0:
        last = out[-1]
        drift = target_us - cursor
        if drift != 0:
            out[-1] = replace(last,
                duration_us=last.duration_us + drift,
                end_us=target_us,
            )
            cursor = target_us
    sum_base = sum(it.duration_us for it in items if it.duration_us > 0)
    sum_post = sum(it.duration_us for it in out)
    log.info(
        "Redistribucion: base=%d us (%d escenas), target=%d us, factor=%.6f",
        sum_base, len(items), target_us, factor,
    )
    log.info(
        "Suma post-redistribucion: %d us (target: %d us, delta: %d)",
        sum_post, target_us, sum_post - target_us,
    )
    return out


def _normalize_spanish(text):
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii").lower()


def snap_to_frame(us: int, frame_us: int = _FRAME_US) -> int:
    """Redondea microsegundos al multiplo mas cercano de frame_us.

    Ejemplo: snap_to_frame(1_500_000, 33_333) -> 1_500_000 (exacto)
             snap_to_frame(1_500_001, 33_333) -> 1_500_000 (redondea abajo)
             snap_to_frame(1_516_666, 33_333) -> 1_516_659 (mas cercano)
    """
    if frame_us <= 0:
        return us
    return round(us / frame_us) * frame_us


def clean_text(text: str) -> str:
    """Limpieza profunda para comparar texto de escenas con el SRT.

    1. Minúsculas.
    2. Quitar acentos y tildes (NFD decomposition + latin strip).
    3. Quitar TODOS los signos de puntuacion, comillas y simbolos raros.
    4. Solo letras y numeros, separados por un solo espacio.
    """
    if not text:
        return ""
    t = text.lower()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w\s-]", " ", t)          # solo [a-z0-9_ -]
    t = re.sub(r"\s+", " ", t).strip()
    return t


def find_cta_intermedio_start(total_duration_us):
    raw = int(total_duration_us * DYC_CTA_INTERMEDIO_PCT)
    return (raw // _FRAME_US) * _FRAME_US


def find_cta_final_starts(srt_path, total_duration_us, patterns=()):
    _FALLBACK_PATTERNS = (
        r"suscribete",
        r"suscribirse",
        r"suscribete al canal",
        r"subscribete",
        r"subscribirse",
        r"suscribete si quieres",
    )
    _patterns = tuple(patterns) if patterns else _FALLBACK_PATTERNS
    _cta_re = re.compile("|".join(f"(?:{p})" for p in _patterns), re.IGNORECASE)
    def _norm(text):
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
    starts = []
    search_from_s = 0.0
    # Keep track of the last matched minute to avoid duplicates within 60s.
    last_matched_minute = -1.0
    for start_s, end_s, cue_text in entries:
        if start_s < search_from_s:
            continue
        normed = _norm(cue_text)
        if _cta_re.search(normed):
            start_us = int(round(start_s * US_PER_S))
            aligned = (start_us // _FRAME_US) * _FRAME_US
            # Dedup: skip if another CTA was already matched within the
            # same minute window (prevents double CTA when the same word
            # appears in consecutive cues).
            minute = int(start_s // 60.0)
            if minute == last_matched_minute:
                log.info(
                    "CTA FINAL omitido (duplicado en mismo minuto): t=%.2f s",
                    start_s,
                )
                search_from_s = end_s + 60.0
                continue
            starts.append(aligned)
            last_matched_minute = minute
            log.info("CTA FINAL #%d en t=%.2f s (match: '%s')", len(starts), start_s,
                     cue_text.strip()[:40])
            search_from_s = end_s + 60.0
    if not starts:
        fallback = int(total_duration_us * CTA_FINAL_FALLBACK_RATIO)
        log.warning("No se encontro 'suscribete' en el SRT; CTA FINAL unico en 90%%.")
        return [(fallback // _FRAME_US) * _FRAME_US], False
    return starts, True


def get_last_srt_end_us(srt_path):
    if srt_path is None or not Path(srt_path).is_file():
        return None
    try:
        entries = parse_srt(Path(srt_path))
    except OSError:
        return None
    if not entries:
        return None
    return int(round(entries[-1][1] * US_PER_S))


def _dyc_intro_animations():
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


DYC_INTRO_ANIMATIONS = _dyc_intro_animations()


DYC_EXCLUDED_TRANSITION_NAMES = ("Elige otro",)


def filter_dyc_transitions(pool):
    return tuple(
        t for t in pool
        if (t[1] if len(t) > 1 else "") not in DYC_EXCLUDED_TRANSITION_NAMES
    )


def pick_dyc_transition(pool, last_id=None):
    import random as _random
    candidates = list(filter_dyc_transitions(pool))
    if not candidates:
        raise ValueError("pool de transiciones DYC vacio tras el filtro")
    if last_id is not None:
        others = [t for t in candidates if t[0] != last_id]
        if others:
            candidates = others
    return _random.choice(candidates)


def pick_dyc_glitch_transition(glitch_transitions=()):
    import random as _random
    if not glitch_transitions:
        raise ValueError("glitch_transitions vacio; el perfil debe definir transiciones.glitch_pool")
    return _random.choice(glitch_transitions)


def _validate_transitions(video_segments, transitions):
    n_aplicadas = 0
    n_capadas = 0
    n_omitidas = 0
    if not transitions or len(video_segments) < 2:
        return transitions, n_aplicadas, n_capadas, n_omitidas
    t_list = transitions
    for b in range(len(t_list)):
        if b >= len(video_segments) - 1:
            break
        dur_i = int(video_segments[b].get("target_timerange", {}).get("duration") or 0)
        dur_next = int(video_segments[b + 1].get("target_timerange", {}).get("duration") or 0)
        max_by_neighbor = min(dur_i, dur_next) // 2
        if max_by_neighbor <= 0:
            continue
        orig = int(t_list[b].get("duration") or 0)
        capped = min(orig, max_by_neighbor)
        if capped != orig:
            n_capadas += 1
            t_list[b]["duration"] = capped
    for _iter in range(3):
        changed = False
        for i in range(1, len(video_segments) - 1):
            dur_seg = int(video_segments[i].get("target_timerange", {}).get("duration") or 0)
            if dur_seg <= 0:
                continue
            t_left = int(t_list[i - 1].get("duration") or 0) if i - 1 < len(t_list) else 0
            t_right = int(t_list[i].get("duration") or 0) if i < len(t_list) else 0
            limite = int(dur_seg * 0.9 * 2)
            suma = t_left + t_right
            if suma > limite and suma > 0:
                factor = limite / suma
                if t_left > 0:
                    t_list[i - 1]["duration"] = int(t_left * factor)
                    changed = True
                if t_right > 0:
                    t_list[i]["duration"] = int(t_right * factor)
                    changed = True
                if not changed:
                    break
        if not changed:
            break
    for b in range(len(t_list)):
        dur = int(t_list[b].get("duration") or 0)
        rounded = int(round(dur / _FRAME_US)) * _FRAME_US
        if rounded != dur:
            t_list[b]["duration"] = rounded
    boundaries_to_remove = []
    for b in range(len(t_list) - 1, -1, -1):
        dur = int(t_list[b].get("duration") or 0)
        if dur < 100_000:
            n_omitidas += 1
            log.info("Transicion #%d omitida (%d us < 0.1s)", b + 1, dur)
            seg = video_segments[b] if b < len(video_segments) else None
            if seg is not None:
                refs = seg.get("extra_material_refs") or []
                ref_id = t_list[b]["id"]
                seg["extra_material_refs"] = [r for r in refs if r != ref_id]
            boundaries_to_remove.append(b)
    for b in sorted(boundaries_to_remove, reverse=True):
        t_list.pop(b)
    n_aplicadas = len(t_list)
    return t_list, n_aplicadas, n_capadas, n_omitidas


def reorder_transition_refs(video_segments, transitions):
    trans_ids = {t["id"] for t in transitions}
    n_with = 0
    n_without = 0
    for seg in video_segments:
        refs = seg.get("extra_material_refs") or []
        trans_ref = None
        for r in refs:
            if r in trans_ids:
                trans_ref = r
                break
        if trans_ref is None:
            n_without += 1
            continue
        other_refs = [r for r in refs if r != trans_ref]
        new_refs = other_refs + [trans_ref]
        seg["extra_material_refs"] = new_refs
        n_with += 1
    return n_with, n_without


def sync_last_item_to_audio_end(items, fin_audio_us, min_duration_us=_FRAME_US, frame_us=_FRAME_US):
    if not items:
        return items
    last = items[-1]
    if last.image_path is None or last.duration_us <= 0:
        return items
    new_dur = max(fin_audio_us - last.start_us, min_duration_us)
    new_dur = snap_to_frame(new_dur, frame_us)
    return list(items[:-1]) + [
        replace(last, duration_us=new_dur, end_us=fin_audio_us)
    ]
def match_scenes_to_srt(
    scenes, srt_path, match_threshold=75.0, audio_dur_s=None,
):
    """Empareja escenas con frases del SRT usando fuzzy matching robusto.

    Algoritmo proporcional (anti-desfase):
      1. Limpieza profunda de texto con clean_text().
      2. El SRT se agrupa en frases (group_srt_into_sentences).
      3. Se calcula un paso uniforme: dist_span / n_escenas.
         - Si se provee audio_dur_s, se distribuye sobre la duracion del audio.
         - Si no, se usa la duracion del SRT.
      4. Cada escena se asigna a su posicion proporcional en el rango elegido.
      5. Si una escena tiene un match fuerte en la zona que le corresponde,
         se ajusta a ese match (pero nunca excede su rango proporcional).
      6. Criterio critico: start_us(N+1) == end_us(N). Sin huecos ni solapamientos.

    Devuelve:
      results: list[(scene_idx, start_s, end_s, matched)]
      no_match: int
      srt_end_s: float (ultima fecha del SRT)
    """
    from rapidfuzz import fuzz

    raw_entries = parse_srt(Path(srt_path))
    entries = group_srt_into_sentences(raw_entries)
    entries = [(s, e, t) for s, e, t in entries if e > s]

    n = len(scenes)
    srt_end_s = entries[-1][1] if entries else 0.0
    # Distribuir sobre audio_dur_s si se provee, sino sobre el SRT.
    dist_end_s = audio_dur_s if audio_dur_s is not None and audio_dur_s > 0 else srt_end_s
    if dist_end_s <= 0:
        dist_end_s = srt_end_s

    if n == 0:
        return [], 0, srt_end_s
    if not entries:
        # Sin SRT: distribuir sobre audio_dur_s si se conoce.
        if audio_dur_s and audio_dur_s > 0:
            step_s = audio_dur_s / n
            return [(i, i * step_s, (i + 1) * step_s, False) for i in range(n)], n, 0.0
        return [], n, 0.0

    step_s = dist_end_s / n

    # Pre-calcular las mejores coincidencias para cada escena.
    scene_best: list[tuple[int, float]] = []
    for scene in scenes:
        key = scene.key_text
        if not key:
            scene_best.append((-1, 0.0))
            continue
        norm_key = clean_text(key)
        best_k, best_score = -1, 0.0
        for k, (_, _, txt) in enumerate(entries):
            score = fuzz.token_set_ratio(norm_key, clean_text(txt))
            if score > best_score:
                best_score = score
                best_k = k
        scene_best.append((best_k, best_score))

    # Asignar posiciones proporcionales, ajustando cuando hay match fuerte.
    results: list[tuple[int, float, float, bool]] = []
    matched_count = 0

    for i, scene in enumerate(scenes):
        phk, score = scene_best[i]
        target_start = i * step_s
        target_end = (i + 1) * step_s

        if phk >= 0 and score >= match_threshold:
            # Ajustar al match dentro del rango asignado.
            phrase_start = entries[phk][0]
            phrase_end = entries[phk][1]
            est_start = max(target_start, phrase_start)
            est_end = min(target_end, phrase_end)
            if est_start >= est_end:
                est_start, est_end = target_start, target_end
            results.append((i, est_start, est_end, True))
            matched_count += 1
        else:
            results.append((i, target_start, target_end, False))

    # Rellenar huecos de duracion minima (< 0.5s).
    fixed = []
    for si, start_s, end_s, matched in results:
        if end_s - start_s < 0.5:
            prev_end = fixed[-1][2] if fixed else 0.0
            new_start = max(start_s, prev_end)
            new_end = new_start + max(0.5, step_s)
            fixed.append((si, new_start, new_end, matched))
        else:
            fixed.append((si, start_s, end_s, matched))

    # Eliminar huecos residuales entre items consecutivos.
    for k in range(1, len(fixed)):
        prev_end = fixed[k - 1][2]
        if fixed[k][1] < prev_end:
            fixed[k] = (fixed[k][0], prev_end, fixed[k][2], fixed[k][3])

    # Forward pass: eliminar solapamientos (start < prev_end).
    for k in range(1, len(fixed)):
        prev_end = fixed[k - 1][2]
        if fixed[k][1] < prev_end:
            fixed[k] = (fixed[k][0], prev_end, fixed[k][2], fixed[k][3])

    # Backward pass: eliminar huecos (gap > 1ms) y ajustar al SRT.
    for k in range(len(fixed) - 2, -1, -1):
        next_start = fixed[k + 1][1]
        if fixed[k][2] > next_start:
            # Solapamiento: recortar end al start del siguiente.
            fixed[k] = (fixed[k][0], fixed[k][1], next_start, fixed[k][3])
        elif fixed[k][2] < next_start - 0.001:
            # Hueco: extender end hasta el start del siguiente.
            fixed[k] = (fixed[k][0], fixed[k][1], next_start, fixed[k][3])

    no_match = sum(1 for r in fixed if not r[3])
    log.info(
        "Match escenas<->SRT: %d/%d emparejadas (umbral=%.0f), paso=%.3f s/escena.",
        matched_count, n, match_threshold, step_s,
    )
    return fixed, no_match, srt_end_s



def build_timeline(
    scenes, srt_path, image_paths,
    cancel_event=None, match_threshold=75.0,
    min_duration_us=DEFAULT_MIN_SCENE_DURATION_US,
    frame_us=_FRAME_US,
):
    matches, no_match, srt_end_s = match_scenes_to_srt(scenes, srt_path, match_threshold)
    items: list[TimelineItem] = []
    n = len(scenes)
    for i, start_s, end_s, matched in matches:
        if cancel_event is not None and cancel_event.is_set():
            raise GenerationCancelled("Generacion cancelada por el usuario.")
        scene = scenes[i]
        image_path = image_paths[i] if i < len(image_paths) else None
        key = scene.key_text
        # Forzar duración mínima en TODOS los items (incluidos interpolados).
        start_us = int(round(max(start_s, 0.0) * US_PER_S))
        end_us   = int(round(max(end_s,   start_s + 0.5) * US_PER_S))
        duration_us = max(end_us - start_us, min_duration_us)
        items.append(
            TimelineItem(i, image_path, key, key, 1.0, start_us, end_us, duration_us)
        )
        log.info(
            "Escena #%d [%s..%s] (%d us)",
            scene.number, f"{start_s:.2f}s", f"{end_s:.2f}s", duration_us,
        )

    # ------------------------------------------------------------------
    # Segundo pase: eliminar huecos y solapamientos.
    # start_us[N+1] == end_us[N] EXACTAMENTE.
    # ------------------------------------------------------------------
    for i in range(1, n):
        if items[i].start_us < items[i - 1].end_us:
            old_start = items[i].start_us
            items[i] = replace(items[i], start_us=items[i - 1].end_us)
            items[i] = replace(items[i], duration_us=items[i].end_us - items[i].start_us)
            if items[i].duration_us < min_duration_us:
                new_end = items[i].start_us + min_duration_us
                items[i] = replace(items[i], end_us=new_end, duration_us=min_duration_us)
            log.info("Escena #%d correccion monotonia: %d -> %d us",
                     scenes[i].number, old_start, items[i].start_us)

    # ------------------------------------------------------------------
    # Tercer pase: validar duracion minima despues de correcciones.
    # ------------------------------------------------------------------
    for i in range(n):
        it = items[i]
        if it.duration_us < min_duration_us:
            new_end = it.start_us + min_duration_us
            items[i] = replace(it, end_us=new_end, duration_us=min_duration_us)
            log.info("Escena #%d extendido a minimo (%d -> %d us)",
                     scenes[i].number, it.duration_us, min_duration_us)

    # ------------------------------------------------------------------
    # Cuarto pase: garantizar suma exacta = srt_end_us mediante
    # redistribución proporcional del delta.
    # ------------------------------------------------------------------
    srt_end_us = int(round(srt_end_s * US_PER_S)) if srt_end_s > 0 else 0
    if srt_end_us > 0 and items:
        last = items[-1]
        # El último item no debe exceder el final del SRT.
        if last.end_us > srt_end_us and last.start_us < srt_end_us:
            items[-1] = replace(last, end_us=srt_end_us)
            items[-1] = replace(items[-1],
                duration_us=items[-1].end_us - items[-1].start_us)
        # Redistribuir cualquier delta acumulado por redondeos o
        # correcciones de monotonia para que la suma sea EXACTA.
        sum_dur = sum(it.duration_us for it in items)
        delta = srt_end_us - sum_dur
        if delta != 0:
            n_items = len(items)
            per_item = delta // n_items
            remainder = delta % n_items
            if abs(per_item) >= 1:
                for i in range(n_items):
                    adj = per_item + (1 if i < abs(remainder) else 0)
                    if per_item < 0 and remainder > 0:
                        adj = per_item - (1 if i < (-remainder) else 0)
                    items[i] = replace(items[i],
                        duration_us=max(items[i].duration_us + adj, 1),
                        end_us=items[i].start_us + items[i].duration_us,
                    )
                log.info(
                    "Redistribución proporcional: delta=%d us, "
                    "%d items, ajuste_por_item=%d us",
                    delta, n_items, per_item,
                )
            else:
                # Delta menor a 1us por item: aplicar a la última imagen.
                items[-1] = replace(items[-1],
                    duration_us=items[-1].duration_us + delta,
                    end_us=srt_end_us,
                )
                log.info(
                    "Delta residual %d us aplicado a la última imagen.", delta,
                )

    # ------------------------------------------------------------------
    # Quinto pase: FRAME SNAP ABSOLUTO — forzar start_us y duration_us a la
    # rejilla exacta de frame_us, construyendo desde cursor=0 hacia adelante.
    # Esto elimina cualquier desfase acumulativo que CapCut pueda reconstruir
    # al leer la rejilla del draft.
    # ------------------------------------------------------------------
    if items:
        cursor = 0
        for it in items:
            start_snapped = round(cursor / frame_us) * frame_us
            dur_snapped = round(it.duration_us / frame_us) * frame_us
            if dur_snapped < 1:
                dur_snapped = frame_us
            items[it.order] = replace(it,
                start_us=start_snapped,
                duration_us=dur_snapped,
                end_us=start_snapped + dur_snapped,
            )
            cursor = start_snapped + dur_snapped

        # Ajuste final: forzar que el ultimo item termine EXACTAMENTE en el
        # total_snapped (multiplo de frame_us mas cercano al original).
        total_raw = items[-1].end_us
        total_snapped = snap_to_frame(total_raw, frame_us)
        if total_snapped != total_raw:
            diff = total_snapped - total_raw
            last = items[-1]
            items[-1] = replace(last,
                duration_us=last.duration_us + diff,
                end_us=total_snapped,
            )
            cursor = total_snapped

        # Log diagnostico de precision de rejilla.
        total_us = items[-1].end_us
        log.info(
            "=== DIAGNOSTICO REJILLA FPS === "
            "frame_us=%d us (%.2f fps nominal), "
            "total_video=%d us (%.3f s, %d frames exactos), "
            "items=%d",
            frame_us, US_PER_S / frame_us,
            total_us, total_us / 1e6, total_us // frame_us, len(items),
        )
        unaligned = [it for it in items
                     if it.duration_us % frame_us != 0
                     or it.start_us % frame_us != 0]
        if unaligned:
            log.warning(
                "AUDITORIA FRAME SNAPPING: %d de %d items con duracion o start_no alineados a %d us",
                len(unaligned), len(items), frame_us,
            )
        else:
            log.info("AUDITORIA FRAME SNAPPING: todos los %d items alineados a %d us.", len(items), frame_us)
    else:
        total_us = 0
    return items, total_us
