"""color_grading_check.py — Valida la estructura HSL y keyframes de color grading.

Verifica que:
1. Se generan 3 materiales HSL (Naranja, Cian, Azul) con base hue/sat/light = 0.
2. Los materiales tienen lumi_hub_path == path (no path/lumi_hub_path).
3. Cada segmento de video tiene enable_hsl = True y extra_material_refs con 3 IDs.
4. Los segmentos tienen keyframes KFTypeHue, KFTypeSaturation, KFTypeLightSensatione.
5. Los materiales HSL tienen hsl_color_type correctos (2, 5, 6).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import config  # noqa: E402
from src.core.capcut_project import CapCutProject  # noqa: E402
from src.core.timeline_builder import (  # noqa: E402
    TimelineItem,
    measure_audio_duration_us,
)


def make_wav(path: Path, secs: float = 3.0) -> None:
    import wave, struct
    rate = 16000
    n = int(secs * rate)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(8000 * ((i % rate) / rate))) for i in range(n)))


def make_dummy_image(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (800, 600), (200, 40, 40)).save(path)


def main() -> None:
    config.ensure_dirs()
    checks: dict[str, bool] = {}
    ok = True

    # Usar plantilla real
    drafts = Path(r"D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts")
    template_name = "1.PLANTILLA"
    project_name = "ColorGrading_Test"

    with tempfile.TemporaryDirectory(prefix="capcutauto_cg_") as td:
        td_path = Path(td)
        audio = td_path / "voz.wav"
        make_wav(audio)
        images = td_path / "imagenes"
        images.mkdir(parents=True, exist_ok=True)
        img = images / "escena01.jpg"
        make_dummy_image(img)

        (td_path / "subs.srt").write_text(
            "1\n00:00:00,100 --> 00:00:01,500\nPrueba de color grading\n\n",
            encoding="utf-8")

        items = [TimelineItem(0, img, "frase", "frase", 1.0, 0, 3_000_000, 3_000_000)]
        audio_dur = measure_audio_duration_us(audio)
        assert audio_dur is not None

        project = CapCutProject(shutil.copytree(
            Path(r"D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts") / "1.PLANTILLA", td_path / "1.PLANTILLA"))
        out = project.generate("ColorGrading_Test", items, audio, audio_dur,
                               allow_test_names=True, subtitle_srt=td_path / "subs.srt")
        data = json.loads((out / "draft_content.json").read_text(encoding="utf-8"))

    materials = data.get("materials", {})
    tracks = data.get("tracks", [])

    # --- 1) Verificar materiales HSL ---
    hsl_materials = materials.get("hsl", [])
    checks[f"HSL: 3 materiales generados"] = len(hsl_materials) == 3

    expected_types = [2, 5, 6]  # Naranja, Cian, Azul
    for i, hsl in enumerate(hsl_materials):
        # Base values = 0
        checks[f"HSL {i}: hue = 0"] = hsl.get("hue") == 0.0
        checks[f"HSL {i}: saturation = 0"] = hsl.get("saturation") == 0.0
        checks[f"HSL {i}: lightness = 0"] = hsl.get("lightness") == 0.0
        # hsl_color_type correcto
        checks[f"HSL {i}: hsl_color_type = {expected_types[i]}"] = hsl.get("hsl_color_type") == expected_types[i]
        # lumi_hub_path == path
        checks[f"HSL {i}: lumi_hub_path == path"] = hsl.get("lumi_hub_path") == hsl.get("path")
        # type = hsl
        checks[f"HSL {i}: type = hsl"] = hsl.get("type") == "hsl"
        # custom_color presente
        checks[f"HSL {i}: custom_color presente"] = bool(hsl.get("custom_color"))
        # resource_id = ""
        checks[f"HSL {i}: resource_id = ''"] = hsl.get("resource_id") == ""
        # source_platform = 0
        checks[f"HSL {i}: source_platform = 0"] = hsl.get("source_platform") == 0

    # --- 2) Verificar segmentos de video ---
    video_tracks = [t for t in tracks if t.get("type") == "video"]
    checks["1 pista de video"] = len(video_tracks) == 1

    video_track = video_tracks[0]
    segments = video_track.get("segments", [])
    checks[f"Segmentos de video: {len(segments)} generados"] = len(segments) > 0

    for seg in segments:
        # enable_hsl = True
        checks["Segmento: enable_hsl = True"] = seg.get("enable_hsl") is True

        # extra_material_refs tiene 6 IDs (3 HSL + 3 adjust)
        refs = seg.get("extra_material_refs", [])
        checks["Segmento: 6 refs (3 HSL + 3 adjust) en extra_material_refs"] = len(refs) == 6

    # --- 3) Verificar keyframes de color grading (HSL) ---
    hsl_prop_types = {"KFTypeHue", "KFTypeSaturation", "KFTypeLightSensatione"}
    found_hsl_props = set()
    for seg in segments:
        for kf in seg.get("common_keyframes", []):
            pt = kf.get("property_type")
            if pt in hsl_prop_types:
                found_hsl_props.add(pt)

    for pt in hsl_prop_types:
        checks[f"Keyframe: {pt} presente"] = pt in found_hsl_props

    # --- 4) Verificar materiales HSL tienen hsl_color_type correctos ---
    hsl_types_found = {hsl.get("hsl_color_type") for hsl in hsl_materials}
    checks["HSL: tiene tipos 2, 5, 6"] = hsl_types_found == {2, 5, 6}

    # --- Imprimir resultados ---
    for k, v in checks.items():
        print(("  ok  " if v else "  FAIL ") + k)
        ok = ok and v

    print()
    if not ok:
        print("COLOR_GRADING_FAIL")
        sys.exit(1)
    print("COLOR_GRADING_OK")


if __name__ == "__main__":
    import json
    import shutil
    main()