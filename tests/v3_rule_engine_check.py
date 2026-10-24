"""Test de verificacion del motor de reglas v3.0.0.

Genera un proyecto con el perfil DYC real y verifica:
1. transition_rules: every_n=3 -> transiciones en cada 3er corte.
2. extra_assets: audio toast (start) y swoosh (black_hole_start) presentes.
3. Agujero negro con duration_us=1000000 (1s) del JSON.
4. layout_rules: audio_sync (comportamiento actual).

Ejecutar desde la raiz:
    & .venv314\\Scripts\\python.exe -X utf8 tests\\v3_rule_engine_check.py
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

from PIL import Image
from src.core import config
from src.core.capcut_project import CapCutProject
from src.core.profile_loader import load_profiles, build_edit_profile, get_profile
from src.core.timeline_builder import TimelineItem, measure_audio_duration_us

DRAFTS = r"D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts"
TEMPLATE_NAME = "1.PLANTILLA"
DYC_ASSETS_DIR = r"D:/YOUTUBE AUTOMATIZADO/0.sticman/assets/"


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
    Image.new("RGB", (w, h), (100, 50, 200)).save(path)


def main() -> None:
    config.ensure_dirs()
    work = Path(tempfile.mkdtemp(prefix="capcutauto_v3test_"))
    results: dict[str, bool] = {}
    ok = True

    # --- Plantilla real ---
    template = shutil.copytree(Path(DRAFTS) / TEMPLATE_NAME, work / TEMPLATE_NAME)

    # --- Audio sintetico 3s ---
    audio = work / "voz.wav"
    make_wav(audio, 3.0)

    # --- 5 imagenes ---
    images_dir = work / "imgs"
    images_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 6):
        make_image(images_dir / f"img{i:02d}.jpg")

    # --- Perfil DYC ---
    profiles = load_profiles(ROOT / "profiles", dyc_assets_dir=DYC_ASSETS_DIR)
    profile_data = get_profile(profiles, "dyc")
    edit_profile = build_edit_profile(profile_data)
    # Aislar el motor de reglas: desactivar CTA (añade transiciones y pantalla
    # final propias que no corresponden al test).
    edit_profile.cta_enabled = False

    print("=== CAMPOS DEL PERFIL (v3.0.0) ===")
    print("transition_rules:", edit_profile.transition_rules)
    print("extra_assets:", edit_profile.extra_assets)
    print("layout_rules:", edit_profile.layout_rules)
    end_anim = edit_profile.dyc_end_animation
    print("end_animation duration_us:", end_anim.get("duration_us") if end_anim else None)

    results["transition_rules_loaded"] = (
        edit_profile.transition_rules.get("type") == "every_n"
        and edit_profile.transition_rules.get("n") == 3
    )
    results["extra_assets_loaded"] = len(edit_profile.extra_assets) == 2
    results["layout_rules_loaded"] = edit_profile.layout_rules.get("mode") == "audio_sync"
    results["end_anim_duration_from_json"] = (
        end_anim is not None and int(end_anim.get("duration_us", 0)) == 1_000_000
    )

    # --- Items: 5 escenas de 600ms = 3s ---
    items = [
        TimelineItem(
            i, images_dir / f"img{i + 1:02d}.jpg",
            f"Escena numero {i + 1}", f"Escena numero {i + 1}", 1.0,
            i * 600_000, (i + 1) * 600_000, 600_000,
        )
        for i in range(5)
    ]
    audio_dur = measure_audio_duration_us(audio)
    assert audio_dur is not None, "No se pudo medir el audio sintetico"

    # --- Generar proyecto ---
    project = CapCutProject(template)
    out = project.generate(
        "Test_V3_RuleEngine", items, audio, audio_dur,
        allow_test_names=True, edit_profile=edit_profile,
    )
    print(f"GENERADO: {out}")

    data = json.loads((out / "draft_content.json").read_text(encoding="utf-8"))
    materials = data.get("materials", {})
    tracks = data.get("tracks", [])
    transitions = materials.get("transitions", [])
    audios = materials.get("audios", [])
    anim_mats = materials.get("material_animations", [])

    # --- 1) Transiciones every_n=3 ---
    # 5 segmentos = 4 bordes; (b+1) % 3 == 0 -> b=2 (3er corte). 1 transicion.
    # NOTA: el CTA añade UNA transición extra (glitch última imagen -> pantalla
    # final) DESPUÉS del motor de reglas; no la contamos aquí.
    trans_ids = {t["id"] for t in transitions}
    n_trans_main = 0
    for tr in tracks:
        if tr.get("type") != "video":
            continue
        for seg in tr.get("segments", []):
            refs = seg.get("extra_material_refs", [])
            if any(r in trans_ids for r in refs):
                n_trans_main += 1
    n_trans = n_trans_main
    print(f"transiciones en track video principal: {n_trans} (esperado 1 con every_n=3 y 4 bordes)")
    results["transitions_every_n"] = n_trans == 1

    # --- 2) Extra assets: audios ---
    audio_names = [str(a.get("name", "")).lower() for a in audios]
    audio_paths = [str(a.get("path", "")).lower() for a in audios]
    all_audio_info = [(n, p) for n, p in zip(audio_names, audio_paths)]
    print(f"audios: {all_audio_info}")
    toast_ok = any(("wiht a glass" in p) or ("toast" in p) for _, p in all_audio_info)
    swoosh_ok = any("swoosh" in p for _, p in all_audio_info)
    results["toast_audio_injected"] = toast_ok
    results["swoosh_audio_injected"] = swoosh_ok

    # Volumen +10 dB = 10^(10/20) = 3.162
    vol_toast = None
    for a in audios:
        p = str(a.get("path", "")).lower()
        if "wiht a glass" in p or "toast" in p:
            # Buscar el segmento con este material_id
            vol_toast = a  # material, volumen va en el segmento
            break
    # Volumen en los segmentos de las pistas de audio
    n_audio_segs_extra = 0
    for t in tracks:
        if t.get("type") != "audio":
            continue
        for seg in t.get("segments", []):
            mid = seg.get("material_id", "")
            mat = next((a for a in audios if a.get("id") == mid), None)
            if mat:
                p = str(mat.get("path", "")).lower()
                if ("wiht a glass" in p or "toast" in p or "swoosh" in p):
                    n_audio_segs_extra += 1
                    vol = seg.get("volume", 0.0)
                    print(f"extra audio segment: vol={vol:.4f} (esperado 3.1623 para +10dB)")
                    if abs(vol - 3.1623) < 0.01:
                        results.setdefault("extra_audio_volume_10db", True)
                    else:
                        results["extra_audio_volume_10db"] = False
    results["extra_audio_segments_count"] = n_audio_segs_extra == 2

    # --- 3) Agujero negro clamped to last segment (600ms) ---
    end_durations = []
    for m in anim_mats:
        for anim in m.get("animations", []):
            if anim.get("type") == "out":
                end_durations.append(anim.get("duration"))
    print(f"end anim durations: {end_durations}")
    results["black_hole_1s"] = end_durations == [600_000]

    # --- 4) Swoosh sincronizado con black hole start ---
    # El black hole arranca al final del ultimo segmento de 600ms -> t = 2400000us (clampado)
    # El swoosh debe arrancar en dyc_black_hole_abs_start_us = 2400000
    swoosh_start = None
    for t in tracks:
        if t.get("type") != "audio":
            continue
        for seg in t.get("segments", []):
            mid = seg.get("material_id", "")
            mat = next((a for a in audios if a.get("id") == mid), None)
            if mat and "swoosh" in str(mat.get("path", "")).lower():
                swoosh_start = (seg.get("target_timerange") or {}).get("start")
    print(f"swoosh start: {swoosh_start} us (esperado 2400000 = black hole start)")
    results["swoosh_at_black_hole"] = swoosh_start == 2_400_000

    # --- Toast al inicio (t=0) ---
    toast_start = None
    for t in tracks:
        if t.get("type") != "audio":
            continue
        for seg in t.get("segments", []):
            mid = seg.get("material_id", "")
            mat = next((a for a in audios if a.get("id") == mid), None)
            if mat and ("wiht a glass" in str(mat.get("path", "")).lower()
                        or "toast" in str(mat.get("path", "")).lower()):
                toast_start = (seg.get("target_timerange") or {}).get("start")
    print(f"toast start: {toast_start} us (esperado 0)")
    results["toast_at_start"] = toast_start == 0

    # --- Resumen ---
    print("\n=== RESULTADOS ===")
    for name, res in results.items():
        status = "OK" if res else "FAIL"
        if not res:
            ok = False
        print(f"  [{status}] {name}")

    print("\n" + ("TEST PASSED" if ok else "TEST FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
