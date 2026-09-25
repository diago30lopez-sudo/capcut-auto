"""Check de LAYOUT INTERNO de los subtitulos (texto pegado abajo en su caja).

Sintoma que corrige: los subtitulos estan bien personalizados en el eje Y, pero
DENTRO de su propia caja el texto se ve pegado al borde inferior, con un hueco
vacio grande ARRIBA. Es decir: la caja es mas alta que los glifos.

CAUSA RAIZ (verificada contra el draft real de referencia de CapCut,
"Nexus Paradoja video 10100", 740 materiales de texto): los `range` de
`content.styles[]` NO cubrian el texto entero. El codigo saltaba el espacio
entre palabras (`cursor = end + 1`), asi que los espacios se quedaban SIN
estilo y CapCut los componia con su estilo POR DEFECTO: la caja se calculaba
con una altura mayor que la de los glifos y el texto se dibujaba pegado abajo.
En el draft real los 740/740 materiales tienen cobertura CONTIGUA de [0, len)
(incluidos los espacios). Este test es el que bloquea la regresion.

Verifica los 5 fixes:
  Fix 1  material.font_size == content.styles[].size (mismo float). OJO: en el
         content la clave se llama `size`, que es como la llama CapCut (no
         `font_size`, que no existe en su esquema).
  Fix 2  content.styles[].align_type == 1 y vertical_align == 1.
  Fix 3  line_spacing == 0.0 en el content y en el material.
  Fix 4  el texto no contiene \\n, \\r, \\t ni espacios no-ASCII, y entre
         palabras hay EXACTAMENTE un espacio ASCII.
  Fix 5  campos de caja del material: fixed_height/fixed_width/inner_padding
         = -1.0 (auto), typesetting 0, line_feed 1, alignment 1,
         preset_has_set_alignment False.
  Extra  la posicion Y NO se toca: clip.transform.y == config.SUBTITLE_POS_Y_JSON.

Ejecutar desde la raiz:
    & .venv\\Scripts\\python.exe -X utf8 tests\\subtitle_layout_check.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.core import subtitles as S  # noqa: E402

# 3 cues -> 3 subtitulos (2-5 palabras = un fragmento por cue). El segundo lleva
# espacios Unicode (\u2003, \u00A0) y el tercero un zero-width + BOM: ambos
# tienen que llegar limpios al content.
SRT_3 = (
    "1\n00:00:00,100 --> 00:00:01,500\nEl héroe es invencible\n\n"
    "2\n00:00:01,600 --> 00:00:03,000\nA\u2003B\u00A0  C D E\n\n"
    "3\n00:00:03,100 --> 00:00:04,500\nZ\u200bZ\ufeff con BOM\n\n"
)

# Espacios no-ASCII prohibidos dentro del texto final (Fix 4).
NON_ASCII_SPACES = "\u00a0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000"
FORBIDDEN_IN_TEXT = ("\n", "\r", "\t")


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def check_material(mat: dict) -> list[str]:
    """Devuelve la lista de checks fallidos de un material de subtitulo."""
    bad: list[str] = []
    content = json.loads(mat["content"])
    text = content["text"]
    styles = content["styles"]
    n = utf16_len(text)

    # --- Fix 4: texto limpio -------------------------------------------------
    for ch in FORBIDDEN_IN_TEXT:
        if ch in text:
            bad.append(f"texto contiene {ch!r}: {text!r}")
    for ch in NON_ASCII_SPACES:
        if ch in text:
            bad.append(f"texto contiene espacio no-ASCII U+{ord(ch):04X}: {text!r}")
    if any(ord(c) in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD) for c in text):
        bad.append(f"texto contiene caracteres invisibles: {text!r}")
    if text != " ".join(text.split()):
        bad.append(f"espaciado no normalizado (se espera 1 espacio ASCII): {text!r}")
    if text != text.strip():
        bad.append(f"texto sin strip(): {text!r}")

    # --- cobertura contigua (CAUSA RAIZ) -------------------------------------
    if not styles:
        bad.append("content sin estilos")
        return bad
    ranges = [tuple(st["range"]) for st in styles]
    if ranges[0][0] != 0:
        bad.append(f"el primer run no empieza en 0: {ranges[0]}")
    if ranges[-1][1] != n:
        bad.append(f"el ultimo run no acaba en len({n}): {ranges[-1]}")
    for i in range(len(ranges) - 1):
        if ranges[i][1] != ranges[i + 1][0]:
            bad.append(
                f"HUECO de cobertura entre {ranges[i]} y {ranges[i + 1]}: "
                "los caracteres sin estilo se componen con el estilo por "
                "defecto y la caja crece (texto pegado abajo)")
    for st in styles:
        a, b = st["range"]
        chunk = text.encode("utf-16-le")[a * 2:b * 2].decode("utf-16-le")
        if not (chunk.strip() == "" or " " not in chunk):
            bad.append(f"run {st['range']} mezcla palabra y espacio: {chunk!r}")

    for st in styles:
        # --- Fix 1: mismo tamano de fuente en material y content --------------
        if st["size"] != mat["font_size"]:
            bad.append(f"Fix 1: styles.size={st['size']!r} != material.font_size={mat['font_size']!r}")
        if type(st["size"]) is not type(mat["font_size"]):
            bad.append(f"Fix 1: tipo distinto {type(st['size']).__name__} vs {type(mat['font_size']).__name__}")
        if st["size"] != float(S.FONT_SIZE):
            bad.append(f"Fix 1: size != FONT_SIZE ({S.FONT_SIZE})")
        # --- Fix 2: alineacion explicita --------------------------------------
        if st.get("vertical_align") != 1:
            bad.append(f"Fix 2: vertical_align={st.get('vertical_align')!r} (debe ser 1)")
        if st.get("align_type") != 1:
            bad.append(f"Fix 2: align_type={st.get('align_type')!r} (debe ser 1)")
        # --- Fix 3: line_spacing a cero ---------------------------------------
        if st.get("line_spacing") != 0.0:
            bad.append(f"Fix 3: styles.line_spacing={st.get('line_spacing')!r} (debe ser 0.0)")

    # --- Fix 3 (material) y Fix 5: caja sin padding, centrada ---------------
    if mat["line_spacing"] != 0.0:
        bad.append(f"Fix 3: material.line_spacing={mat['line_spacing']!r} (debe ser 0.0)")
    for key in ("fixed_height", "fixed_width", "inner_padding"):
        if mat.get(key) != -1.0 or type(mat.get(key)) is not float:
            bad.append(f"Fix 5: {key}={mat.get(key)!r} (debe ser -1.0 float)")
    if mat.get("typesetting") != 0:
        bad.append(f"Fix 5: typesetting={mat.get('typesetting')!r} (debe ser 0)")
    if mat.get("line_feed") != 1:
        bad.append(f"Fix 5: line_feed={mat.get('line_feed')!r} (debe ser 1)")
    if mat.get("alignment") != 1:
        bad.append(f"Fix 5: alignment={mat.get('alignment')!r} (debe ser 1)")
    if mat.get("preset_has_set_alignment") is not False:
        bad.append(f"Fix 5: preset_has_set_alignment={mat.get('preset_has_set_alignment')!r} (debe ser False)")
    return bad


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="capcutauto_layout_"))
    srt = work / "tres_subtitulos.srt"
    srt.write_text(SRT_3, encoding="utf-8")

    track, materials, segments = S.build_subtitle_track(srt)
    checks: dict[str, bool] = {}

    # --- 3 subtitulos -------------------------------------------------------
    checks["3 subtitulos generados (3 materiales + 3 segmentos)"] = (
        track is not None and len(materials) == 3 and len(segments) == 3
        and len(track["segments"]) == 3)

    # --- la causa raiz: cobertura de estilos en TODOS los materiales --------
    failures: list[str] = []
    for mat in materials:
        failures += [f"[{json.loads(mat['content'])['text']!r}] {b}"
                     for b in check_material(mat)]
    checks["Fix 1-5 + cobertura contigua en los 3 subtitulos"] = not failures

    # --- el texto sucio del SRT llega limpio (Fix 4) -----------------------
    texts = [json.loads(m["content"])["text"] for m in materials]
    checks["Fix 4: \\u2003 y \\u00A0 normalizados a espacio ASCII"] = texts[1] == "A B C D E"
    checks["Fix 4: zero-width y BOM eliminados"] = texts[2] == "ZZ CON BOM"

    # --- sincronizacion intacta (no se ha tocado) --------------------------
    last = segments[-1]["target_timerange"]
    checks["sincronizacion intacta: ultimo cue acaba a 4.5 s"] = (
        last["start"] + last["duration"] == 4_500_000)
    checks["sincronizacion intacta: primer subtitulo empieza a 0.1 s"] = (
        segments[0]["target_timerange"]["start"] == 100_000)

    # --- la posicion Y NO se toca ------------------------------------------
    ys = {seg["clip"]["transform"]["y"] for seg in segments}
    checks[f"posicion Y intacta ({config.SUBTITLE_POS_Y_JSON})"] = (
        ys == {float(config.SUBTITLE_POS_Y_JSON)})

    # --- Fix 2/3 tambien en el content construido a mano -------------------
    st0 = json.loads(S.build_text_content("PRUEBA DE TEXTO", "", float(S.FONT_SIZE)))["styles"][0]
    checks["Fix 2: align_type=1 y vertical_align=1 en styles[0]"] = (
        st0["align_type"] == 1 and st0["vertical_align"] == 1)
    checks["Fix 3: line_spacing=0.0 en styles[0]"] = st0["line_spacing"] == 0.0
    checks["Fix 1: styles[0].size == material.font_size"] = (
        st0["size"] == float(S.FONT_SIZE)
        and S.build_text_material("PRUEBA DE TEXTO")["font_size"] == float(S.FONT_SIZE))

    ok = True
    for name, passed in checks.items():
        print(("  ok  " if passed else "  FAIL ") + name)
        ok = ok and passed
    for f in failures:
        print("    -> " + f)

    # --- fragmento de JSON para inspeccion manual ---------------------------
    mat = materials[1]
    content = json.loads(mat["content"])
    print()
    print("  --- material (subtitulo) ---")
    print("  " + json.dumps({k: mat[k] for k in (
        "font_size", "text_size", "letter_spacing", "line_spacing", "alignment",
        "line_feed", "typesetting", "fixed_width", "fixed_height",
        "inner_padding", "preset_has_set_alignment", "border_mode",
        "border_width")}, ensure_ascii=False))
    print("  --- content.styles (ranges = offsets UTF-16) ---")
    for st in content["styles"]:
        a, b = st["range"]
        chunk = content["text"].encode("utf-16-le")[a * 2:b * 2].decode("utf-16-le")
        print(f"  {st['range']} {chunk!r:12} size={st['size']} "
              f"v_align={st['vertical_align']} align={st['align_type']} "
              f"line_spacing={st['line_spacing']} "
              f"color={st['fill']['content']['solid']['color']}")
    print(f"  text={content['text']!r} (utf16 len={utf16_len(content['text'])}, "
          f"cobertura 0..{content['styles'][-1]['range'][1]})")
    print(f"  clip.transform = {segments[1]['clip']['transform']}")

    if not ok:
        print("SUBTITLE_LAYOUT_FAIL")
        sys.exit(1)
    print("SUBTITLE_LAYOUT_OK")


if __name__ == "__main__":
    main()
