"""Verificación de los 5 puntos avanzados (sin tocar la UI ni Transcriber):

1) Tipo de edición + nombre por defecto "Nexus Paradoja video" (a nivel de UI se
   verifica en session_restore_check; aquí se valida la generación de proyectos).
2) Escala 'cover' por imagen: clip.scale = max(canvas_w/w, canvas_h/h).
3) Keyframes de zoom: primer frame = 1.0 (relativo a clip.scale), segundo =
   1.10 o 1.15 al final de la duración de cada imagen.
4) Cada imagen dura exactamente su frase (SRT) -> duraciones contiguas.
5) Si la suma de duraciones < duración total del audio, el excedente se reparte
   PROPORCIONALMENTE entre todas las imágenes (el video termina a la vez que el
   audio), nunca estirando solo la última.

Ejecutar desde la raiz:
    & .venv\\Scripts\\python.exe -X utf8 tests\\features_check.py
"""

from __future__ import annotations

import json
import shutil
import struct
import sys
import tempfile
import wave
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.core.capcut_project import CapCutProject  # noqa: E402
from src.core.timeline_builder import (  # noqa: E402
    TimelineItem,
    measure_audio_duration_us,
    redistribute_gap,
)

DRAFTS = r"D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts"
TEMPLATE_NAME = "1.PLANTILLA"
PROJECT_NAME = "Features_Test"


def make_wav(path: Path, secs: float) -> None:
    rate = 16000
    n = int(secs * rate)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(8000 * ((i % rate) / rate))) for i in range(n)))


def make_images(folder: Path, sizes: list[tuple[int, int]]) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for idx, (w, h) in enumerate(sizes, start=1):
        p = folder / f"img{idx:02d}.jpg"
        Image.new("RGB", (w, h), (idx * 20, 40, 90)).save(p)
        out.append(p)
    return out


def main() -> None:
    config.ensure_dirs()
    checks: dict[str, bool] = {}
    ok = True

    # --- redistribución proporcional (punto 5), sin disco -----------------
    imgs_a = [Path("a.jpg"), Path("b.jpg"), Path("c.jpg")]
    base = [
        TimelineItem(0, imgs_a[0], "a", "a", 1.0, 0, 1_000_000, 1_000_000),
        TimelineItem(1, imgs_a[1], "b", "b", 1.0, 1_000_000, 2_000_000, 1_000_000),
        TimelineItem(2, imgs_a[2], "c", "c", 1.0, 2_000_000, 4_000_000, 2_000_000),
    ]
    target = 8_000_000  # suma = 4s -> excedente 4s repartido *2
    out = redistribute_gap(base, target)
    durations = [it.duration_us for it in out]
    checks["redistribución proporcional *2"] = durations == [2_000_000, 2_000_000, 4_000_000]
    checks["redistribución contigua"] = all(
        out[i].end_us == out[i + 1].start_us for i in range(len(out) - 1))
    checks["redistribución termina en audio"] = out[-1].end_us == target
    checks["no se estira solo la última"] = durations[-1] / durations[0] == 2.0

    no_gap = redistribute_gap(base, 4_000_000)
    checks["sin excedente no cambia"] = [i.duration_us for i in no_gap] == [1_000_000, 1_000_000, 2_000_000]

    # --- medición audio real -------------------------------------------------
    audio = Path(tempfile.mkdtemp(prefix="capcutauto_feat_")) / "voz.wav"
    make_wav(audio, 7.0)
    checks["duración real wav"] = measure_audio_duration_us(audio) == 7_000_000

    # --- generación real del proyecto (plantilla real copiada a temp) --------
    work = Path(tempfile.mkdtemp(prefix="capcutauto_feat_"))
    project = CapCutProject(shutil.copytree(Path(DRAFTS) / TEMPLATE_NAME, work / TEMPLATE_NAME))
    sizes = [(1920, 1080), (800, 1200), (1024, 1024)]
    images = make_images(work / "imagenes", sizes)

    # 3 escenas; frases de 1s cada una -> suma 3s < audio 7s -> reparto *7/3
    items = [
        TimelineItem(0, images[0], "frase uno", "frase uno", 1.0, 0, 1_000_000, 1_000_000),
        TimelineItem(1, images[1], "frase dos", "frase dos", 1.0, 1_000_000, 2_000_000, 1_000_000),
        TimelineItem(2, images[2], "frase tres", "frase tres", 1.0, 2_000_000, 3_000_000, 1_000_000),
    ]
    audio_dur = measure_audio_duration_us(audio)
    assert audio_dur is not None
    checks["suma < audio detectado"] = (sum(i.duration_us for i in items) < audio_dur)

    out_dir = project.generate(PROJECT_NAME, items, audio, audio_dur, allow_test_names=True)
    data = json.loads((out_dir / "draft_content.json").read_text(encoding="utf-8"))
    video_segs = [s for t in data["tracks"] if t.get("type") == "video" for s in t["segments"]]
    video_mats = {m["id"]: m for m in data["materials"]["videos"]}

    checks["3 segmentos foto"] = len(video_segs) == 3
    checks["canvas 1920x1080"] = (
        data.get("canvas_config", {}).get("width") == 1920
        and data["canvas_config"].get("height") == 1080)

    # cover: escala por imagen -> max(1920/w, 1080/h)
    for seg, (w, h) in zip(video_segs, sizes):
        cover = max(1920 / w, 1080 / h)
        sc = seg["clip"]["scale"]
        checks[f"cover img {w}x{h}"] = abs(sc["x"] - cover) < 1e-9 and abs(sc["y"] - cover) < 1e-9
        # keyframes relativos: primero 1.0, segundo 1.10/1.15 al final
        ks = {k["property_type"]: k["keyframe_list"] for k in seg["common_keyframes"]}
        for axis in ("KFTypeScaleX", "KFTypeScaleY"):
            lst = ks.get(axis)
            checks[f"keyframes {axis} img {w}x{h}"] = (
                lst is not None
                and lst[0]["time_offset"] == 0
                and lst[0]["values"] == [1.0]
                and lst[1]["time_offset"] == seg["target_timerange"]["duration"]
                and lst[1]["values"][0] in (1.10, 1.15)
                and lst[1]["curveType"] == "Line")

    checks["duraciones proporcionales contiguas"] = all(
        s["target_timerange"]["start"] + s["target_timerange"]["duration"] == n["target_timerange"]["start"]
        for s, n in zip(video_segs, video_segs[1:]))
    checks["termina con el audio"] = (
        video_segs[-1]["target_timerange"]["start"] + video_segs[-1]["target_timerange"]["duration"]
        == audio_dur)
    checks["duración del proyecto == audio"] = data["duration"] == audio_dur
    audio_segs = [s for t in data["tracks"] if t.get("type") == "audio" for s in t["segments"]]
    checks["audio sin recortar"] = audio_segs[0]["target_timerange"]["duration"] == audio_dur

    # capa auxiliar: tamaño natural declarado en material
    checks["materials con tamaño real"] = all(
        (video_mats[s["material_id"]].get("width"), video_mats[s["material_id"]].get("height"))
        == size for s, size in zip(video_segs, sizes))

    for k, v in checks.items():
        print(("  ok  " if v else "  FAIL ") + k)
        ok = ok and v
    shutil.rmtree(out_dir, ignore_errors=True)
    if not ok:
        print("FEATURES_FAIL")
        sys.exit(1)
    print("FEATURES_OK")


if __name__ == "__main__":
    main()