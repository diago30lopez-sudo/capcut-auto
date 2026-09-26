"""v1.4.0 FIX v4 ??? "Imagina esto" como POST-PROCESO del `draft_content.json`.

Filosof??a
---------
La detecci??n se hace sobre los **SUBT??TULOS YA GENERADOS**
(`materials.texts` + el `target_timerange` de su segmento), **NO** sobre el
texto de `escenas.txt`. Cada bloque de subt??tulo ya tiene su rango temporal
(`start` + `duration`), as?? que ese rango ES exactamente la parte de la imagen
que hay que ocultar: no hay que emparejar escenas ??? segmentos y no se puede
confundir una imagen con otra.

Flujo (4 fases, tal y como se ejecuta aqu??):

| Fase | Qu?? hace | D??nde |
|---|---|---|
| **A** | el proyecto se genera normal (v1.3.0) y se escribe el JSON | `capcut_project.CapCutProject.generate` |
| **B** | leer el JSON, normalizar cada subt??tulo y marcar los que tienen keyword | `aplicar` ??? `bloques()` + `_marcar()` |
| **C** | una keyword partida en 2-3 bloques contiguos marca **todos** los bloques | `_marcar()` |
| **D** | centrar el subt??tulo, ocultar la imagen debajo y **verificar** | `centrar_segmento()`, `ocultar_rango()`, `_verificar()` |

FASE D.2 ??? ocultar la imagen
-----------------------------
Se busca en la pista de video (`type == "video"`) los segmentos cuyo
`target_timerange` se solapa con `[t_start, t_end)` y **se dividen** en tres
sub-segmentos contiguos, con el **mismo `material_id`** y ajustando
`source_timerange` + `target_timerange`:

* `antes`   ??? sin cambios,
* `durante` ??? `visible: false` + `clip.alpha: 0.0` + keyframe `KFTypeAlpha`
              (`values: [0.0]`, `time_offset: 0`) ??? las **3 capas** juntas,
* `despu??s` ??? sin cambios.

Los `common_keyframes` del padre (zoom, color grading, paneo) se **recortan** al
sub-rango con `_slice_keyframes` para que cada trozo siga siendo la **misma**
curva y el zoom no se reinicie dentro de la imagen partida. Si la divisi??n
fallara, se recurre a la **opci??n de respaldo** (ocultar el segmento completo) y
se deja escrito por qu?? en el log.

FASE D.3 ??? verificaci??n obligatoria
-----------------------------------
Tras escribir, se **vuelve a leer el JSON desde disco** y se comprueba, bloque a
bloque afectado, que:

1. el segmento de texto tiene `clip.transform == {x: 0.0, y: 0.0}`,
2. todos los segmentos de video que se solapan con su rango est??n ocultos
   (`visible == false` **y** `clip.alpha == 0.0`),
3. esos segmentos tienen un keyframe `KFTypeAlpha` con `values: [0.0]`.

Si algo falla se lanza `ImaginaEstoError` (el caller aborta la generaci??n y no
deja el proyecto a medias).

Nota sobre `track_text_id`: el generador pasa el id de la pista de
**subt??tulos** para que la pista del **watermark** (tambi??n `type == "text"`)
nunca se centre ni se contamine en el log.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from src.core import config

log = logging.getLogger("capcutauto")

CONTENT_JSON = "draft_content.json"

# FASE C: nunca se concatenan m??s de 3 bloques seguidos (evita falsos positivos
# al cruzar frases de escenas distintas).
MAX_BLOQUES_CONCATENADOS = 3

# Signos de puntuaci??n que se ignoran al comparar (la lista de la especificaci??n:
# ?? ? ?? ! . , ; : " ' ??? ). Se elimina todo lo que no sea letra ni d??gito, lo que
# adem??s cubre guiones y par??ntesis.
_NO_ALFANUMERICO = re.compile(r"[^a-z0-9]+")


class ImaginaEstoError(RuntimeError):
    """Fallo de la verificaci??n de la FASE D.3: se aborta la generaci??n."""


# ---------------------------------------------------------------------------
# Normalizaci??n (id??ntica para el texto del subt??tulo y para las keywords)
# ---------------------------------------------------------------------------
def normalizar(texto: str | None) -> str:
    """min??sculas + sin tildes + sin puntuaci??n + espacios colapsados.

    `"??Sup??n  que???!"` ??? `"supon que"`. Se usa para los subt??tulos y para
    `config.IMAGINA_ESTO_KEYWORDS`, as?? que da igual c??mo se escriba la frase
    (con tildes, en may??sculas o con signos)."""
    if not texto:
        return ""
    plano = unicodedata.normalize("NFKD", texto)
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    plano = plano.lower()
    plano = _NO_ALFANUMERICO.sub(" ", plano)
    return " ".join(plano.split())


# Las keywords se normalizan al importar (una sola vez) y se ordenan de m??s
# larga a m??s corta (y alfab??ticamente entre iguales, para que el orden sea
# estable) para que, si dos coinciden a la vez, se informe de la m??s larga.
KEYWORDS: tuple[str, ...] = tuple(sorted(
    {normalizar(kw) for kw in config.IMAGINA_ESTO_KEYWORDS},
    key=lambda k: (-len(k), k),
))


def keyword_de(texto_norm: str) -> str:
    """Keyword de la v1.4.0 contenida en un texto YA normalizado ('' si ninguna)."""
    for kw in KEYWORDS:
        if kw and kw in texto_norm:
            return kw
    return ""


# ---------------------------------------------------------------------------
# FASE B ??? bloques de subt??tulo
# ---------------------------------------------------------------------------
@dataclass
class Bloque:
    """Un bloque de subt??tulo: su texto (ya normalizado) y su rango temporal."""

    idx: int
    material_id: str
    segment_id: str
    texto: str
    texto_norm: str
    start_us: int
    end_us: int
    keyword: str = ""                 # "" = no afectado
    grupo: tuple[int, ...] = ()       # bloques concatenados (FASE C)
    ocultos: int = 0                  # sub-segmentos de video ocultos
    ocultos_ok: bool = False

    @property
    def afectado(self) -> bool:
        return bool(self.keyword)

    @property
    def duration_us(self) -> int:
        return self.end_us - self.start_us


def _texto_de_material(mat: dict) -> str:
    """Texto de un material `text` de CapCut (`content` es un JSON en string)."""
    content = mat.get("content")
    if not isinstance(content, str):
        return ""
    try:
        return str(json.loads(content).get("text") or "")
    except (ValueError, AttributeError):
        match = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
        if not match:
            return ""
        try:
            return json.loads(f'"{match.group(1)}"')
        except ValueError:
            return ""


def _textos_por_id(content: dict) -> dict[str, str]:
    return {
        m["id"]: _texto_de_material(m)
        for m in (content.get("materials", {}).get("texts") or [])
        if m.get("id")
    }


def _pistas_text(content: dict, track_text_id: str | None = None) -> list[dict]:
    pistas = [t for t in (content.get("tracks") or []) if t.get("type") == "text"]
    if track_text_id:
        pistas = [t for t in pistas if t.get("id") == track_text_id]
    return pistas


def _pistas_video(content: dict) -> list[dict]:
    return [t for t in (content.get("tracks") or []) if t.get("type") == "video"]


def bloques(content: dict, track_text_id: str | None = None) -> list[Bloque]:
    """FASE B: bloques de subt??tulo con texto, tiempos y texto normalizado.

    Un "bloque" es el par (material de texto, segmento que lo reproduce): el
    texto viene de `materials.texts` y los tiempos del `target_timerange` del
    segmento, que es lo que CapCut dibuja en pantalla."""
    textos = _textos_por_id(content)
    brutos: list[tuple[int, int, str, str, str]] = []  # start, end, mat, seg, texto
    for pista in _pistas_text(content, track_text_id):
        for seg in (pista.get("segments") or []):
            mat_id = seg.get("material_id")
            texto = textos.get(mat_id, "")
            rango = seg.get("target_timerange") or {}
            start = int(rango.get("start") or 0)
            dur = int(rango.get("duration") or 0)
            if not texto.strip() or dur <= 0:
                continue
            brutos.append((start, start + dur, mat_id, seg.get("id", ""), texto))
    brutos.sort(key=lambda b: (b[0], b[1], b[3]))
    return [
        Bloque(idx=i, material_id=mat, segment_id=seg, texto=texto,
               texto_norm=normalizar(texto), start_us=start, end_us=end)
        for i, (start, end, mat, seg, texto) in enumerate(brutos)
    ]


# ---------------------------------------------------------------------------
# FASE C ??? keyword partida entre 2 o 3 bloques contiguos
# ---------------------------------------------------------------------------
def _contiguos(grupo: list[Bloque]) -> bool:
    """True si los bloques del grupo van uno tras otro, sin huecos entre ellos."""
    return all(
        grupo[i].start_us == grupo[i - 1].end_us for i in range(1, len(grupo))
    )


def _marcar(bloques_: list[Bloque]) -> None:
    """FASE B + FASE C: marca los bloques afectados por una keyword.

    1) cada bloque se busca por su cuenta (sobre su texto normalizado);
    2) si no aparece, se concatenan 2 y 3 bloques **contiguos** (rangos
       temporales seguidos, sin huecos) y se busca en la concatenaci??n: si
       aparece la keyword se marcan **todos** los bloques del grupo. Como mucho
       3 bloques, para no arrastrar frases de escenas distintas."""
    for b in bloques_:
        b.keyword = keyword_de(b.texto_norm)
        b.grupo = (b.idx,) if b.keyword else ()
    for largo in range(2, MAX_BLOQUES_CONCATENADOS + 1):
        for i in range(len(bloques_)):
            grupo = bloques_[i:i + largo]
            if len(grupo) < largo or not _contiguos(grupo):
                continue
            
            # Solo buscamos si hay alguna posibilidad de que la keyword est?? partida.
            # Si todos los bloques ya tienen su propia keyword, no hace falta.
            if all(b.keyword for b in grupo):
                continue

            texto_concat = " ".join(b.texto_norm for b in grupo)
            kw = keyword_de(texto_concat)
            if not kw:
                continue
            
            # CR??TICO: El keyword no debe estar ya contenido en ning??n subgrupo
            # contiguo m??s peque??o. Si lo est??, ese subgrupo m??s peque??o es el
            # que debe marcarse (o ya se marc??), no este grupo m??s grande.
            tiene_en_subgrupo = False
            for sub_largo in range(1, len(grupo)):
                for start_idx in range(len(grupo) - sub_largo + 1):
                    sub_grupo = grupo[start_idx:start_idx + sub_largo]
                    if kw in " ".join(sb.texto_norm for sb in sub_grupo):
                        tiene_en_subgrupo = True
                        break
                if tiene_en_subgrupo:
                    break
            if tiene_en_subgrupo:
                continue

            for b in grupo:
                if not b.keyword:
                    b.keyword = kw
                    b.grupo = tuple(range(i, i + largo))
            log.info(
                "[imagina-esto] keyword %r partida entre los bloques %s: %s",
                kw, list(range(i, i + largo)),
                " + ".join(repr(b.texto_norm) for b in grupo),
            )




# ---------------------------------------------------------------------------
# FASE D.1 ??? centrar el subt??tulo
# ---------------------------------------------------------------------------
def centrar_segmento(seg: dict) -> None:
    """`clip.transform = {x: 0.0, y: 0.0}` (centro del lienzo).

    El `transform` vive en el SEGMENTO de texto (no en el material): es el
    campo que CapCut lee para colocar la caja, igual que lleva
    `subtitles.SUBTITLE_Y` en los subt??tulos normales."""
    transform = seg.setdefault("clip", {}).setdefault("transform", {})
    transform["x"] = 0.0
    transform["y"] = 0.0


# ---------------------------------------------------------------------------
# FASE D.2 ??? ocultar la imagen
# ---------------------------------------------------------------------------
def _new_id() -> str:
    return uuid.uuid4().hex.upper()


def _keyframe(t_us: int, value: float) -> dict:
    """Keyframe individual de CapCut (mismo formato que el draft de referencia)."""
    return {
        "id": _new_id(),
        "curveType": "Line",
        "time_offset": int(t_us),
        "left_control": {"x": 0.0, "y": 0.0},
        "right_control": {"x": 0.0, "y": 0.0},
        "values": [float(value)],
        "string_value": "",
        "curve_id": "",
        "property_type": "",
    }


def _alpha_keyframe(value: float = 0.0, t_us: int = 0) -> dict:
    """Keyframe `KFTypeAlpha` con un ??nico valor constante (3?? capa del ocultamiento)."""
    return {
        "id": _new_id(),
        "material_id": "",
        "property_type": "KFTypeAlpha",
        "keyframe_list": [_keyframe(t_us, value)]
    }



def _interp(points: list[tuple[int, float]], t_us: int) -> float:
    """Valor de una curva `[(t_us, valor), ...]` en `t_us` (lineal, saturada)."""
    if not points:
        return 0.0
    if t_us <= points[0][0]:
        return points[0][1]
    if t_us >= points[-1][0]:
        return points[-1][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= t_us <= t1:
            if t1 == t0:
                return v1
            return v0 + (v1 - v0) * (t_us - t0) / (t1 - t0)
    return points[-1][1]


def _slice_keyframes(kfs: list[dict], sub_start: int, sub_end: int) -> list[dict]:
    """Recorta los `common_keyframes` del padre a [sub_start, sub_end) y rebasea a 0.

    Los `time_offset` de un segmento son RELATIVOS a su propio inicio, as?? que al
    partir una imagen cada trozo debe seguir la **misma** curva de zoom / color
    grading / paneo (si no, el zoom se reiniciar??a dentro de cada trozo). Se
    conservan los keyframes interiores y se a??aden los dos extremos con el valor
    interpolado; los de un solo punto (los est??ticos de color) siguen siendo un
    ??nico keyframe constante."""
    out: list[dict] = []
    dur = max(sub_end - sub_start, 1)
    for entry in kfs or []:
        if not isinstance(entry, dict):
            continue
        pts = [(int(k.get("time_offset") or 0), float((k.get("values") or [0.0])[0]))
               for k in (entry.get("keyframe_list") or [])]
        if not pts:
            continue
        base = {
            "id": _new_id(),
            "material_id": entry.get("material_id", ""),
            "property_type": entry.get("property_type", ""),
        }
        if len(pts) == 1:
            out.append({**base, "keyframe_list": [_keyframe(0, pts[0][1])]})
            continue
        recortados: list[tuple[int, float]] = [
            (0, _interp(pts, sub_start)),
            *[(t - sub_start, v) for t, v in pts if sub_start < t < sub_end],
            (dur, _interp(pts, sub_end)),
        ]
        out.append({**base, "keyframe_list": [_keyframe(t, v) for t, v in recortados]})
    return out


def esta_oculto(seg: dict) -> bool:
    """True si el segmento lleva las 3 capas de ocultamiento."""
    alpha_kf = any(
        k.get("property_type") == "KFTypeAlpha"
        and (k.get("keyframe_list") or [{}])[0].get("values") == [0.0]
        for k in (seg.get("common_keyframes") or [])
    )
    return (
        seg.get("visible") is False
        and float((seg.get("clip") or {}).get("alpha", 1.0)) == 0.0
        and alpha_kf
    )


def _ocultar_segmento(seg: dict) -> None:
    """Aplica las 3 capas de ocultamiento a un sub-segmento.

    1. `visible: false` (el conmutador del clip en la timeline de CapCut),
    2. `clip.alpha: 0.0` (la plantilla lo trae en 1.0),
    3. keyframe `KFTypeAlpha` con `values: [0.0]` en `time_offset: 0`.

    Se aplican JUNTAS porque la verificaci??n visual de v1.4.0 mostr?? que el
    preview de CapCut puede ignorar `visible: false`."""
    seg["visible"] = False
    seg.setdefault("clip", {})["alpha"] = 0.0
    seg.setdefault("common_keyframes", []).append(_alpha_keyframe(0.0, 0))


def rango(seg: dict) -> tuple[int, int]:
    """`(start, end)` del `target_timerange` de un segmento."""
    r = seg.get("target_timerange") or {}
    start = int(r.get("start") or 0)
    return start, start + int(r.get("duration") or 0)


def _copia(seg: dict, target: tuple[int, int], source: tuple[int, int],
           kfs: list[dict]) -> dict:
    nuevo = copy.deepcopy(seg)
    nuevo["id"] = _new_id()
    nuevo["target_timerange"] = {"start": target[0], "duration": target[1] - target[0]}
    nuevo["source_timerange"] = {"start": source[0], "duration": source[1] - source[0]}
    nuevo["common_keyframes"] = kfs
    return nuevo


def dividir_segmento(seg: dict, ini: int, fin: int) -> list[dict]:
    """Parte `seg` en [antes] [durante(oculto)] [despu??s] dentro de [ini, fin).

    Los sub-segmentos son CONTIGUOS (el `start` del siguiente es el `end` del
    anterior), conservan el `material_id` y el resto de campos del padre (zoom,
    HSL, color grading y transiciones de `extra_material_refs`), y el
    `source_timerange` de cada uno avanza dentro del material."""
    s, e = rango(seg)
    src = seg.get("source_timerange") or {}
    ss = int(src.get("start") or 0)
    dur = e - s
    factor = (int(src.get("duration") or dur) / dur) if dur > 0 else 1.0
    kfs_padre = list(seg.get("common_keyframes") or [])

    def _offs(a: int, b: int) -> list[dict]:
        return _slice_keyframes(kfs_padre, max(0, min(a, dur)), max(0, min(b, dur)))

    def _src(a: int) -> int:
        return ss + int(round((a - s) * factor))

    trozos: list[dict] = []
    if ini > s:                                    # antes (sin cambios)
        trozos.append(_copia(seg, (s, ini), (_src(s), _src(ini)), _offs(0, ini - s)))
    d_ini, d_fin = max(ini, s), min(fin, e)         # durante (oculto)
    if d_fin > d_ini:
        oculto = _copia(seg, (d_ini, d_fin), (_src(d_ini), _src(d_fin)),
                        _offs(d_ini - s, d_fin - s))
        _ocultar_segmento(oculto)
        trozos.append(oculto)
    if e > fin:                                    # despu??s (sin cambios)
        trozos.append(_copia(seg, (fin, e), (_src(fin), _src(e)), _offs(fin - s, dur)))
    return trozos


def ocultar_rango(content: dict, ini: int, fin: int) -> int:
    """Oculta la imagen durante [ini, fin) en las pistas de video.

    Devuelve el n?? de segmentos ocultos (los reci??n creados + los que ya estaban
    ocultos por un bloque anterior). Opci??n de respaldo: si la divisi??n de un
    segmento fallara, se oculta el segmento COMPLETO y se avisa por log."""
    ocultados = 0
    for pista in _pistas_video(content):
        nuevos: list[dict] = []
        cambiado = False
        for seg in (pista.get("segments") or []):
            s, e = rango(seg)
            if e <= ini or s >= fin:
                nuevos.append(seg)
                continue
            if esta_oculto(seg):
                nuevos.append(seg)      # ya oculto: no se vuelve a partir
                ocultados += 1
                continue
            try:
                trozos = dividir_segmento(seg, ini, fin)
            except Exception as exc:  # noqa: BLE001 - respaldo, nunca aborta
                log.warning(
                    "[imagina-esto] no se pudo dividir el segmento %s (%s): "
                    "se oculta COMPLETO (opci??n de respaldo).",
                    seg.get("id"), exc,
                )
                _ocultar_segmento(seg)
                nuevos.append(seg)
                ocultados += 1
                cambiado = True
                continue
            nuevos.extend(trozos or [seg])
            ocultados += sum(1 for t in trozos if esta_oculto(t))
            cambiado = True
        if cambiado:
            pista["segments"] = nuevos
    return ocultados


# ---------------------------------------------------------------------------
# FASE D.3 ??? verificaci??n obligatoria (vuelve a leer el JSON desde disco)
# ---------------------------------------------------------------------------
def _verificar(path: Path, esperados: list[Bloque],
               track_text_id: str | None = None) -> list[str]:
    """Relee el JSON de disco y comprueba cada bloque afectado.

    Devuelve la lista de errores (vac??a si todo est?? bien). Cada error empieza
    por `bloque <idx>: ` para poder atribuirlo a su bloque."""
    errores: list[str] = []
    data = json.loads(path.read_text(encoding="utf-8"))
    ids_text = {m["id"] for m in (data.get("materials", {}).get("texts") or [])}

    segmentos_text: dict[str, dict] = {}
    for pista in _pistas_text(data, track_text_id):
        for seg in (pista.get("segments") or []):
            segmentos_text.setdefault(seg.get("material_id"), seg)
    segmentos_video: list[dict] = [
        seg for pista in _pistas_video(data) for seg in (pista.get("segments") or [])
    ]

    for b in esperados:
        if b.material_id not in ids_text:
            errores.append(f"bloque {b.idx}: el material de texto desaparece del draft")
            continue
        seg_txt = segmentos_text.get(b.material_id)
        if seg_txt is None:
            errores.append(
                f"bloque {b.idx} ({b.texto_norm!r}): el material de texto "
                f"{b.material_id} no tiene segmento en el draft")
            continue
        transform = (seg_txt.get("clip") or {}).get("transform") or {}
        es_centrado = float(transform.get("x", -1.0)) == 0.0 and float(transform.get("y", 1.0)) == 0.0
        
        solapados = [s for s in segmentos_video
                     if rango(s)[1] > b.start_us and rango(s)[0] < b.end_us]

        if b.afectado:
            if not es_centrado:
                errores.append(
                    f"bloque {b.idx} ({b.texto_norm!r}): con keyword pero NO est?? "
                    f"centrado (transform={transform})")
            if not solapados:
                errores.append(
                    f"bloque {b.idx} ({b.texto_norm!r}): con keyword pero sin imagen "
                    f"debajo en [{b.start_us} .. {b.end_us})")
            else:
                for seg in solapados:
                    if not esta_oculto(seg):
                        errores.append(
                            f"bloque {b.idx} ({b.texto_norm!r}): el segmento de video "
                            f"{seg.get('id')} [{rango(seg)[0]} .. {rango(seg)[1]}) NO est?? "
                            f"oculto (visible={seg.get('visible')}, "
                            f"alpha={(seg.get('clip') or {}).get('alpha')})")
        else:
            # Si NO tiene keyword, NO debe estar centrado y NO debe estar oculto
            if es_centrado:
                errores.append(
                    f"bloque {b.idx} ({b.texto_norm!r}): SIN keyword pero EST?? "
                    f"centrado (transform={transform})")
            for seg in solapados:
                if esta_oculto(seg):
                    errores.append(
                        f"bloque {b.idx} ({b.texto_norm!r}): SIN keyword pero el "
                        f"segmento de video {seg.get('id')} [{rango(seg)[0]} .. "
                        f"{rango(seg)[1]}) EST?? oculto")
    return errores


# ---------------------------------------------------------------------------
# Orquestaci??n de las FASES B + C + D
# ---------------------------------------------------------------------------
def _escribir(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _log_resumen(bloques_: list[Bloque], errores: list[str]) -> None:
    """LOG OBLIGATORIO: tabla bloque a bloque + TOTAL."""
    lineas = [
        "[IMAGINA-ESTO] RESUMEN",
        "bloque_idx | texto_normalizado | keyword? | t_start_ms | t_end_ms | "
        "segmentos_afectados | ocultos_ok",
    ]
    for b in bloques_:
        if b.afectado:
            estado = "SI" if b.ocultos_ok else "NO"
        else:
            estado = "-" if b.ocultos_ok else "NO"

        lineas.append(
            f"{b.idx} | {b.texto_norm} | {'SI' if b.afectado else 'NO'} | "
            f"{b.start_us // 1000} | {b.end_us // 1000} | {b.ocultos} | {estado}"
        )
    for err in errores:
        lineas.append(f"ERROR | {err}")
    afectados = sum(1 for b in bloques_ if b.afectado)
    ocultos = sum(b.ocultos for b in bloques_)
    lineas.append(
        f"TOTAL: {afectados} bloques afectados, {ocultos} segmentos ocultos, "
        f"{len(errores)} errores")
    log.info("\n".join(lineas))


def aplicar(
    project_dir: str | Path,
    track_text_id: str | None = None,
    timeline_id: str | None = None,
) -> dict | None:
    """FASE B + C + D sobre el `draft_content.json` YA escrito.

    Centra el texto de los bloques de subt??tulo con keyword y oculta la imagen
    que hay debajo. Escribe el JSON en la ra??z y en `Timelines/<id>/` (CapCut lee
    ambos) y **verifica el resultado ley??ndolo de nuevo desde disco**. Devuelve
    el `content` resultante, o `None` si el proyecto no tiene subt??tulos."""
    raiz = Path(project_dir)
    destino = raiz / CONTENT_JSON
    if not destino.is_file():
        log.info("[imagina-esto] no hay %s en %s; se omite el post-proceso.",
                 CONTENT_JSON, raiz)
        return None

    content = json.loads(destino.read_text(encoding="utf-8"))
    bloques_ = bloques(content, track_text_id)
    if not bloques_:
        log.info("[imagina-esto] sin bloques de subt??tulo; se omite el post-proceso.")
        return None
    _marcar(bloques_)

    # D.2: ocultar la imagen (por bloque, en orden temporal).
    for b in bloques_:
        if b.afectado:
            b.ocultos = ocultar_rango(content, b.start_us, b.end_us)

    # D.1: centrar el texto de los bloques afectados.
    segmentos_text = {
        seg.get("material_id"): seg
        for pista in _pistas_text(content, track_text_id)
        for seg in (pista.get("segments") or [])
    }
    for b in bloques_:
        if b.afectado and b.material_id in segmentos_text:
            centrar_segmento(segmentos_text[b.material_id])

    destinos = [destino]
    if timeline_id:
        copia = raiz / "Timelines" / timeline_id / CONTENT_JSON
        if copia.is_file():
            destinos.append(copia)
    for path in destinos:
        _escribir(path, content)

    # D.3: se verifica SIEMPRE sobre lo escrito, ley??ndolo de nuevo de disco.
    errores: list[str] = []
    for path in destinos:
        donde = "<raiz>" if path == destino else "Timelines/" + str(timeline_id)
        errores += [f"{donde}: {e}" for e in
                    _verificar(path, bloques_, track_text_id)]
    for b in bloques_:
        prefijo = f"bloque {b.idx}: "
        b.ocultos_ok = not any(
            e.startswith(prefijo) or f": {prefijo}" in e for e in errores)
    _log_resumen(bloques_, errores)
    if errores:
        raise ImaginaEstoError(
            f"'imagina esto': la verificaci??n del draft fall?? "
            f"({len(errores)} error(es)); el proyecto NO se cierra.\n"
            + "\n".join(errores))
    return content
