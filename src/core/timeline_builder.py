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
MIN_SCENE_DURATION_US = int(1.5 * US_PER_S)
_FRAME_US = 33333
DYC_CTA_INTERMEDIO_PCT = 0.37
CTA_FINAL_FALLBACK_RATIO = 0.90
DYC_CHROMA_INTENSITY = 0.25

_CTA_PATTERNS = (
    r"suscribete",
    r"suscribirse",
    r"suscribete al canal",
    r"subscribete",
    r"subscribirse",
    r"suscribete si quieres",
)
_CTA_RE = re.compile("|".join(f"(?:{p})" for p in _CTA_PATTERNS), re.IGNORECASE)
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
    if target_us > 0 and abs(sum_synced - target_us) / target_us < 0.05:
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


def find_cta_intermedio_start(total_duration_us):
    raw = int(total_duration_us * DYC_CTA_INTERMEDIO_PCT)
    return (raw // _FRAME_US) * _FRAME_US


def find_cta_final_starts(srt_path, total_duration_us):
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


def sync_last_item_to_audio_end(items, fin_audio_us, min_duration_us=1_000_000):
    if not items:
        return items
    last = items[-1]
    if last.image_path is None or last.duration_us <= 0:
        return items
    new_dur = max(fin_audio_us - last.start_us, min_duration_us)
    return list(items[:-1]) + [
        replace(last, duration_us=new_dur, end_us=fin_audio_us)
    ]
def match_scenes_to_srt(
    scenes, srt_path, match_threshold=75.0,
):
    from rapidfuzz import fuzz
    entries = parse_srt(Path(srt_path))
    entries = [e for e in entries if e[1] > e[0]]

    def _norm(text):
        text = text.lower()
        text = re.sub(r"[^\w\s-]", " ", text)
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = re.sub(r"[^\w\s-]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    gap_threshold = 0.3
    gap_indices = set()
    for k in range(1, len(entries)):
        if entries[k][0] - entries[k - 1][1] > gap_threshold:
            gap_indices.add(k)

    results = []
    no_match = 0
    for i, scene in enumerate(scenes):
        key = scene.key_text
        if not key:
            results.append((i, 0.0, 0.0, False))
            no_match += 1
            continue
        norm_key = _norm(key)
        words = norm_key.split()
        n_words = len(words)
        n_start = min(4, max(1, n_words // 2))
        n_end = min(4, max(1, n_words // 2))
        prefix = " ".join(words[:n_start])
        suffix = " ".join(words[-n_end:]) if n_end < n_words else prefix

        prev_end = results[i - 1][2] if i > 0 and results[i - 1][3] else 0.0
        start_idx = None
        start_score = 0.0
        for k, (s, e, txt) in enumerate(entries):
            if s < prev_end - 0.05:
                continue
            norm_cue = _norm(txt)
            score = fuzz.partial_ratio(prefix, norm_cue)
            if score >= match_threshold and score > start_score:
                start_score = score
                start_idx = k
                break

        end_idx = None
        end_score = 0.0
        search_from = start_idx if start_idx is not None else 0
        for k in range(search_from, len(entries)):
            if k in gap_indices and k > search_from:
                break
            norm_cue = _norm(entries[k][2])
            score = fuzz.partial_ratio(suffix, norm_cue)
            if score >= match_threshold and score > end_score:
                end_score = score
                end_idx = k

        if start_idx is not None:
            start_s = entries[start_idx][0]
            end_s = entries[end_idx][1] if end_idx is not None else entries[start_idx][1]
            results.append((i, start_s, end_s, True))
        else:
            fallback_idx = None
            for k in range(len(entries) - 1, -1, -1):
                if entries[k][1] <= prev_end:
                    fallback_idx = k
                    break
            if fallback_idx is not None:
                results.append((i, entries[fallback_idx][0], entries[fallback_idx][1], True))
            else:
                results.append((i, 0.0, 0.0, False))
                no_match += 1

    log.info(
        "Match escenas<->SRT: %d/%d escenas emparejadas (umbral=%.0f).",
        len(scenes) - no_match, len(scenes), match_threshold,
    )
    return results, no_match


def build_timeline(
    scenes, srt_path, image_paths,
    cancel_event=None, match_threshold=75.0,
):
    matches, no_match = match_scenes_to_srt(scenes, srt_path, match_threshold)
    items = []
    for i, start_s, end_s, matched in matches:
        if cancel_event is not None and cancel_event.is_set():
            raise GenerationCancelled("Generacion cancelada por el usuario.")
        scene = scenes[i]
        image_path = image_paths[i] if i < len(image_paths) else None
        key = scene.key_text
        if not key or not matched:
            items.append(TimelineItem(i, image_path, "", "", 0.0, 0, 0))
            continue
        start_us = int(round(start_s * US_PER_S))
        end_us = int(round(end_s * US_PER_S))
        duration_us = max(end_us - start_us, MIN_SCENE_DURATION_US)
        log.info(
            "Escena #%d OK - [%s .. %s] (%d us) - score=%d",
            scene.number, f"{start_s:.2f}s", f"{end_s:.2f}s", duration_us,
            int(matches[i][3] * 100) if matches[i][3] else 0,
        )
        items.append(
            TimelineItem(i, image_path, key, key, 1.0, start_us, end_us, duration_us)
        )

    n = len(items)
    for i in range(n):
        if items[i].duration_us == 0 and items[i].scene_text:
            prev_idx = next((p for p in range(i - 1, -1, -1) if items[p].duration_us > 0), None)
            next_idx = next((p for p in range(i + 1, n) if items[p].duration_us > 0), None)
            if prev_idx is not None and next_idx is not None:
                t_start = items[prev_idx].end_us
                t_end = items[next_idx].start_us
                steps = next_idx - prev_idx
                step_idx = i - prev_idx
                if t_end > t_start and steps > 0:
                    dur_step = (t_end - t_start) / steps
                    est_start = t_start + step_idx * dur_step
                    est_end = t_start + (step_idx + 1) * dur_step
                else:
                    est_start = t_start
                    est_end = t_start + MIN_SCENE_DURATION_US
            elif prev_idx is not None:
                est_start = items[prev_idx].end_us
                est_end = est_start + MIN_SCENE_DURATION_US
            elif next_idx is not None:
                est_end = items[next_idx].start_us
                est_start = max(0, est_end - MIN_SCENE_DURATION_US)
            else:
                est_start = 0
                est_end = MIN_SCENE_DURATION_US
            est_start_us = int(round(est_start))
            est_end_us = int(round(max(est_end, est_start_us + MIN_SCENE_DURATION_US)))
            items[i] = replace(items[i],
                start_us=est_start_us, end_us=est_end_us,
                duration_us=est_end_us - est_start_us,
            )
            log.info("Escena #%d interpolada - [%d .. %d] us", scenes[i].number,
                     est_start_us, est_end_us)

    for i in range(n):
        it = items[i]
        if it.duration_us < MIN_SCENE_DURATION_US:
            old_end = it.end_us
            new_end = it.start_us + MIN_SCENE_DURATION_US
            items[i] = replace(it, end_us=new_end, duration_us=MIN_SCENE_DURATION_US)
            log.info("Escena #%d extendida a minimo 1.5s (%d -> %d us)",
                     scenes[i].number, old_end, new_end)

    if items:
        max_end = max(it.end_us for it in items)
        last = items[-1]
        if last.end_us < max_end:
            items[-1] = replace(last, end_us=max_end)

    for i in range(1, len(items)):
        if items[i].start_us < items[i - 1].end_us:
            old_start = items[i].start_us
            items[i] = replace(items[i], start_us=items[i - 1].end_us)
            items[i] = replace(items[i], duration_us=items[i].end_us - items[i].start_us)
            if items[i].duration_us < MIN_SCENE_DURATION_US:
                items[i] = replace(items[i],
                    end_us=items[i].start_us + MIN_SCENE_DURATION_US,
                    duration_us=MIN_SCENE_DURATION_US,
                )
            log.info("Escena #%d monotonia corregida: %d -> %d us",
                     scenes[i].number, old_start, items[i].start_us)

    total_us = max((it.end_us for it in items), default=0)
    suma = sum(it.duration_us for it in items)
    if suma > total_us and total_us > 0:
        factor = total_us / suma
        cursor = 0
        nuevos = []
        for it in items:
            dur = max(round(it.duration_us * factor), 1)
            nuevos.append(replace(it, start_us=cursor, end_us=cursor + dur, duration_us=dur))
            cursor += dur
        items = nuevos
        total_us = cursor
    return items, total_us
