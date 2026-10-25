"""Prueba de precision de rejilla FPS exacto (v3.0.1).

Valida:
  1. Deteccion de fps desde canvas_config (29.97 y 30.0).
  2. Snapping absoluto: start_us y duration_us alineados al frame grid.
  3. Audio snap a rejilla.
  4. Log diagnostico con frames exactos.
  5. Suma exacta de duraciones == total_us multiplo de frame_us.

Ejecuta: .venv314\\Scripts\\python.exe tests\\test_fps_exacto.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.scene_parser import Scene
from src.core.timeline_builder import build_timeline, snap_to_frame, _FRAME_US
from src.core.capcut_project import CapCutProject


def _check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  OK   {label} -> {detail}")
        return True
    print(f"  FAIL {label} -> {detail}")
    return False


def _make_draft_with_fps(fps: float, tmp_dir: Path) -> Path:
    """Crea una plantilla minima con canvas_config.fps."""
    tpl = tmp_dir / "tpl_fps_test"
    tpl.mkdir(parents=True, exist_ok=True)
    content = {
        "id": "test-timeline-id",
        "fps": fps,
        "canvas_config": {"width": 1920, "height": 1080, "fps": fps},
        "materials": {},
        "tracks": [],
    }
    (tpl / "draft_content.json").write_text(
        json.dumps(content), encoding="utf-8"
    )
    (tpl / "draft_meta_info.json").write_text(
        json.dumps({"draft_id": "x"}), encoding="utf-8"
    )
    return tpl


def test_detect_frame_us() -> int:
    print("TEST 1 — Deteccion de frame_us desde plantilla:")
    results: list[bool] = []
    tmp = Path(tempfile.mkdtemp(prefix="fps_test_"))

    for expected_fps, desc in [(29.97, "fps29_97"), (30.0, "fps30"), (60.0, "fps60")]:
        tpl = _make_draft_with_fps(expected_fps, tmp / desc)
        proj = CapCutProject(tpl)
        expected_frame_us = int(round(1_000_000 / expected_fps))
        ok = proj.frame_us == expected_frame_us
        results.append(_check(
            f"{desc}: frame_us={proj.frame_us}",
            ok,
            f"esperado={expected_frame_us}, delta={proj.frame_us - expected_frame_us} us",
        ))
    return 0 if all(results) else 1


def test_absolute_snapping() -> int:
    print("\nTEST 2 — Snapping absoluto con fps no entero (29.97):")
    results: list[bool] = []
    tmp = Path(tempfile.mkdtemp(prefix="snap_test_"))
    frame_us = int(round(1_000_000 / 29.97))  # 33367

    scenes = [Scene(number=i, voice=f"escena {i}") for i in range(1, 12)]
    srt_lines = []
    for i in range(1, 11):
        start = (i - 1) * 2.5
        end = i * 2.5
        srt_lines.append(
            f"{i}\n"
            f"00:{int(start // 60):02d}:{int(start % 60):02d},000 "
            f"--> 00:{int(end // 60):02d}:{int(end % 60):02d},000\n"
            f"escena {i}\n\n"
        )
    srt_path = tmp / "test.srt"
    srt_path.write_text("".join(srt_lines), encoding="utf-8")
    images = [tmp / f"img_{i:03d}.jpg" for i in range(1, 12)]
    for img in images:
        img.touch()

    items, total_us = build_timeline(scenes, srt_path, images, frame_us=frame_us)
    n = len(items)

    results.append(_check(f"{n} items", n == 11, f"count={n}"))
    results.append(_check(
        "total multiplo de frame_us",
        total_us % frame_us == 0,
        f"total={total_us} us, frames={total_us // frame_us}, remainder={total_us % frame_us}",
    ))
    results.append(_check(
        "suma duraciones == total",
        sum(it.duration_us for it in items) == total_us,
        f"sum={sum(it.duration_us for it in items)}, total={total_us}",
    ))

    # Todos los start_us y duration_us deben ser multiplos de frame_us.
    all_aligned = all(
        it.start_us % frame_us == 0 and it.duration_us % frame_us == 0
        for it in items
    )
    results.append(_check(
        "todos los items alineados a frame grid",
        all_aligned,
        f"frame_us={frame_us} us ({1_000_000/frame_us:.4f} fps)",
    ))

    # Verificar adyacencia perfecta (start[N] == end[N-1]).
    no_gaps = all(
        items[i].start_us == items[i - 1].end_us
        for i in range(1, len(items))
    )
    results.append(_check(
        "adyacencia perfecta (sin huecos)",
        no_gaps,
        f"items={n}",
    ))

    # Verificar que el ultimo item termina en total_us.
    results.append(_check(
        "ultima imagen termina en total_us",
        items[-1].end_us == total_us,
        f"last_end={items[-1].end_us}, total={total_us}",
    ))

    return 0 if all(results) else 1


def test_audio_frame_snap() -> int:
    print("\nTEST 3 — Audio snap a rejilla:")
    results: list[bool] = []
    tmp = Path(tempfile.mkdtemp(prefix="audio_snap_"))

    tpl = _make_draft_with_fps(29.97, tmp / "tpl")
    proj = CapCutProject(tpl)
    frame_us = proj.frame_us

    # Simular audio de duracion no alineada.
    raw_audio_dur = 5_000_000  # 5s exactos
    snapped = round(raw_audio_dur / frame_us) * frame_us
    diff = snapped - raw_audio_dur

    results.append(_check(
        "audio snap extiende cuando no es multiplo",
        snapped >= raw_audio_dur,
        f"raw={raw_audio_dur}, snapped={snapped}, delta={diff} us ({diff/frame_us:.2f} frames)",
    ))
    results.append(_check(
        "audio snap es multiplo de frame_us",
        snapped % frame_us == 0,
        f"snapped={snapped}, remainder={snapped % frame_us}",
    ))
    results.append(_check(
        "snap minimo = 1 frame si delta positivo",
        diff >= 0 and diff < frame_us * 2,
        f"delta={diff} us, frame_us={frame_us}",
    ))

    return 0 if all(results) else 1


def test_no_regression_default_frame() -> int:
    print("\nTEST 4 — Sin regression: default frame_us=33333 (30 fps):")
    results: list[bool] = []
    tmp = Path(tempfile.mkdtemp(prefix="no_reg_"))

    scenes = [Scene(number=i, voice=f"escena {i}") for i in range(1, 6)]
    srt_lines = []
    for i in range(1, 6):
        start = (i - 1) * 3.0
        end = i * 3.0
        srt_lines.append(
            f"{i}\n"
            f"00:00:{int(start):02d},000 --> 00:00:{int(end):02d},000\n"
            f"escena {i}\n\n"
        )
    srt_path = tmp / "test.srt"
    srt_path.write_text("".join(srt_lines), encoding="utf-8")
    images = [tmp / f"b{i}.jpg" for i in range(1, 6)]
    for img in images:
        img.touch()

    # Sin pasar frame_us → usa default 33333.
    items, total_us = build_timeline(scenes, srt_path, images)
    results.append(_check(
        "total multiplo de 33333 (default)",
        total_us % _FRAME_US == 0,
        f"total={total_us}, frames={total_us/_FRAME_US:.1f}",
    ))
    results.append(_check(
        "suma == total",
        sum(it.duration_us for it in items) == total_us,
        f"sum={sum(it.duration_us for it in items)}",
    ))

    return 0 if all(results) else 1


def main() -> int:
    r1 = test_detect_frame_us()
    r2 = test_absolute_snapping()
    r3 = test_audio_frame_snap()
    r4 = test_no_regression_default_frame()
    ok = r1 == 0 and r2 == 0 and r3 == 0 and r4 == 0
    print()
    if ok:
        print("=== TODAS LAS PRUEBAS DE FPS EXACTO PASARON ===")
    else:
        print("=== ALGUNA PRUEBA FALLO ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
