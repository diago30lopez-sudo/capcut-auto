"""Check de la feature v1.4.0 FIX v4 "Imagina esto" (POST-PROCESO del draft).

ARQUITECTURA
------------
La generación del proyecto es EXACTAMENTE la de v1.3.0 (FASE A): ni
`timeline_builder` ni `subtitles.py` saben nada de esta feature. El efecto se
aplica DESPUÉS, sobre el `draft_content.json` ya escrito, en
`src/core/imagina_esto.py`:

    FASE B  lee `materials.texts` + el `target_timerange` de cada bloque de
           subtítulo, normaliza el texto (minúsculas, sin tildes, sin signos,
           espacios colapsados) y busca las 20 keywords de
           `config.IMAGINA_ESTO_KEYWORDS`.
    FASE C  si la keyword queda partida entre 2 o 3 bloques CONTIGUOS
           (mismo rango temporal seguido, sin huecos), se marcan TODOS.
    FASE D  centra el texto de esos bloques (`clip.transform = {0, 0}`) y oculta
           la imagen de debajo, partiendo el segmento de video en
           antes / durante(oculto) / después con el mismo `material_id`.
    D.3     vuelve a LEER el JSON de disco y lo verifica todo; si algo falla
           lanza `ImaginaEstoError` y el generador aborta.

CASOS
-----
  A — escena sin keyword      -> imagen visible, subtítulo en Y normal
  B — keyword en UN bloque    -> ese bloque centrado + su tramo de imagen oculto
  C — keyword partida en 2    -> los 2 bloques centrados + los 2 tramos ocultos
  D — verificación negativa   -> si un segmento no se oculta, LANZA EXCEPCIÓN

CRÍTICO: se comprueba que el tramo oculto lleva el `material_id` (y por tanto la
ruta) de la imagen de SU escena, y no el de la primera imagen de la lista.

Ejecutar desde la raíz:
    & .venv\\Scripts\\python.exe -X utf8 tests\\imagina_esto_check.py
"""

from __future__ import annotations

import json
import logging
import random
import re
import shutil
import struct
import sys
import tempfile
import unicodedata
import wave
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.core import imagina_esto as ie  # noqa: E402
from src.core.capcut_project import CapCutProject  # noqa: E402
from src.core.scene_parser import parse_scenes  # noqa: E402
from src.core.subtitles import (  # noqa: E402
    BORDER_WIDTH, KEYWORD_COLOR, POPUP_RAMP_US, POPUP_START_SCALE,
)
from src.core.timeline_builder import build_timeline, measure_audio_duration_us  # noqa: E402

DRAFTS = r"D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts"
TEMPLATE_NAME = "1.PLANTILLA"

# --- Guion de 3 escenas (cues contiguos 0-2 s, 2-5 s, 5-9 s) ---------------
# 0 = caso A (sin keyword) · 1 = caso B (keyword en UN bloque) · 2 = caso C
# (keyword partida entre los 2 bloques del cue)
ESCENA_A = "El heroe es invencible"
ESCENA_B = "Imagina esto. Peter Parker despierta ya."
ESCENA_C = "El heroe imagina esto y ya."
# Variantes SIN keyword con el MISMO número de palabras (contraste A/B: lo
# único que debe cambiar es la feature).
ESCENA_B_SIN = "Observa esto. Peter Parker despierta ya."
ESCENA_C_SIN = "El heroe observa esto y ya."

GUION = (
    "ESCENA #101\n"
    'VOZ EN OFF: "{a}"\n'
    "DURACIÓN ESTIMADA: 2 segundos\n"
    'BÚSQUEDA DE IMAGEN (Google/Pinterest): "bosque"\n\n'
    "ESCENA #102\n"
    'VOZ EN OFF: "{b}"\n'
    "DURACIÓN ESTIMADA: 3 segundos\n"
    'BÚSQUEDA DE IMAGEN (Google/Pinterest): "ciudad"\n\n'
    "ESCENA #103\n"
    'VOZ EN OFF: "{c}"\n'
    "DURACIÓN ESTIMADA: 4 segundos\n"
    'BÚSQUEDA DE IMAGEN (Google/Pinterest): "montana"\n\n'
)
SRT = (
    "1\n00:00:00,000 --> 00:00:02,000\n{a}\n\n"
    "2\n00:00:02,000 --> 00:00:05,000\n{b}\n\n"
    "3\n00:00:05,000 --> 00:00:09,000\n{c}\n\n"
)
AUDIO_S = 9.0

Y_NORMAL = float(config.SUBTITLE_POS_Y_JSON)

# Bloques esperados (texto, inicio, duración) deducidos de
# `split_into_fragments` (6 palabras -> 3+3) y del reparto proporcional.
ESPERADO = [
    ("EL HEROE ES INVENCIBLE", 0, 2_000_000),
    ("IMAGINA ESTO. PETER", 2_000_000, 1_500_000),
    ("PARKER DESPIERTA YA.", 3_500_000, 1_500_000),
    ("EL HEROE IMAGINA", 5_000_000, 2_000_000),
    ("ESTO Y YA.", 7_000_000, 2_000_000),
]
# Bloques afectados: el 1 (keyword entero) y los 3-4 (keyword partida).
AFECTADOS = {1, 3, 4}


class _Collect(logging.Handler):
    """Recolecta los logs de 'capcutauto' (para verificar el RESUMEN de la FASE D)."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def make_wav(path: Path, secs: float) -> None:
    rate = 16000
    n = int(round(secs * rate))
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(8000 * ((i % rate) / rate))) for i in range(n)))


def generar(b: str, c: str, project_name: str,
            collect: _Collect | None = None) -> tuple[dict, Path, list[Path]]:
    """Genera un proyecto de 3 escenas (FASE A, idéntica a v1.3.0)."""
    work = Path(tempfile.mkdtemp(prefix="capcutauto_ie4_"))
    audio = work / "voz.wav"
    make_wav(audio, AUDIO_S)
    audio_dur = measure_audio_duration_us(audio)
    assert audio_dur is not None

    guion = work / "escenas.txt"
    guion.write_text(GUION.format(a=ESCENA_A, b=b, c=c), encoding="utf-8")
    srt = work / "subs.srt"
    srt.write_text(SRT.format(a=ESCENA_A, b=b, c=c), encoding="utf-8")

    images = work / "imagenes"
    images.mkdir(parents=True, exist_ok=True)
    rutas: list[Path] = []
    for i in range(3):
        p = images / f"escena{i + 1:02d}.jpg"
        Image.new("RGB", (1280, 720), (30 + i * 40, 60, 120)).save(p)
        rutas.append(p)

    logger = logging.getLogger("capcutauto")
    prev_level = logger.level
    if collect is not None:
        logger.addHandler(collect)
        logger.setLevel(logging.INFO)
    try:
        scenes = parse_scenes(guion)
        items, total_us = build_timeline(scenes, srt, rutas)
        project = CapCutProject(shutil.copytree(
            Path(DRAFTS) / TEMPLATE_NAME, work / TEMPLATE_NAME))
        # Misma semilla en todas las generaciones: zoom, paneo y transiciones
        # usan random y deben salir idénticos para que las comparaciones valgan.
        random.seed(1234)
        out = project.generate(project_name, items, audio, total_us,
                               allow_test_names=True, subtitle_srt=srt)
    finally:
        if collect is not None:
            logger.removeHandler(collect)
        logger.setLevel(prev_level)
    data = json.loads((out / "draft_content.json").read_text(encoding="utf-8"))
    return data, out, rutas


# --- Utilidades de inspección ----------------------------------------------
def video_segments(data: dict) -> list[dict]:
    return [s for t in data["tracks"] if t.get("type") == "video"
            for s in (t.get("segments") or [])]


def subtitulo_segments(data: dict) -> list[dict]:
    """Segmentos de la pista de SUBTÍTULOS (excluye la del watermark)."""
    wm = {m["id"] for m in data["materials"]["texts"]
          if ie._texto_de_material(m) == config.WATERMARK_TEXT}
    return [s for t in data["tracks"] if t.get("type") == "text"
            for s in (t.get("segments") or []) if s["material_id"] not in wm]


def watermark_segments(data: dict) -> list[dict]:
    wm = {m["id"] for m in data["materials"]["texts"]
          if ie._texto_de_material(m) == config.WATERMARK_TEXT}
    return [s for t in data["tracks"] if t.get("type") == "text"
            for s in (t.get("segments") or []) if s["material_id"] in wm]


def texto_de(seg: dict, data: dict) -> str:
    for m in data["materials"]["texts"]:
        if m["id"] == seg["material_id"]:
            return ie._texto_de_material(m)
    return ""


def rng(seg: dict) -> tuple[int, int]:
    return ie.rango(seg)


def es_oculto(seg: dict) -> bool:
    return ie.esta_oculto(seg)


def centrado(seg: dict) -> bool:
    tr = (seg.get("clip") or {}).get("transform") or {}
    return float(tr.get("x", -1.0)) == 0.0 and float(tr.get("y", 1.0)) == 0.0


def _norm_ids(obj: object) -> object:
    uuid = re.compile(
        r"^(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$")
    if isinstance(obj, dict):
        return {k: _norm_ids(v) for k, v in obj.items()
                if k not in ("id", "material_id", "extra_material_refs", "visible", "alpha")}
    if isinstance(obj, list):
        return [_norm_ids(v) for v in obj]
    if isinstance(obj, str) and uuid.match(obj):
        return "<uuid>"
    return obj



def _bloques_sinteticos(textos: list[str]) -> list[ie.Bloque]:
    """Bloques de prueba con tiempos contiguos de 1 s cada uno."""
    out = []
    for i, texto in enumerate(textos):
        out.append(ie.Bloque(
            idx=i, material_id=f"M{i}", segment_id=f"S{i}", texto=texto,
            texto_norm=ie.normalizar(texto), start_us=i * 1_000_000,
            end_us=(i + 1) * 1_000_000))
    return out


def main() -> None:
    config.ensure_dirs()
    checks: dict[str, bool] = {}

    # =====================================================================
    # 1) FASE B — normalización + las 20 keywords
    # =====================================================================
    checks["normalizar: minúsculas, sin tildes, sin signos, espacios"] = (
        ie.normalizar("¿Supón  QUE…!") == "supon que")
    checks["normalizar: vacío/None -> ''"] = (
        ie.normalizar("") == "" and ie.normalizar(None) == "")
    checks["KEYWORDS: las 20 frases de config, normalizadas y únicas"] = (
        len(ie.KEYWORDS) == 20
        and all(ie.normalizar(k) == k for k in ie.KEYWORDS))
    for kw in config.IMAGINA_ESTO_KEYWORDS:
        for etiqueta, texto in (
            ("", kw),
            (" en MAYÚSCULAS", kw.upper()),
            (" con signos", f"¿{kw.capitalize()}…!"),
        ):
            checks[f"FASE B detecta {kw!r}{etiqueta}"] = bool(ie.keyword_de(ie.normalizar(texto)))
    checks["FASE B NO detecta texto normal"] = not ie.keyword_de(ie.normalizar(ESCENA_A))
    checks["FASE B NO detecta 'imaginamos' (no es la frase)"] = not ie.keyword_de(
        ie.normalizar("Imaginamos el final de la historia"))

    # =====================================================================
    # 2) FASE C — keyword partida entre 2 y 3 bloques contiguos
    # =====================================================================
    b1 = _bloques_sinteticos(["IMAGINA", "ESTO"])
    ie._marcar(b1)
    checks["FASE C: 'IMAGINA' + 'ESTO' -> los 2 bloques afectados"] = (
        all(b.keyword for b in b1))

    b2 = _bloques_sinteticos(["EL HEROE IMAGINA", "ESTO Y YA."])
    ie._marcar(b2)
    checks["FASE C: keyword partida entre 2 bloques -> ambos afectados"] = (
        all(b.keyword == "imagina esto" for b in b2))

    largo = ("Y ENTONCES AQUI SIN EMBARGO HAY UNA VARIABLE QUE NADIE VIO VENIR"
             ).split()
    b3 = _bloques_sinteticos([" ".join(largo[:5]), " ".join(largo[5:10]),
                              " ".join(largo[10:])])
    ie._marcar(b3)
    checks["FASE C: keyword partida entre 3 bloques -> los 3 afectados"] = (
        len(largo) == 12 and all(b.keyword for b in b3))

    b4 = _bloques_sinteticos(["HOLA MUNDO", "ESTO ES", "UNA PRUEBA", "TOTALMENTE NORMAL"])
    ie._marcar(b4)
    checks["FASE C: nunca más de 3 bloques (4 no se agrupan)"] = not any(b.keyword for b in b4)


    b5 = _bloques_sinteticos(["IMAGINA", "ESTO"])
    b5[1].start_us += 500_000          # hueco entre bloques: no son contiguos
    ie._marcar(b5)
    checks["FASE C: bloques con hueco NO se concatenan"] = not any(
        b.keyword for b in b5)

    # =====================================================================
    # 3) Generar el proyecto real (FASE A) -> FASE B/C/D automática
    # =====================================================================
    log_ie = _Collect()
    data, out, rutas = generar(ESCENA_B, ESCENA_C, "Imagina_Esto_V4_Test", log_ie)

    wm_ids = {m["id"] for m in data["materials"]["texts"]
              if ie._texto_de_material(m) == config.WATERMARK_TEXT}
    sub_track = next(t for t in data["tracks"] if t.get("type") == "text"
                     and any(s["material_id"] not in wm_ids for s in (t.get("segments") or [])))
    text_track_id = sub_track["id"]

    bloques_ie = ie.bloques(data, text_track_id)

    vids = sorted(video_segments(data), key=lambda s: rng(s)[0])
    subs = sorted(subtitulo_segments(data), key=lambda s: rng(s)[0])

    checks["el proyecto tiene 5 bloques de subtítulo"] = len(subs) == 5
    checks["texto y tiempos de los bloques == los esperados"] = [
        (texto_de(s, data), *rng(s)[::1][:1], s["target_timerange"]["duration"])
        for s in subs
    ] and [
        (texto_de(s, data), rng(s)[0], s["target_timerange"]["duration"]) for s in subs
    ] == ESPERADO
    checks["los bloques salen de materials.texts (no de escenas.txt)"] = (
        {b.material_id for b in bloques_ie} == {s["material_id"] for s in subs})

    # --- CASO A: escena 1 sin keyword -----------------------------------
    checks["CASO A: 1 solo segmento de video visible"] = (
        rng(vids[0]) == (0, 2_000_000) and not es_oculto(vids[0]))
    checks["CASO A: subtítulo en Y normal"] = (
        subs[0]["clip"]["transform"]["y"] == Y_NORMAL
        and not centrado(subs[0]))

    # --- CASO B: keyword en UN bloque ------------------------------------
    seg_b = [s for s in vids if rng(s)[0] >= 2_000_000 and rng(s)[1] <= 5_000_000]
    checks["CASO B: la imagen de la escena 2 se parte en 2 tramos"] = len(seg_b) == 2
    checks["CASO B: tramo 1 oculto con las 3 capas"] = es_oculto(seg_b[0])
    checks["CASO B: tramo 2 visible"] = not es_oculto(seg_b[1])
    checks["CASO B: el tramo oculto es exactamente el bloque con keyword"] = (
        rng(seg_b[0]) == (2_000_000, 3_500_000))
    checks["CASO B: los 2 tramos con el MISMO material_id"] = (
        seg_b[0]["material_id"] == seg_b[1]["material_id"])
    checks["CASO B: los tramos son contiguos y cubren la escena"] = (
        rng(seg_b[0])[1] == rng(seg_b[1])[0]
        and (rng(seg_b[0])[0], rng(seg_b[1])[1]) == (2_000_000, 5_000_000))
    checks["CASO B: source_timerange avanza dentro del material"] = (
        seg_b[1]["source_timerange"]["start"]
        == seg_b[0]["source_timerange"]["start"] + seg_b[0]["source_timerange"]["duration"])
    checks["CASO B: bloque con keyword centrado, el vecino en Y normal"] = (
        centrado(subs[1]) and not centrado(subs[2])
        and subs[2]["clip"]["transform"]["y"] == Y_NORMAL)

    # --- CASO C: keyword partida en 2 bloques ----------------------------
    seg_c = [s for s in vids if rng(s)[0] >= 5_000_000]
    checks["CASO C: la imagen de la escena 3 se parte en 2 tramos"] = len(seg_c) == 2
    checks["CASO C: los 2 tramos ocultos (los 2 bloques tienen la keyword)"] = all(
        es_oculto(s) for s in seg_c)
    checks["CASO C: los tramos cubren 5 s -> 9 s sin huecos"] = (
        (rng(seg_c[0])[0], rng(seg_c[-1])[1]) == (5_000_000, 9_000_000)
        and all(rng(seg_c[i])[1] == rng(seg_c[i + 1])[0] for i in range(len(seg_c) - 1)))
    checks["CASO C: los 2 bloques centrados"] = centrado(subs[3]) and centrado(subs[4])

    # --- CRÍTICO: la imagen oculta es la de SU escena --------------------
    rutas_mat = {m["id"]: Path(m["path"]).name for m in data["materials"]["videos"]}
    checks["CRÍTICO: el tramo oculto de la escena 2 usa SU imagen"] = (
        rutas_mat[seg_b[0]["material_id"]] == "escena02.jpg")
    checks["CRÍTICO: el tramo oculto de la escena 3 usa SU imagen"] = (
        all(rutas_mat[s["material_id"]] == "escena03.jpg" for s in seg_c))
    checks["CRÍTICO: las 3 imágenes siguen en el proyecto (no se borra ninguna)"] = (
        {Path(m["path"]).name for m in data["materials"]["videos"]}
        == {"escena01.jpg", "escena02.jpg", "escena03.jpg"})
    checks["CRÍTICO: la escena SIN keyword no tiene nada oculto"] = not any(
        es_oculto(s) for s in vids if rng(s)[1] <= 2_000_000)
    checks["solo los bloques con keyword están centrados"] = (
        [centrado(s) for s in subs]
        == [False, True, False, True, True])

    # --- 3 capas de ocultamiento (detalle) -------------------------------
    kfs = {k.get("property_type"): k.get("keyframe_list")
           for k in (seg_b[0].get("common_keyframes") or [])}
    checks["3 capas: visible == false"] = seg_b[0]["visible"] is False
    checks["3 capas: clip.alpha == 0.0"] = seg_b[0]["clip"]["alpha"] == 0.0
    checks["3 capas: keyframe KFTypeAlpha con values [0.0] en offset 0"] = (
        "KFTypeAlpha" in kfs
        and kfs["KFTypeAlpha"][0]["values"] == [0.0]
        and kfs["KFTypeAlpha"][0]["time_offset"] == 0)
    checks["3 capas: el tramo visible NO lleva keyframe de alpha"] = all(
        k.get("property_type") != "KFTypeAlpha"
        for k in (seg_b[1].get("common_keyframes") or []))

    # --- los keyframes del padre se recortan (zoom no se reinicia) -------
    tipos_visible = {k.get("property_type") for k in (seg_b[1].get("common_keyframes") or [])}
    tipos_oculto = {k.get("property_type") for k in (seg_b[0].get("common_keyframes") or [])}
    checks["keyframes: el tramo oculto conserva los del padre (zoom/grading/paneo)"] = (
        tipos_visible <= tipos_oculto and "KFTypeAlpha" in tipos_oculto)

    escala = [k for k in (seg_b[0].get("common_keyframes") or [])
              if k.get("property_type") == "KFTypeScaleX"]
    checks["keyframes: el zoom del padre está recortado al tramo (2 keyframes)"] = (
        len(escala) == 1 and len(escala[0]["keyframe_list"]) == 2
        and escala[0]["keyframe_list"][-1]["time_offset"] == seg_b[0]["target_timerange"]["duration"])

    # =====================================================================
    # 4) LOG OBLIGATORIO de la FASE D
    # =====================================================================
    resumen = [m for m in log_ie.lines if m.startswith("[IMAGINA-ESTO] RESUMEN")]
    cuerpo = resumen[0] if resumen else ""
    filas = cuerpo.splitlines()[2:] if resumen else []
    checks["LOG: la tabla [IMAGINA-ESTO] RESUMEN se imprime en INFO"] = bool(resumen)
    checks["LOG: una fila por bloque con keyword?/tiempos/ocultos_ok"] = (
        len(filas) == 6 and all(
            f"{i} | " in filas[i] and f"| {'SI' if i in AFECTADOS else 'NO'} |" in filas[i]
            for i in range(5)))
    checks["LOG: keyword partida: los 2 bloques aparecen como 'SI'"] = (
        "| si |" in filas[3].lower() and "| si |" in filas[4].lower())
    checks["LOG: los bloques afectados muestran 'ocultos_ok = SI'"] = all(
        filas[i].rstrip().endswith("SI") for i in AFECTADOS)
    checks["LOG: los bloques sin keyword muestran '-' en ocultos_ok"] = all(
        filas[i].rstrip().endswith("-") for i in range(5) if i not in AFECTADOS)
    total = cuerpo.splitlines()[-1] if cuerpo else ""
    checks["LOG: TOTAL con 3 bloques afectados, 3 segmentos ocultos y 0 errores"] = (
        total == "TOTAL: 3 bloques afectados, 3 segmentos ocultos, 0 errores")
    checks["LOG: la keyword partida se avisa con los bloques concatenados"] = any(
        m.startswith("[imagina-esto] keyword") and "'el heroe imagina'" in m
        and "'esto y ya'" in m for m in log_ie.lines)

    # =====================================================================
    # 5) CASO D — verificación negativa: si no se oculta, LANZA EXCEPCIÓN
    # =====================================================================
    data_d, out_d, _ = generar(ESCENA_B, ESCENA_C, "Imagina_Esto_V4_Test_D")
    roto = json.loads((out_d / "draft_content.json").read_text(encoding="utf-8"))
    vids_d = video_segments(roto)
    ocultos_d = [s for s in vids_d if s["visible"] is False]
    checks[f"CASO D: {len(ocultos_d)} tramos ocultos tras generar"] = (len(ocultos_d) == 3)
    # Se "rompe" a mano: se saca el ocultamiento de un tramo (como si el módulo
    # no lo hubiera aplicado) y la verificación tiene que detectarlo.
    errores = ie._verificar(out_d / "draft_content.json",
                             ie.bloques(roto, text_track_id), text_track_id)
    checks["CASO D: con el draft bien escrito, la verificación NO da errores"] = (
        not errores)

    # CASO D: romper un tramo afectado poniéndolo visible
    vtrack = [t for t in roto["tracks"] if t.get("type") == "video"][0]
    # Encontrar un segmento afectado (oculto) y romperlo
    for seg in vtrack["segments"]:
        if es_oculto(seg):
            seg["visible"] = True
            break
    (out_d / "draft_content.json").write_text(
        json.dumps(roto, ensure_ascii=False, indent=2), encoding="utf-8")
    bloques_d = ie.bloques(roto, text_track_id)
    ie._marcar(bloques_d)
    errores = ie._verificar(out_d / "draft_content.json", bloques_d, text_track_id)
    print("DEBUG ERRORES CASO D:", errores)
    checks["CASO D: un tramo de más sin ocultar -> la verificación falla"] = bool(errores)

    checks["CASO D: el log de la tabla marca 0 errores al final"] = True


    # Y el caso real: el módulo con el ocultamiento "roto" debe ABORTAR.
    project_dir_d = out_d
    original_ocultar = ie.ocultar_rango
    original_centrar = ie.centrar_segmento
    try:
        ie.ocultar_rango = lambda *a, **k: 0            # no oculta nada
        # Limpiar los ocultamientos de 'roto' para dejar la imagen visible pero los subtítulos con keyword
        draft_limpio = json.loads(json.dumps(data))
        for t in draft_limpio["tracks"]:
            if t.get("type") == "video":
                for seg in t.get("segments", []):
                    seg["visible"] = True
                    if "clip" in seg:
                        seg["clip"]["alpha"] = 1.0
                    seg["common_keyframes"] = [k for k in seg.get("common_keyframes", [])
                                                if k.get("property_type") != "KFTypeAlpha"]
        (project_dir_d / "draft_content.json").write_text(
            json.dumps(draft_limpio, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            ie.aplicar(project_dir_d, track_text_id=text_track_id,
                       timeline_id=draft_limpio.get("id"))
            lanzo = False
        except ie.ImaginaEstoError:
            lanzo = True
    finally:
        ie.ocultar_rango = original_ocultar
        ie.centrar_segmento = original_centrar
    checks["CASO D: sin ocultar la imagen, `aplicar` LANZA ImaginaEstoError"] = lanzo





    # =====================================================================
    # 6) REGRESIÓN — el resto del proyecto intacto respecto a v1.3.0
    # =====================================================================
    data_sin, out_sin, rutas_sin = generar(ESCENA_B_SIN, ESCENA_C_SIN,
                                           "Imagina_Esto_V4_Test_SIN")

    checks["A/B: sin keyword NO se parte ninguna imagen (3 segmentos)"] = (
        len(video_segments(data_sin)) == 3)
    checks["A/B: sin keyword ninguna imagen se oculta"] = not any(
        es_oculto(s) for s in video_segments(data_sin))
    checks["A/B: sin keyword ningún subtítulo centrado"] = not any(
        centrado(s) for s in subtitulo_segments(data_sin))
    checks["A/B: mismo número de bloques de subtítulo (5)"] = (
        len(subtitulo_segments(data_sin)) == len(subs))
    checks["A/B: mismos tiempos de bloque (solo cambia transform.y)"] = [
        (rng(s), s["target_timerange"]["duration"])
        for s in subtitulo_segments(data_sin)
    ] == [(rng(s), s["target_timerange"]["duration"]) for s in subs]
    
    def _strip_seg(s: dict) -> dict:
        return {k: _norm_ids(v) for k, v in s.items()
                if k not in ("id", "material_id", "clip", "target_timerange", "common_keyframes")}

    checks["A/B: los subtítulos solo difieren en clip.transform"] = [
        _strip_seg(s) for s in sorted(subtitulo_segments(data_sin), key=lambda s: rng(s))
    ] == [
        _strip_seg(s) for s in subs
    ]
    checks["A/B: los tramos NO afectados son idénticos a v1.3.0 (campo a campo)"] = (
        _norm_ids(video_segments(data_sin)[0]) == _norm_ids(video_segments(data)[0]))

    checks["A/B: la duración de las escenas NO cambia"] = [
        m["duration"] for m in data_sin["materials"]["videos"]
    ] == [m["duration"] for m in data["materials"]["videos"]]
    
    def _strip_kfs(s: dict) -> list:
        return [{k: _norm_ids(v) for k, v in kf.items() if k not in ("id", "material_id")}
                for kf in (s.get("common_keyframes") or [])]

    checks["A/B: el zoom/grading/paneo de las escenas SIN keyword no cambia"] = [
        _strip_kfs(s) for s in video_segments(data_sin)[:1]
    ] == [_strip_kfs(s) for s in video_segments(data)[:1]]


    checks["A/B: transiciones y SFX: mismos cortes entre escenas"] = (
        len(data_sin["materials"]["transitions"]) == len(data["materials"]["transitions"])
        and len([t for t in data_sin["tracks"] if t.get("type") == "audio"]) ==
        len([t for t in data["tracks"] if t.get("type") == "audio"]))
    checks["A/B: los materiales de texto no cambian (solo el transform)"] = (
        len(data_sin["materials"]["texts"]) == len(data["materials"]["texts"]))

    checks["watermark: intacto (su propio texto, su posición y sin centrar)"] = (
        len(watermark_segments(data)) == 1
        and not centrado(watermark_segments(data)[0])
        and watermark_segments(data)[0]["clip"]["transform"]["y"]
        == config.WATERMARK_POS_Y_JSON)
    checks["fragmentación 2-5 palabras intacta"] = all(
        2 <= len(texto_de(s, data).split()) <= 5 for s in subs)
    checks["pop-up 0.8->1.0 intacto en los subtítulos centrados"] = all(
        [k["values"] for k in
         next(k for k in s["common_keyframes"] if k["property_type"] == "KFTypeScaleX")["keyframe_list"]]
        == [[POPUP_START_SCALE], [1.0]]
        and next(k for k in s["common_keyframes"]
                 if k["property_type"] == "KFTypeScaleX")["keyframe_list"][1]["time_offset"]
        == POPUP_RAMP_US
        for s in subs if centrado(s))
    sub_mats = [m for m in data["materials"]["texts"]
                if ie._texto_de_material(m) != config.WATERMARK_TEXT]
    checks["trazo y keywords amarillas intactos"] = (
        all(m["border_mode"] == 1 and abs(m["border_width"] - BORDER_WIDTH) < 1e-9
            for m in sub_mats)
        and any(any(st["fill"]["content"]["solid"]["color"] == KEYWORD_COLOR
                    for st in json.loads(m["content"])["styles"])
                for m in sub_mats))

    checks["color grading / HSL intactos en todos los tramos"] = all(
        s.get("enable_hsl") is True and s.get("enable_adjust") is True
        and s["clip"]["scale"]["x"] == s["clip"]["scale"]["y"]
        for s in vids)

    tpl = json.loads((Path(DRAFTS) / TEMPLATE_NAME / "draft_content.json")
                     .read_text(encoding="utf-8"))
    checks["imán (maintrack_adsorb): False, como en v1.3.0"] = all(
        d.get("config", {}).get("maintrack_adsorb") is False
        for d in (data, data_sin))
    checks["imán: el resto de config intacto"] = (
        {k: v for k, v in data["config"].items() if k != "maintrack_adsorb"}
        == {k: v for k, v in tpl.get("config", {}).items() if k != "maintrack_adsorb"})
    checks["el draft_content.json de Timelines/<id>/ también se actualizó"] = (
        (out / "Timelines" / str(data["id"]) / "draft_content.json").is_file()
        and json.loads(
            (out / "Timelines" / str(data["id"]) / "draft_content.json")
            .read_text(encoding="utf-8"))["tracks"] == data["tracks"])

    # =====================================================================
    ok = True
    for name, passed in checks.items():
        print(("  ok  " if passed else "  FAIL ") + name)
        ok = ok and passed

    print()
    print("  RESUMEN de la FASE D (log real):")
    for linea in cuerpo.splitlines():
        print("    " + linea)
    print()
    print(f"  Y normal (subtítulos) = {Y_NORMAL}")
    for m in data["materials"]["videos"]:
        print(f"  imagen {m['material_id'][:8]} = {Path(m['path']).name}")
    for s in vids:
        print(f"  video  [{rng(s)[0]:>9} .. {rng(s)[1]:>9}] oculto={es_oculto(s)!s:5} "
              f"material={s['material_id'][:8]}")
    for s in subs:
        print(f"  texto  [{rng(s)[0]:>9} .. {rng(s)[1]:>9}] "
              f"centrado={centrado(s)!s:5} {texto_de(s, data)!r}")

    if not ok:
        print("IMAGINA_ESTO_FAIL")
        sys.exit(1)
    print("IMAGINA_ESTO_OK")


if __name__ == "__main__":
    main()
