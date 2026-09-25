"""Check de la MARCA DE AGUA (watermark) "NEXUS PARADOJA".

Verifica en un proyecto real generado (plantilla real copiada a un directorio
temporal, sin tocar los drafts):

1) Material `text` con el texto exacto, tamano 8, negrita+italica, espaciado de
   caracteres '2' de la UI (= 0.10 en el JSON normalizado de CapCut) y opacidad
   15% via global_alpha=0.15 (text_alpha=1.0 fijo; CapCut usa global_alpha
   como control principal, segun draft real).
2) Segmento propio que cubre TODO el video: target_timerange [0, audio_dur).
3) Pista propia SEPARADA de la pista de subtitulos (dos pistas text distintas).
4) target_timerange del watermark en el mismo eje temporal que el audio.
5) Toggle config.WATERMARK_ENABLED = False -> no se agrega ni material ni pista.

Se reporta el mapeo de posicion (X=-1098, Y=896) -> JSON CONFIRMADO
   empiricamente x=-0.571875 (-1098/1920), y=0.8296296 (896/1080) en
   clip.transform, y la constatacion de que el watermark va en el EXTREMO
   superior-izquierdo, independiente de la fila de los subtitulos
   (Y=-0.8333333 = UI -900).

Ejecutar desde la raiz:
    & .venv\\Scripts\\python.exe -X utf8 tests\\watermark_check.py
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
)

DRAFTS = r"D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts"
TEMPLATE_NAME = "1.PLANTILLA"
PROJECT_NAME = "Watermark_Test"
WATERMARK_TEXT = "NEXUS PARADOJA"


def make_wav(path: Path, secs: float = 3.0) -> None:
    rate = 16000
    n = int(secs * rate)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(8000 * ((i % rate) / rate))) for i in range(n)))


def _generate(enable_watermark: bool) -> tuple[dict, int]:
    """Genera un proyecto real con subtitulos + watermark (o sin el, segun el
    toggle) y devuelve (draft_content, audio_duration_us)."""
    work = Path(tempfile.mkdtemp(prefix="capcutauto_wm_"))
    saved = config.WATERMARK_ENABLED
    try:
        config.WATERMARK_ENABLED = enable_watermark
        audio = work / "voz.wav"
        make_wav(audio)
        images = work / "imagenes"
        images.mkdir(parents=True, exist_ok=True)
        img = images / "escena01.jpg"
        Image.new("RGB", (800, 600), (200, 40, 40)).save(img)
        (work / "subs.srt").write_text(
            "1\n00:00:00,100 --> 00:00:01,500\nUn subtitulo de prueba\n\n"
            "2\n00:00:01,600 --> 00:00:03,000\nSegundo fragmento\n\n",
            encoding="utf-8")

        items = [TimelineItem(0, img, "frase", "frase", 1.0, 0, 3_000_000, 3_000_000)]
        audio_dur = measure_audio_duration_us(audio)
        assert audio_dur is not None

        project = CapCutProject(shutil.copytree(
            Path(DRAFTS) / TEMPLATE_NAME, work / TEMPLATE_NAME))
        out = project.generate(PROJECT_NAME, items, audio, audio_dur,
                               allow_test_names=True, subtitle_srt=work / "subs.srt")
        data = json.loads((out / "draft_content.json").read_text(encoding="utf-8"))
        return data, audio_dur
    finally:
        config.WATERMARK_ENABLED = saved


def text_of(mat: dict) -> str:
    return json.loads(mat["content"])["text"]


def main() -> None:
    config.ensure_dirs()
    checks: dict[str, bool] = {}
    ok = True

    data, audio_dur = _generate(enable_watermark=True)
    materials = (data.get("materials") or {}).get("texts") or []
    wm_mats = [m for m in materials if text_of(m) == WATERMARK_TEXT]
    checks["1 material watermark"] = len(wm_mats) == 1
    wm = wm_mats[0]

    content = json.loads(wm["content"]) if wm_mats else {}
    styles = content.get("styles") or []
    single = styles[0] if styles else {}
    checks["content: 1 estilo [0,len)"] = (
        len(styles) == 1
        and single.get("range") == [0, len(WATERMARK_TEXT)])
    checks["font_size 8 (UI 8)"] = (
        wm.get("font_size") == float(config.WATERMARK_FONT_SIZE)
        and single.get("size") == config.WATERMARK_FONT_SIZE)
    checks["negrita + italica activas"] = (
        wm_mats and single.get("bold") is config.WATERMARK_BOLD
        and single.get("italic") is config.WATERMARK_ITALIC)
    # UI '2' de espaciado = 0.10 JSON (escala confirmada: UI * 0.05).
    checks["espaciado chars '2' = 0.10 JSON"] = (
        wm_mats and abs(wm["letter_spacing"] - config.WATERMARK_LETTER_SPACING_JSON) < 1e-9)
    # Opacidad 15% = global_alpha 0.15, text_alpha 1.0 (CapCut usa global_alpha
    # como control principal; draft real: global_alpha=0.1005 -> ~10%).
    checks["opacidad 15% (global_alpha 0.15, text_alpha 1.0)"] = (
        wm_mats
        and abs(wm["global_alpha"] - config.WATERMARK_ALPHA_JSON) < 1e-9
        and wm["text_alpha"] == 1.0
        and (styles[0].get("fill") or {}).get("alpha") == 1.0)
    # Sin trazo ni sombra: defaults del canonico (desactivados).
    checks["sin trazo ni sombra"] = (
        wm_mats
        and wm.get("border_mode") == 0
        and wm.get("has_shadow") is False)

    # Segmento/pista del watermark (pista text cuya unica pieza apunta al wm).
    text_tracks = [t for t in data.get("tracks") or [] if t.get("type") == "text"]
    wm_track = next((t for t in text_tracks if any(
        s.get("material_id") == wm["id"] for s in t.get("segments") or [])),
        None) if wm_mats else None
    wm_seg = (wm_track.get("segments") or [{}])[0] if wm_track else {}
    checks["pista watermark separada de subtitulos"] = (
        len(text_tracks) == 2
        and wm_track is not None
        and all(t["id"] != wm_track["id"] for t in text_tracks if t is not wm_track)
        and len(wm_track["segments"]) == 1)
    checks["target cubre todo el audio [0, dur)"] = (
        wm_seg.get("target_timerange") == {"start": 0, "duration": audio_dur})
    checks["mismo eje temporal que el audio"] = (
        any(s.get("target_timerange", {}).get("duration") == audio_dur
            for t in data.get("tracks") or [] if t.get("type") == "audio"
            for s in t.get("segments") or []))

    # Posicion fija reportada (valores JSON CONFIRMADOS escritos directos).
    transform = wm_seg.get("clip", {}).get("transform", {})
    checks["pos X=-1098 -> x=-0.571875 (izquierda)"] = (
        abs(transform.get("x", 0) - config.WATERMARK_POS_X_JSON) < 1e-9
        and abs(config.WATERMARK_POS_X_JSON - (-1098 / 1920)) < 1e-9)
    checks["pos Y=896 -> y=0.8296296 (ARRIBA)"] = (
        abs(transform.get("y", 0) - config.WATERMARK_POS_Y_JSON) < 1e-9
        and abs(config.WATERMARK_POS_Y_JSON - (896 / 1080)) < 1e-9)

    # Toggle OFF: no debe aparecer ni material ni pista extra.
    data_off, _ = _generate(enable_watermark=False)
    off_mats = [m for m in (data_off.get("materials") or {}).get("texts") or []
                if text_of(m) == WATERMARK_TEXT]
    off_text_tracks = [t for t in data_off.get("tracks") or [] if t.get("type") == "text"]
    checks["toggle OFF: sin material watermark"] = not off_mats
    checks["toggle OFF: solo la pista de subtitulos"] = len(off_text_tracks) == 1

    for k, v in checks.items():
        print(("  ok  " if v else "  FAIL ") + k)
        ok = ok and v

    print()
    print(f"  posicion JSON (directo): x = {transform.get('x', 0)} "
          f"(=-1098/1920), y = {transform.get('y', 0)} (=896/1080)")
    print(f"  letter_spacing JSON = {wm.get('letter_spacing')} (UI '2' x0.05)")
    print(f"  global_alpha = {wm.get('global_alpha')} (15%), text_alpha = {wm.get('text_alpha')}")
    print("  -> watermark Y=896 (ARRIBA), X=-1098 (extremo izquierdo);"
          " subtitulos centrados en Y=-900 (abajo).")
    if not ok:
        print("WATERMARK_FAIL")
        sys.exit(1)
    print("WATERMARK_OK")


if __name__ == "__main__":
    main()