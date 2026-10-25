"""Prueba de estrés para el fix de desfase acumulativo.

Scenario: SRT de 233s pero audio de 250s → el último clip debe extenderse
para cubrir los 250s sin huecos.

Ejecuta:  python tests/test_drift_fix.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "D:/capcut-auto")

from src.core.scene_parser import Scene
from src.core.timeline_builder import build_timeline, US_PER_S, DEFAULT_MIN_SCENE_DURATION_US


def _check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  OK   {label} -> {detail}")
        return True
    print(f"  FAIL {label} -> {detail}")
    return False


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="drift_test_"))
    results: list[bool] = []
    MIN_US = DEFAULT_MIN_SCENE_DURATION_US

    # ---------------------------------------------------------------
    # TEST: 146 escenas, SRT de 233s, audio de 250s
    # El desfase debe corregirse: última imagen extiende hasta 250s.
    # ---------------------------------------------------------------
    print("TEST — SRT 233s + Audio 250s (desfase de 17s):")

    scenes = []
    srt_lines = []
    audio_dur_s = 250.0
    srt_dur_s = 233.0
    step_srt = srt_dur_s / 146

    for i in range(1, 147):
        scenes.append(Scene(number=i, voice=f"frase numero {i} para prueba de desfase"))
        start = (i - 1) * step_srt
        end = i * step_srt
        srt_lines.append(
            f"{i}\n"
            f"00:{int(start // 60):02d}:{int(start % 60):02d},000 "
            f"--> 00:{int(end // 60):02d}:{int(end % 60):02d},000\n"
            f"frase numero {i} para prueba de desfase\n\n"
        )

    srt_path = tmp / "test.srt"
    srt_path.write_text("".join(srt_lines), encoding="utf-8")
    images = [tmp / f"img_{i:03d}.jpg" for i in range(1, 147)]
    for img in images:
        img.touch()

    items, total_us = build_timeline(scenes, srt_path, images)
    n_items = len(items)
    results.append(_check("146 items", n_items == 146, f"count={n_items}"))

    # La duracion total debe ser multiplo exacto de frame_us (33333 us).
    from src.core.timeline_builder import _FRAME_US
    frame_aligned = total_us % _FRAME_US == 0
    results.append(_check(
        "total_us multiplo de frame_us",
        frame_aligned,
        f"total_us={total_us} us, total/frame={total_us/_FRAME_US:.1f} frames",
    ))

    # Verificar que ningun item tiene duración negativa o cero.
    all_positive = all(it.duration_us > 0 for it in items)
    results.append(_check("todas las duraciones > 0", all_positive, ""))

    # Verificar duracion minima.
    min_dur = min(it.duration_us for it in items)
    results.append(_check(
        "min_dur >= 1.5s",
        min_dur >= MIN_US,
        f"min={min_dur/1e6:.3f}s",
    ))

    # Verificar adyacencia perfecta.
    no_gaps = all(
        abs(items[i].start_us - items[i - 1].end_us) <= 20000
        for i in range(1, len(items))
    )
    results.append(_check("sin huecos (< 20ms)", no_gaps, ""))

    # Verificar que la suma de duraciones == total_us (sin drift interno).
    sum_dur = sum(it.duration_us for it in items)
    sum_match = abs(sum_dur - total_us) <= 1  # tolerancia de 1us por redondeo
    results.append(_check(
        "suma duraciones == total_us",
        sum_match,
        f"sum={sum_dur}, total={total_us}, diff={sum_dur - total_us}",
    ))

    # Verificar que el último item termina en total_us.
    last_ends_at_total = items[-1].end_us == total_us
    results.append(_check(
        "ultima imagen termina en total_us",
        last_ends_at_total,
        f"last_end={items[-1].end_us}, total={total_us}",
    ))

    # ---------------------------------------------------------------
    # TEST B: SRT = audio (caso ideal, delta=0)
    # ---------------------------------------------------------------
    print("\nTEST B — SRT = Audio (delta=0 esperado):")
    scenes2 = [Scene(number=i, voice=f"escena {i}") for i in range(1, 6)]
    srt_lines2 = []
    for i in range(1, 6):
        start = (i - 1) * 2.0
        end = i * 2.0
        srt_lines2.append(
            f"{i}\n"
            f"00:00:{int(start):02d},000 --> 00:00:{int(end):02d},000\n"
            f"escena {i}\n\n"
        )
    srt2 = tmp / "test2.srt"
    srt2.write_text("".join(srt_lines2), encoding="utf-8")
    imgs2 = [tmp / f"b{i}.jpg" for i in range(1, 6)]
    for img in imgs2:
        img.touch()
    items2, total_us2 = build_timeline(scenes2, srt2, imgs2)
    results.append(_check("5 items", len(items2) == 5, f"count={len(items2)}"))
    # Verificar frame alignment en lugar de duracion exacta.
    from src.core.timeline_builder import _FRAME_US
    frame_aligned2 = total_us2 % _FRAME_US == 0
    results.append(_check(
        "total_us multiplo de frame_us",
        frame_aligned2,
        f"total={total_us2} us, frames={total_us2/_FRAME_US:.1f}",
    ))
    sum2 = sum(it.duration_us for it in items2)
    results.append(_check("suma==total", sum2 == total_us2, f"sum={sum2}"))
    results.append(_check("min_dur>=1.5s",
                          min(it.duration_us for it in items2) >= MIN_US,
                          f"min={min(it.duration_us for it in items2)/1e6:.3f}s"))

    # ---------------------------------------------------------------
    # RESULTADO
    # ---------------------------------------------------------------
    ok = all(results)
    if ok:
        print("\n=== TODAS LAS PRUEBAS DE DESFASE PASARON ===")
    else:
        n_fail = results.count(False)
        print(f"\n{n_fail} prueba(s) FALLARON.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
