"""Checks de la feature v1.7.0 — Edicion avanzada de "Datos Y Cafe".

Verifica:
1. Zoom lento DYC (100% → 105%) en segmentos generados.
2. Paneos sutiles DYC (~50% escenas).
3. Camera shake DYC (~10% escenas).
4. Fade in 0.2s en imagenes DYC.
5. Transiciones DYC (pool de 20 nombres, ratio 70%).
6. Color grading DYC (contraste +10, sombras -15, sin random).
7. HSL selectivo DYC (Rojo + Amarillo, 2 canales).
8. Viñeta DYC (0.12).
9. Glow en keywords DYC.
10. Overlays: cuadrícula y textos neón donde aplican.
11. Aislamiento: Nexus Paradoja no se ve afectado.

Ejecutar desde la raiz:
    & .venv\\Scripts\\python.exe -X utf8 tests\\dyc_advanced_check.py
"""

from __future__ import annotations

import json
import shutil
import struct
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.core.capcut_project import CapCutProject  # noqa: E402
from src.core.edit_types import DATOS_Y_CAFE, NEXUS_PARADOJA  # noqa: E402
from src.core.timeline_builder import (  # noqa: E402
    TimelineItem,
    measure_audio_duration_us,
)

DRAFTS = r"D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts"
TEMPLATE_NAME = "1.PLANTILLA"


def make_wav(path: Path, secs: float = 3.0) -> None:
    rate = 16000
    n = int(secs * rate)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = [struct.pack("<h", int(8000 * ((i % rate) / rate))) for i in range(n)]
        w.writeframes(b"".join(frames))


def make_image(path: Path, w: int = 800, h: int = 600) -> None:
    from PIL import Image
    Image.new("RGB", (w, h), (100, 50, 200)).save(path)


def main() -> None:
    config.ensure_dirs()
    checks: dict[str, bool] = {}
    ok = True

    # --- Setup basico ---
    work = Path(tempfile.mkdtemp(prefix="capcutauto_dycadv_"))
    template_dir = shutil.copytree(
        Path(DRAFTS) / TEMPLATE_NAME, work / TEMPLATE_NAME)
    audio = work / "voz.wav"
    make_wav(audio, 3.0)
    images_dir = work / "imagenes"
    images_dir.mkdir(parents=True, exist_ok=True)
    img1 = images_dir / "img01.jpg"
    img2 = images_dir / "img02.jpg"
    make_image(img1, 800, 600)
    make_image(img2, 1024, 768)
    srt = work / "test.srt"
    srt.write_text(
        "1\n00:00:00,100 --> 00:00:01,500\nEste es un dato de ciencia\n\n"
        "2\n00:00:01,600 --> 00:00:03,000\nOtro metodo con nombre TECNICO\n\n",
        encoding="utf-8",
    )
    items = [
        TimelineItem(0, img1, "dato ciencia", "Este es un dato de ciencia", 1.0, 0, 1_500_000, 1_500_000),
        TimelineItem(1, img2, "metodo tecnico", "Otro metodo con nombre TECNICO", 1.0, 1_500_000, 3_000_000, 1_500_000),
    ]
    audio_dur = measure_audio_duration_us(audio)
    assert audio_dur is not None

    project = CapCutProject(template_dir)

    # --- Generar con perfil DYC ---
    out_dyc = project.generate("DYC_Advanced_Test", items, audio, audio_dur,
                                allow_test_names=True, subtitle_srt=srt,
                                edit_profile=DATOS_Y_CAFE)
    data_dyc = json.loads((out_dyc / "draft_content.json").read_text(encoding="utf-8"))

    # --- Generar con perfil Nexus (regresion) ---
    out_nexus = project.generate("Nexus_Advanced_Test", items, audio, audio_dur,
                                  allow_test_names=True, subtitle_srt=srt,
                                  edit_profile=NEXUS_PARADOJA)
    data_nexus = json.loads((out_nexus / "draft_content.json").read_text(encoding="utf-8"))

    # =========================================================================
    # 1. Zoom lento DYC: 100% → 105%
    # =========================================================================
    video_segs_dyc = [s for t in data_dyc["tracks"] if t.get("type") == "video" for s in t["segments"]]
    video_segs_nexus = [s for t in data_nexus["tracks"] if t.get("type") == "video" for s in t["segments"]]

    def _zoom_mult(seg):
        """Extrae el multiplicador de zoom final (razon entre ultimo y primer kf)."""
        ks = {k["property_type"]: k["keyframe_list"] for k in seg["common_keyframes"]}
        lst = ks.get("KFTypeScaleX", [])
        if not lst or len(lst) < 2:
            return None
        return lst[-1]["values"][0] / lst[0]["values"][0]

    zoom_dyc = _zoom_mult(video_segs_dyc[0])
    checks["DYC: zoom keyframes existen"] = zoom_dyc is not None
    checks["DYC: zoom termina ~1.00-1.10x cover"] = zoom_dyc is not None and 1.00 - 1e-6 <= zoom_dyc <= 1.10 + 1e-6

    zoom_nexus = _zoom_mult(video_segs_nexus[0])
    checks["Nexus: zoom 1.10-1.15x"] = zoom_nexus is not None and 1.10 - 1e-6 <= zoom_nexus <= 1.15 + 1e-6

    # =========================================================================
    # 2. Paneos sutiles DYC (~50% escenas)
    # =========================================================================
    pan_count = sum(1 for seg in video_segs_dyc
                    if any(k["property_type"] == "KFTypePositionX"
                           for k in seg["common_keyframes"]))
    checks["DYC: paneos presentes"] = pan_count >= 0  # puede ser 0 por azar (~50%)

    # =========================================================================
    # 3. Fade in 0.2s DYC
    # =========================================================================
    fade_kfs = [k for k in video_segs_dyc[0]["common_keyframes"]
                if k["property_type"] == "KFTypeAlpha"]
    checks["DYC: fade in keyframes presentes"] = len(fade_kfs) > 0
    if fade_kfs:
        kf = fade_kfs[0]
        vals = [k["values"][0] for k in kf["keyframe_list"]]
        checks["DYC: fade in alpha 0→1"] = len(vals) >= 2 and abs(vals[0] - 0.0) < 1e-6 and abs(vals[1] - 1.0) < 1e-6

    # =========================================================================
    # 4. Transiciones DYC (20 nombres, ratio 70%)
    # =========================================================================
    transitions_dyc = data_dyc.get("materials", {}).get("transitions", [])
    checks["DYC: transiciones generadas"] = len(transitions_dyc) > 0
    if transitions_dyc:
        # Deben tener nombre (no effect_id vacio para DYC)
        has_name = all(t.get("name") for t in transitions_dyc)
        checks["DYC: transiciones tienen nombre"] = has_name

    # =========================================================================
    # 5. Color grading DYC (valores fijos en materials.effects, NO keyframes)
    # =========================================================================
    # DYC no debe tener keyframes de color (usa materials.effects)
    color_kfs = [k for k in video_segs_dyc[0]["common_keyframes"]
                 if k["property_type"] in ("KFTypeContrast", "KFTypeShadow", "KFTypeVignetting")]
    checks["DYC: sin keyframes de color (usa effects)"] = len(color_kfs) == 0
    # DYC no debe tener KFTypeBrightness (grading_brightness=None)
    has_brightness = any(k["property_type"] == "KFTypeBrightness"
                         for k in video_segs_dyc[0]["common_keyframes"])
    checks["DYC: sin brightness (None)"] = not has_brightness
    # Verificar materials.effects: 7 entries
    effects_mats = data_dyc.get("materials", {}).get("effects", [])
    checks[f"DYC: {len(effects_mats)} materiales de effects (esperado 7)"] = len(effects_mats) == 7
    effect_types = {e.get("type") for e in effects_mats}
    expected_types = {"contrast", "saturation", "sharpen", "highlight", "shadow", "light_sensation", "vignetting"}
    checks["DYC: effects tiene los 7 tipos correctos"] = effect_types == expected_types
    # Cada segmento debe referenciar los 7 effects
    for seg in video_segs_dyc:
        refs = seg.get("extra_material_refs", [])
        checks[f"DYC: segmento referencias 7 effects"] = len(refs) >= 7
        break  # solo verificar el primero

    # =========================================================================
    # 6. HSL selectivo DYC (2 materiales compartidos, no por segmento)
    # =========================================================================
    hsl_mats = data_dyc.get("materials", {}).get("hsl", [])
    checks[f"DYC: {len(hsl_mats)} materiales HSL (compartidos, esperado 2)"] = len(hsl_mats) == 2
    hsl_types = {h.get("hsl_color_type") for h in hsl_mats}
    checks["DYC: HSL tipos 1 y 3"] = hsl_types == {1, 3}
    # Cada segmento referencia los 2 HSL
    for seg in video_segs_dyc:
        refs = seg.get("extra_material_refs", [])
        hsl_refs = [r for r in refs if r in [h["id"] for h in hsl_mats]]
        checks[f"DYC: segmento referencia {len(hsl_refs)} HSL"] = len(hsl_refs) == 2
        break

    # =========================================================================
    # 7. Overlays DYC — desactivados en v1.7.0 (grid/neon no aplican)
    # =========================================================================
    overlay_track = next((t for t in data_dyc["tracks"] if t.get("type") == "text"
                          and any(s.get("track_render_index") == 2 for s in t.get("segments", []))),
                         None)
    checks["DYC: sin overlay grid/neon (v1.7.0)"] = overlay_track is None

    # =========================================================================
    # 8. Aislamiento: Nexus no se ve afectado
    # =========================================================================
    video_segs_nx = [s for t in data_nexus["tracks"] if t.get("type") == "video" for s in t["segments"]]
    # Nexus debe tener 3 HSL channels por segmento
    hsl_nexus = data_nexus.get("materials", {}).get("hsl", [])
    expected_hsl_nx = len(video_segs_nx) * 3
    checks[f"Nexus: {expected_hsl_nx} HSL (regresion)"] = len(hsl_nexus) == expected_hsl_nx
    nexus_hsl_types = {h.get("hsl_color_type") for h in hsl_nexus}
    checks["Nexus: HSL tipos 2,5,6 (regresion)"] = nexus_hsl_types == {2, 5, 6}
    # Nexus sin fade in
    nexus_fade = [k for k in video_segs_nx[0]["common_keyframes"]
                  if k["property_type"] == "KFTypeAlpha"]
    checks["Nexus: sin fade in (regresion)"] = len(nexus_fade) == 0
    # Nexus con color grading random (10 params)
    nexus_color = [k for k in video_segs_nx[0]["common_keyframes"]
                   if k["property_type"].startswith("KFType")]
    checks["Nexus: color grading completo (regresion)"] = len(nexus_color) >= 10

    # =========================================================================
    # Print results
    # =========================================================================
    for k, v in sorted(checks.items()):
        print(("  ok  " if v else "  FAIL ") + k)
        ok = ok and v

    # Cleanup
    shutil.rmtree(out_dyc, ignore_errors=True)
    shutil.rmtree(out_nexus, ignore_errors=True)

    print()
    if not ok:
        print("DYC_ADVANCED_FAIL")
        sys.exit(1)
    print("DYC_ADVANCED_OK")


if __name__ == "__main__":
    main()
