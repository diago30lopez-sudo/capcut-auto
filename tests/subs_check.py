"""Verifica el modulo de subtitulos (TAREA 2): fragmentacion 2-5 palabras,
timing proporcional, estilo del content (blanco/amarillo), trazo, sombra,
pop-up de escala y que el JSON completo con la pista text se serializa."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import config
from src.core.capcut_canonical import TEXT_MATERIAL, TEXT_SEGMENT
from src.core.subtitles import (
    BORDER_COLOR, BORDER_MODE, BORDER_WIDTH, FONT_SIZE, KEYWORD_COLOR,
    LETTER_SPACING, POPUP_RAMP_US, POPUP_START_SCALE, SHADOW_ALPHA, STROKE_MODE,
    STYLE_BOLD, STYLE_ITALIC, SUBTITLE_KEYWORDS, SUBTITLE_Y, build_subtitle_track,
    clean_srt_text, split_into_fragments,
)

SRT = Path(__file__).parent / "data" / "subs_test.srt"


def main() -> None:
    assert SRT.is_file(), f"falta {SRT}"

    # 1) limpieza de tags HTML
    assert clean_srt_text("<i>El héroe es invencible</i>") == "El héroe es invencible"

    # 1b) REGLA DE ORO espaciado: exactamente un espacio ASCII entre palabras
    #     (prohibidos \u2003, \u00A0, \t, \n o multiples espacios).
    for raw in ("¿Qué   pasaría\t si", "A\u2003B\u00A0 C", "X\n\nY"):
        normal = clean_srt_text(raw)
        assert "  " not in normal and "\t" not in normal and "\n" not in normal, raw
        assert all(c in " " or ord(c) >= 0x20 for c in normal), raw

    # 2) frag2mentos de 2-5 palabras (nunca 1 ni >5)
    for text in ("Un poder mucho más grande de lo que imaginan",
                 "El ataque final destruyó la bomba",
                 "Memoria eterna"):
        frags = split_into_fragments(text)
        assert frags, text
        total = [w for f in frags for w in f]
        assert " ".join(total) == text, (frags, text)
        for f in frags:
            assert 2 <= len(f) <= 5, (f, text)

    # 3) timing proporcional: la suma = duracion total del cue
    track, materials, segments = build_subtitle_track(SRT)

    n_frag = sum(len(split_into_fragments(clean_srt_text(c[2]))) for c in _cues())
    assert len(materials) == len(segments) == n_frag, (len(materials), len(segments), n_frag)

    # ultimo fragmento del ultimo cue llega al final exacto (11.3 s)
    last = segments[-1]["target_timerange"]
    assert last["start"] + last["duration"] == 11_300_000, last

    # primer segmento empieza en 0
    assert segments[0]["target_timerange"]["start"] == 0

    # cada cue con >5 palabras debe partirse en >=2 fragmentos
    long_cue = [m for m in materials if "PODER" in m["content"]]
    assert long_cue, "no se encontro la cue larga"

    # 4) estilo del material
    mat = materials[0]
    for k in TEXT_MATERIAL:
        assert k in mat, f"material.texts pierde campo {k}"
    content = json.loads(mat["content"])
    assert content["text"] == "EL HÉROE ES INVENCIBLE", content["text"]
    # espaciado: el content usa exactamente un espacio ASCII entre palabras
    assert "  " not in content["text"]
    assert content["text"] == " ".join(content["text"].split())
    assert content["text"] == content["text"].upper(), "Texto debe estar en MAYÚSCULAS"
    assert content["styles"], "sin estilos"
    for st in content["styles"]:
        assert st["range"][1] > st["range"][0]
        color = st["fill"]["content"]["solid"]["color"]
        assert color in ([1.0, 1.0, 1.0], KEYWORD_COLOR), color
        assert st["size"] == FONT_SIZE, st["size"]        # tamano exacto 12
        assert st["bold"] is STYLE_BOLD, st["bold"]       # negrita
        assert st["italic"] is STYLE_ITALIC, st["italic"] # italica
        # trazo ACTIVADO en cada estilo del content (lo que renderiza CapCut)
        assert st["strokes"] and st["strokes"][0]["width"] == BORDER_WIDTH, st
        assert abs(st["strokes"][0]["width"] - 0.06) < 1e-6, st              # UI "30" /500
        assert st["strokes"][0]["enable"] is True, st              # trazo ACTIVADO
        assert st["strokes"][0]["mode"] == STROKE_MODE, st
        assert st["strokes"][0]["content"]["solid"]["color"] == [0.0, 0.0, 0.0], st
    assert mat["font_size"] == FONT_SIZE, mat["font_size"]
    assert mat["letter_spacing"] == LETTER_SPACING == 0.0, mat["letter_spacing"]
    assert mat["border_width"] == BORDER_WIDTH, mat["border_width"]  # UI "30"
    assert abs(mat["border_width"] - 0.06) < 1e-6, mat["border_width"]  # UI "30" /500
    assert mat["border_alpha"] == 1.0
    assert mat["border_color"] == BORDER_COLOR
    assert mat["border_mode"] == BORDER_MODE   # casilla "Trazo" ACTIVADA
    assert mat["has_shadow"] is True
    assert mat["shadow_alpha"] == SHADOW_ALPHA
    assert mat["shadow_smoothing"] == 0.2
    assert mat["shadow_distance"] == 15.0
    assert mat["text_color"] == "#FFFFFF"

    # palabra clave debe estar en amarillo (fragmentos de la cue con 'ATAQUE')
    kw_mats = []
    for m in materials:
        c = json.loads(m["content"])
        words = c["text"].split()  # ya en mayusculas
        if any(w.strip("¿?¡!,.;:()") == "ATAQUE" for w in words):
            kw_mats.append(c)
    assert kw_mats, "keyword 'ATAQUE' no presente"
    assert any(
        s["fill"]["content"]["solid"]["color"] == KEYWORD_COLOR
        for c in kw_mats for s in c["styles"]
    )

    # 5) segmento de texto: pop-up de entrada + posicion Y CONSTANTE -0.8333333
    #    (escala confirmada empiricamente JSON = UI_Y/1080 = -900/1080) y
    #    ESTATICO tras la entrada (escala 1.0 = sin zoom continuo durante toda
    #    la duracion).
    seg = segments[0]
    for k in TEXT_SEGMENT:
        assert k in seg, f"segment.text pierde campo {k}"
    assert SUBTITLE_Y == config.SUBTITLE_POS_Y_JSON, (SUBTITLE_Y, config.SUBTITLE_POS_Y_JSON)
    assert abs(seg["clip"]["transform"]["y"] - SUBTITLE_Y) < 1e-9, seg["clip"]["transform"]
    assert seg["clip"]["scale"]["x"] == 1.0 and seg["clip"]["scale"]["y"] == 1.0
    kfs = {kf["property_type"]: kf["keyframe_list"] for kf in seg["common_keyframes"]}
    assert "KFTypeScaleX" in kfs and "KFTypeScaleY" in kfs
    first = kfs["KFTypeScaleX"][0]
    second = kfs["KFTypeScaleX"][1]
    assert first["time_offset"] == 0 and first["values"] == [POPUP_START_SCALE]
    assert second["time_offset"] == POPUP_RAMP_US and second["values"] == [1.0]
    assert len(kfs["KFTypeScaleX"]) == 2, "solo entrada pop-up (sin zoom continuo)"

    # 6) el track completo es serializable (JSON valido para CapCut)
    for o in (track, materials, segments):
        json.dumps(o, ensure_ascii=False)

    print("SUBTITLES OK ·",
          f"{len(materials)} fragmentos ·",
          f"popup {POPUP_START_SCALE}->1.0 en {POPUP_RAMP_US/1000:.0f} ms ·",
          f"keywords={len(SUBTITLE_KEYWORDS)}")


def _cues():
    # reutiliza parse_srt del modulo (consume el mismo archivo)
    from src.core.timeline_builder import parse_srt
    return parse_srt(SRT)


if __name__ == "__main__":
    main()