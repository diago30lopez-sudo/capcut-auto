"""json_scales_check.py — VALIDA los valores JSON EXACTOS de la escala
JSON <-> CapCut UI (confirmada empiricamente; docs/capcut_json_scales.md).

Canvas del proyecto: 1920x1080 (CapCut multiplica transform por el canvas
COMPLETO, no por su mitad). Escalas CONFIRMADAS empiricamente (v1.3.0-dev, contra
el draft real del usuario y mediciones en CapCut):
  - strokes[0].width / border_width = UI / 500  (UI 30    -> 0.06)
  - global_alpha (opacidad)           = UI / 100   (15%      -> 0.15)
    (text_alpha=1.0 fijo; CapCut usa global_alpha como control principal)
  - letter_spacing                  = UI * 0.05  (UI 2     -> 0.10)
  - transform.x (watermark)         = UI_X / 1920 (UI -1098 -> -0.571875)
  - transform.y (watermark)         = UI_Y / 1080 (UI 896   -> 0.8296296
  - transform.y (subtitulos)        = UI_Y / 1080 (UI -900  -> -0.8333333

No genera proyectos ni abre CapCut: usa los builders directamente y comprueba
que el JSON que se escribira en draft_content.json lleva EXACTAMENTE esos
valores.

Ejecutar desde la raiz:
    & .venv\\Scripts\\python.exe -X utf8 tests\\json_scales_check.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import config  # noqa: E402
from src.core.subtitles import (  # noqa: E402
    build_subtitle_track,
    build_watermark_material_and_track,
    clean_srt_text,
)

SRT_TEST = (
    "1\n00:00:00,100 --> 00:00:01,500\n¿Qué pasaría si el ataque final llega\n\n"
)

CANVAS_W = config.CANVAS_WIDTH   # 1920
CANVAS_H = config.CANVAS_HEIGHT  # 1080


def main() -> None:
    checks: dict[str, bool] = {}
    ok = True

    # --- 1) Constantes de escalas en config --------------------------------
    checks["trazo UI 30 -> JSON 0.06 (UI /500)"] = (
        abs(config.SUBTITLE_STROKE_WIDTH_JSON - 0.06) < 1e-6)
    checks["opacidad 15% -> global_alpha 0.15 (UI /100)"] = (
        config.WATERMARK_ALPHA_JSON == 0.15)
    checks["letter spacing UI 2 -> JSON 0.10 (UI x0.05)"] = (
        config.WATERMARK_LETTER_SPACING_JSON == 0.10)
    checks["watermark X UI -1098 -> JSON -0.571875 (-1098/1920)"] = (
        abs(config.WATERMARK_POS_X_JSON - (-1098 / CANVAS_W)) < 1e-9)
    checks["watermark Y UI 896 -> JSON 0.8296296 (896/1080)"] = (
        abs(config.WATERMARK_POS_Y_JSON - (896 / CANVAS_H)) < 1e-9)
    checks["subtitulos Y UI -900 -> JSON -0.8333333 (-900/1080)"] = (
        abs(config.SUBTITLE_POS_Y_JSON - (-900 / CANVAS_H)) < 1e-9)
    checks["watermark font size 8.0"] = config.WATERMARK_FONT_SIZE == 8.0
    checks["watermark bold+italic"] = (
        config.WATERMARK_BOLD is True and config.WATERMARK_ITALIC is True)

    # --- 2) SUBTITULOS: JSON exacto -----------------------------------------
    with tempfile.TemporaryDirectory(prefix="json_scales_subs_") as td:
        srt = Path(td) / "subs.srt"
        srt.write_text(SRT_TEST, encoding="utf-8")
        track, materials, segments = build_subtitle_track(srt)

    checks["subtitulos: 1 material generado"] = len(materials) >= 1
    mat = materials[0]
    sub_content = json.loads(mat["content"])
    checks["subtitulos: un solo espacio ASCII entre palabras"] = (
        sub_content["text"] == " ".join(sub_content["text"].split())
        and "  " not in sub_content["text"])
    checks["subtitulos: texto en MAYUSCULAS"] = (
        sub_content["text"] == sub_content["text"].upper())
    styles = sub_content["styles"]
    stroke = styles[0]["strokes"][0]
    checks["subtitulos: strokes[0].enable = true"] = stroke["enable"] is True
    checks["subtitulos: strokes[0].width = 0.06"] = (
        abs(stroke["width"] - 0.06) < 1e-6)
    checks["subtitulos: strokes[0].color negro puro"] = (
        stroke["content"]["solid"]["color"] == [0.0, 0.0, 0.0])
    checks["subtitulos: mat.border_width = 0.06 / border_mode = 1"] = (
        abs(mat["border_width"] - 0.06) < 1e-6 and mat["border_mode"] == 1)
    checks["subtitulos: letter_spacing = 0.0 (UI 0)"] = (
        mat["letter_spacing"] == 0.0)
    seg = segments[0]
    checks["subtitulos: clip.transform.y = -0.8333333 (UI -900)"] = (
        seg["clip"]["transform"]["y"] == config.SUBTITLE_POS_Y_JSON
        and abs(seg["clip"]["transform"]["y"] - (-900 / CANVAS_H)) < 1e-6)
    checks["subtitulos: clip.transform.x = 0.0 (centrado)"] = (
        seg["clip"]["transform"]["x"] == 0.0)

    # --- 3) WATERMARK: JSON exacto ------------------------------------------
    wm_mat, wm_track = build_watermark_material_and_track(
        "NEXUS PARADOJA", 3, 1_234_567)
    wm_content = json.loads(wm_mat["content"])
    wm_style = wm_content["styles"][0]
    checks["watermark: content una sola linea"] = (
        wm_content["text"] == "NEXUS PARADOJA")
    checks["watermark: misma fuente que subtitulos"] = (
        wm_style["font"]["path"] == wm_mat["font_path"]
        and wm_mat["font_path"] == mat["font_path"])
    checks["watermark: estilo unico [0, len)"] = (
        len(wm_content["styles"]) == 1
        and wm_style["range"] == [0, len("NEXUS PARADOJA")])
    checks["watermark: content size 8.0 / bold / italic"] = (
        wm_style["size"] == 8.0 and wm_style["bold"] is True
        and wm_style["italic"] is True)
    checks["watermark: content fill.alpha = 1.0"] = (
        wm_style.get("fill", {}).get("alpha") == 1.0)
    checks["watermark: mat.font_size = 8.0"] = wm_mat["font_size"] == 8.0
    checks["watermark: global_alpha = 0.15 (15%)"] = (
        wm_mat["global_alpha"] == 0.15)
    checks["watermark: text_alpha = 1.0 (fijo)"] = (
        wm_mat["text_alpha"] == 1.0)
    checks["watermark: letter_spacing = 0.10 (UI 2)"] = (
        wm_mat["letter_spacing"] == 0.10)
    wm_seg = wm_track["segments"][0]
    checks["watermark: clip.transform.x = -0.571875 (UI -1098)"] = (
        abs(wm_seg["clip"]["transform"]["x"] - (-1098 / CANVAS_W)) < 1e-9)
    checks["watermark: clip.transform.y = 0.8296296 (UI 896)"] = (
        abs(wm_seg["clip"]["transform"]["y"] - (896 / CANVAS_H)) < 1e-9)
    checks["watermark: duracion start=0, dur=audio_duration_us"] = (
        wm_seg["target_timerange"] == {"start": 0, "duration": 1_234_567})
    checks["watermark: pista text propia (1 segmento)"] = (
        wm_track["type"] == "text" and len(wm_track["segments"]) == 1)

    # --- 4) Normalizacion de espacios (sin huecos) ---------------------------
    for raw in ("¿Qué   pasaría  si", "A\u2003B\u00A0 C\tD\nE"):
        normal = clean_srt_text(raw)
        checks[f"espacios normalizados: {raw!r}"] = (
            "  " not in normal and all(c in " " or ord(c) >= 0x20 for c in normal))

    for k, v in checks.items():
        print(("  ok  " if v else "  FAIL ") + k)
        ok = ok and v

    print()
    print("=== FRAGMENTO JSON SUBTITULO (valores calibrados) ===")
    print(json.dumps({
        "material": {
            "border_width": mat["border_width"],
            "border_mode": mat["border_mode"],
            "border_color": mat["border_color"],
            "letter_spacing": mat["letter_spacing"],
        },
        "content.styles[0].strokes[0]": stroke,
        "clip.transform": seg["clip"]["transform"],
    }, ensure_ascii=False, indent=2))
    print()
    print("=== FRAGMENTO JSON WATERMARK (valores exactos) ===")
    print(json.dumps({
        "content": wm_content,
        "material": {
            "global_alpha": wm_mat["global_alpha"],
            "text_alpha": wm_mat["text_alpha"],
            "letter_spacing": wm_mat["letter_spacing"],
            "font_size": wm_mat["font_size"],
        },
        "clip.transform": wm_seg["clip"]["transform"],
        "target_timerange": wm_seg["target_timerange"],
    }, ensure_ascii=False, indent=2))
    print()

    if not ok:
        print("JSON_SCALES_FAIL")
        sys.exit(1)
    print("JSON_SCALES_OK")


if __name__ == "__main__":
    main()