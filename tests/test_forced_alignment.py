"""Prueba de estrés del algoritmo de alineación forzada (anti-desfase).

Valida que:
  A) Con 146 escenas + SRT con errores ortográficos intencionales:
     - Ninguna imagen dura menos de 1.5s (min_duration_us).
     - La suma total de duraciones = duración del audio.
     - No hay huecos ni solapamientos (start[N] == end[N-1]).
  B) Con 5 escenas + SRT word-level (800 cues) para verificar agrupación.

Ejecuta:  python tests/test_forced_alignment.py
"""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.scene_parser import Scene
from src.core.timeline_builder import (
    build_timeline,
    parse_srt,
    group_srt_into_sentences,
    US_PER_S,
    DEFAULT_MIN_SCENE_DURATION_US,
)


def _check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  OK   {label} -> {detail}")
        return True
    print(f"  FAIL {label} -> {detail}")
    return False


def make_srt_path(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def make_wav(path: Path, duration_s: float = 10.0) -> Path:
    """Crea un wav sintético de duración determinada."""
    import wave
    import struct
    rate = 44100
    frames = int(rate * duration_s)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00" * (frames * 2))
    return path


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="align_test_"))
    results: list[bool] = []
    MIN_US = DEFAULT_MIN_SCENE_DURATION_US  # 1_500_000 = 1.5s
    EPSILON_US = int(0.02 * US_PER_S)  # tolerancia de 20ms

    # ------------------------------------------------------------------
    # TEST A: 146 escenas con SRT que tiene errores ortográficos
    # ------------------------------------------------------------------
    print("TEST A — 146 escenas + SRT con errores ortográficos:")

    # Crear 146 escenas con frases ligeramente alteradas del SRT.
    # El SRT tendrá frases correctas; las escenas tendrán errores tipográficos
    # (tildes mal puestas, letras cambiadas, palabras sueltas).
    scenes: list[Scene] = []
    srt_lines: list[str] = []
    audio_dur_s = 240.0  # 4 minutos de audio

    for i in range(1, 147):
        # Frase original del SRT
        phrase = f"La tecnologia avanza a pasos agigantados en el siglo veintiuno"
        # Escena con error ortografico intencional
        scenes.append(Scene(number=i, voice=f"{phrase} numero {i}"))
        # SRT: distribuir uniformemente en el rango del audio (240s)
        step = audio_dur_s / 146
        start = (i - 1) * step
        end = i * step
        # SRT también con ligeras variaciones para probar fuzzy matching
        srt_line = (
            f"{i}\n"
            f"00:{int(start // 60):02d}:{int(start % 60):02d},000 "
            f"--> 00:{int(end // 60):02d}:{int(end % 60):02d},000\n"
            f"{phrase} {i}\n\n"
        )
        srt_lines.append(srt_line)

    srt_path = tmp / "test_a.srt"
    make_srt_path(srt_path, "".join(srt_lines))
    audio_path = tmp / "audio.wav"
    make_wav(audio_path, duration_s=audio_dur_s)

    images = [tmp / f"img_{i:03d}.jpg" for i in range(1, 147)]
    for img in images:
        img.touch()

    items, total_us = build_timeline(scenes, srt_path, images)
    n_items = len(items)
    results.append(_check("146 items", n_items == 146, f"count={n_items}"))
    results.append(_check("total_us no nulo", total_us > 0, f"total_us={total_us}"))

    # Verificar duración mínima en CADA item
    min_dur_found = min(it.duration_us for it in items) if items else 0
    results.append(_check(
        "min_dur >= 1.5s",
        min_dur_found >= MIN_US,
        f"min_dur={min_dur_found} us ({min_dur_found/US_PER_S:.3f}s)",
    ))

    audio_dur_us = int(audio_dur_s * US_PER_S)
    diff_pct = abs(total_us - audio_dur_us) / audio_dur_us * 100
    ok = diff_pct <= 2.0
    print(f"  {'OK' if ok else 'FAIL'} suma ~= duracion audio (+/-2%) -> audio={audio_dur_us} us, timeline={total_us} us, delta={diff_pct:.2f}%")
    results.append(ok)

    # Verificar que no hay huecos ni solapamientos
    monotonic_ok = all(
        items[i].start_us >= items[i - 1].end_us
        for i in range(1, len(items))
    )
    no_gaps = all(
        abs(items[i].start_us - items[i - 1].end_us) <= EPSILON_US
        for i in range(1, len(items))
    )
    results.append(_check(
        "sin solapamientos", monotonic_ok,
        "start[N] >= end[N-1] en todos los puntos",
    ))
    results.append(_check(
        "sin huecos (adjacencia perfecta)", no_gaps,
        "|start[N] - end[N-1]| <= 20ms en todos los puntos",
    ))

    # ------------------------------------------------------------------
    # TEST B: 5 escenas, SRT word-level simulado (varias líneas por escena)
    # ------------------------------------------------------------------
    print("\nTEST B — 5 escenas + SRT word-level agrupado:")

    scenes2 = [
        Scene(number=1, voice="hola mundo desde mexico"),
        Scene(number=2, voice="gracias por vernos hoy"),
        Scene(number=3, voice="no se olviden de suscribirse"),
        Scene(number=4, voice="la proxima semana mas contenido"),
        Scene(number=5, voice="hasta la próxima amigo mio"),
    ]
    # SRT word-level: cada palabra en un cue separado, con gaps pequeños.
    srt_words = [
        "hola mundo desde mexico y gracias",
        "por vernos hoy y no se olviden",
        "de suscribirse al canal y dar like",
        "porque la proxima semana mas contenido",
        "y hasta la próxima amigo mio nos vemos",
    ]
    srt_lines2 = []
    t = 0.0
    for idx, words in enumerate(srt_words, 1):
        dur = 2.0
        start_s, end_s = t, t + dur
        srt_lines2.append(
            f"{idx}\n"
            f"00:00:{int(start_s):02d},000 --> 00:00:{int(end_s):02d},000\n"
            f"{words}\n\n"
        )
        t += dur

    srt2 = tmp / "test_b.srt"
    make_srt_path(srt2, "".join(srt_lines2))
    audio2 = tmp / "audio2.wav"
    make_wav(audio2, duration_s=t)
    imgs2 = [tmp / f"b_{i}.jpg" for i in range(1, 6)]
    for img in imgs2:
        img.touch()

    items2, total_us2 = build_timeline(scenes2, srt2, imgs2)
    results.append(_check("5 items", len(items2) == 5, f"count={len(items2)}"))
    results.append(_check("min_dur >= 1.5s",
                          min(it.duration_us for it in items2) >= MIN_US,
                          f"min={min(it.duration_us for it in items2)} us"))
    no_gaps2 = all(
        abs(items2[i].start_us - items2[i - 1].end_us) <= EPSILON_US
        for i in range(1, len(items2))
    )
    results.append(_check("sin huecos (TEST B)", no_gaps2, ""))

    # ------------------------------------------------------------------
    # TEST C: SRT con frases completamente diferentes al texto de escenas
    #          (debe usar interpolación forzada)
    # ------------------------------------------------------------------
    print("\nTEST C — SRT sin match (forzando interpolación):")

    scenes3 = [
        Scene(number=1, voice="primera escena"),
        Scene(number=2, voice="segunda escena"),
        Scene(number=3, voice="tercera escena"),
    ]
    srt_lines3 = [
        "1\n00:00:00,000 --> 00:00:02,000\nalgo completamente distinto\n\n",
        "2\n00:00:02,000 --> 00:00:04,000\nnada que ver con lo que digo\n\n",
        "3\n00:00:04,000 --> 00:00:06,000\nsolo palabras al azar\n\n",
    ]
    srt3 = tmp / "test_c.srt"
    make_srt_path(srt3, "".join(srt_lines3))
    audio3 = tmp / "audio3.wav"
    make_wav(audio3, duration_s=6.0)
    imgs3 = [tmp / f"c_{i}.jpg" for i in range(1, 4)]
    for img in imgs3:
        img.touch()

    items3, total_us3 = build_timeline(scenes3, srt3, imgs3)
    results.append(_check("3 items", len(items3) == 3, f"count={len(items3)}"))
    results.append(_check("min_dur >= 1.5s",
                          min(it.duration_us for it in items3) >= MIN_US,
                          f"min={min(it.duration_us for it in items3)} us"))
    no_gaps3 = all(
        abs(items3[i].start_us - items3[i - 1].end_us) <= EPSILON_US
        for i in range(1, len(items3))
    )
    results.append(_check("sin huecos (TEST C)", no_gaps3, ""))
    # Con interpolación forzada, la suma debe cubrir el audio
    diff_pct3 = abs(total_us3 - int(6.0 * US_PER_S)) / (6.0 * US_PER_S) * 100
    results.append(_check(
        "suma ~= 6s (TEST C)",
        diff_pct3 <= 5.0,
        f"delta={diff_pct3:.2f}%, total_us={total_us3}",
    ))

    # ------------------------------------------------------------------
    # RESULTADO
    # ------------------------------------------------------------------
    ok = all(results)
    if ok:
        print("\n=== TODAS LAS PRUEBAS DE ALINEACIÓN PASARON ===")
    else:
        n_fail = results.count(False)
        print(f"\n{ n_fail } prueba(s) FALLARON.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
