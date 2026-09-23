"""Clonado y edicion de un proyecto plantilla de CapCut.

La plantilla del usuario es un esqueleto 100% vacio (tracks: [], materials: []
en draft_content.json y en Timelines/<id>/draft_content.json), asi que no hay
estructura que copiar. Este modulo usa las estructuras canonicas de
capcut_canonical.py (extraidas de un draft real del usuario que SI renderiza)
y adapta ids, rutas, timeranges y duraciones con el contenido generado.

Cambios recientes:
- El proyecto se crea en la carpeta PADRE de la plantilla (junto a ella), no en
  %LOCALAPPDATA%\\CapCut\\...
- Las pistas usan tracks[].segments = [ ... ] (array), como CapCut actual.
- El draft_content.json final es un superconjunto del de la plantilla: se hace
  deep-copy del original y solo se sobreescriben los campos que cambian.
- Se escribe el mismo contenido en la RAIZ y en Timelines/<timeline_id>/.
- Guardia anti-tests: nombres con prefijo Test/Smoke/Autosync/Tmp/_test solo
  con allow_test_names=True. Ademas, si el JSON resultante queda sin pistas o
  segmentos, se borra el proyecto y se lanza error.
- Escala 'cover' por imagen (cubre el lienzo sin deformar) + zoom final
  aleatorio x1.10/x1.15 vía keyframes reales (common_keyframes), relativos a
  clip.scale.
- Si la suma de duraciones de las imágenes es menor que el audio total, el
  excedente se reparte proporcionalmente entre TODAS las imágenes (nunca se
  estira la última) para terminar a la vez con el audio.
"""

from __future__ import annotations

import copy
import json
import logging
import random
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image

from src.core import capcut_canonical as canonical
from src.core import config
from src.core.timeline_builder import (
    GenerationCancelled,
    TimelineItem,
    measure_audio_duration_us,
    redistribute_gap,
)

log = logging.getLogger("capcutauto")

CONTENT_JSON = "draft_content.json"
META_JSON = "draft_meta_info.json"

# Prefijos reservados: un proyecto con estos prefijos solo se genera en tests.
TEST_NAME_PREFIXES = ("test", "smoke", "autosync", "tmp", "_test")

# Multiplicadores de zoom al final de cada imagen (nunca valores intermedios).
ZOOM_END_OPTIONS = (1.10, 1.15)
# Canvas por defecto si la plantilla no declara canvas_config.
CANVAS_FALLBACK = (1920, 1080)


class CapCutProjectError(Exception):
    pass


def is_test_name(name: str) -> bool:
    """True si el nombre del proyecto coincide con los prefijos reservados a tests."""
    low = (name or "").strip().lower()
    return any(low.startswith(p) for p in TEST_NAME_PREFIXES)


def new_id() -> str:
    """Id unico hexadecimal de 32 chars (formato usado por CapCut)."""
    return uuid.uuid4().hex.upper()


def _now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


def _image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as im:
            return im.width, im.height
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo leer dimensiones de %s (%s); default 1920x1080.", path, exc)
        return 1920, 1080


def _canvas_size(content: dict) -> tuple[int, int]:
    """Dimensiones del lienzo (canvas_config), con fallback 1920x1080."""
    cc = content.get("canvas_config") or {}
    try:
        w = int(cc.get("width") or CANVAS_FALLBACK[0])
        h = int(cc.get("height") or CANVAS_FALLBACK[1])
    except (TypeError, ValueError):
        w, h = CANVAS_FALLBACK
    return w, h


def _cover_scale(canvas_w: int, canvas_h: int, img_w: int, img_h: int) -> float:
    """Escala 'cover': cubre el lienzo completo sin deformar ni dejar bandas
    negras (el sobrante se recorta). Ambas == x == y: escala uniforme."""
    if img_w <= 0 or img_h <= 0:
        return 1.0
    return max(canvas_w / img_w, canvas_h / img_h)


def _zoom_keyframes(duration_us: int, mult: float) -> list[dict]:
    """Keyframes REALES de CapCut (mismo formato que el draft 0921) para animar
    la escala uniforme: valores RELATIVOS a clip.scale. 1.0 sin cambio; 'mult'
    al final de la duración de la imagen."""
    def _frame(t_us: int, value: float) -> dict:
        return {
            "id": new_id(),
            "curveType": "Line",
            "time_offset": t_us,
            "left_control": {"x": 0.0, "y": 0.0},
            "right_control": {"x": 0.0, "y": 0.0},
            "values": [value],
            "string_value": "",
            "graphID": "",
        }

    return [
        {
            "id": new_id(),
            "material_id": "",
            "property_type": "KFTypeScaleX",
            "keyframe_list": [_frame(0, 1.0), _frame(duration_us, mult)],
        },
        {
            "id": new_id(),
            "material_id": "",
            "property_type": "KFTypeScaleY",
            "keyframe_list": [_frame(0, 1.0), _frame(duration_us, mult)],
        },
    ]


# --------------------------------------------------------------------------
# Esquema / muestra (para logs/schema_plantilla.json y schema_plantilla_full.json)
# --------------------------------------------------------------------------
def _describe(value, depth: int = 0, max_depth: int = 3):
    if value is None:
        return {"tipo": "null"}
    if isinstance(value, bool):
        return {"tipo": "bool", "ejemplo": value}
    if isinstance(value, (int, float)):
        return {"tipo": type(value).__name__, "ejemplo": value}
    if isinstance(value, str):
        return {"tipo": "str", "longitud": len(value), "ejemplo": value[:80]}
    if isinstance(value, list):
        d: dict = {"tipo": "list", "longitud": len(value)}
        if value and depth < max_depth:
            d["elemento_0"] = _describe(value[0], depth + 1, max_depth)
        return d
    if isinstance(value, dict):
        if depth >= max_depth:
            return {"tipo": "object", "claves": sorted(value.keys())}
        return {
            "tipo": "object",
            "claves": {k: _describe(v, depth + 1, max_depth) for k, v in value.items()},
        }
    return {"tipo": type(value).__name__}


def _muestra(value, depth: int = 0):
    """Copia sanitizada (listas acotadas, strings acotados) para inspeccion."""
    if isinstance(value, dict):
        return {k: _muestra(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if depth > 3:
            return f"<lista de {len(value)} elementos>"
        body = [_muestra(v, depth + 1) for v in value[:2]]
        if len(value) > 2:
            body.append(f"... ({len(value) - 2} mas)")
        return body
    if isinstance(value, str):
        return value[:120]
    return value


# --------------------------------------------------------------------------
# Proyecto CapCut
# --------------------------------------------------------------------------
class CapCutProject:
    def __init__(self, template_dir: str | Path):
        self.template_dir = Path(template_dir)
        self.content_path = self.template_dir / CONTENT_JSON
        self.meta_path = self.template_dir / META_JSON
        if not self.content_path.is_file():
            raise CapCutProjectError(
                f"La plantilla no contiene {CONTENT_JSON}: {self.template_dir}"
            )
        if not self.meta_path.is_file():
            raise CapCutProjectError(
                f"La plantilla no contiene {META_JSON}: {self.template_dir}"
            )
        self.content = json.loads(self.content_path.read_text(encoding="utf-8"))
        self.meta = json.loads(self.meta_path.read_text(encoding="utf-8"))

    # -- backup + esquema ----------------------------------------------------
    def backup_originals(self) -> Path:
        """Copia los JSON originales de la plantilla a backups/<timestamp>/."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        bak_dir = config.BACKUPS_DIR / stamp
        bak_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.content_path, bak_dir / f"{CONTENT_JSON}.original")
        shutil.copy2(self.meta_path, bak_dir / f"{META_JSON}.original")
        log.info("Backup de la plantilla guardado en %s", bak_dir)
        return bak_dir

    def dump_schema(self) -> Path:
        """Vuelca esquema (profundidad 3) + muestra a logs/schema_plantilla.json."""
        return self.dump_schema_to(config.SCHEMA_FILE, max_depth=3, sample=True)

    def dump_full_schema(self) -> Path:
        """Vuelca esquema COMPLETO (todas las claves, hasta nivel 5) a
        logs/schema_plantilla_full.json."""
        return self.dump_schema_to(config.SCHEMA_FULL_FILE, max_depth=5, sample=False)

    def dump_schema_to(self, target: Path, max_depth: int, sample: bool) -> Path:
        config.ensure_dirs()
        payload = {
            "generado_el": datetime.now().isoformat(timespec="seconds"),
            "plantilla": self.template_dir.name,
            "profundidad_maxima": max_depth,
            "esquema": _describe(self.content, max_depth=max_depth),
        }
        if sample:
            payload["muestra"] = _muestra(self.content)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        log.info("Esquema de la plantilla volcado a %s", target)
        return target

    # -- helpers de construccion -------------------------------------------------
    def _timeline_id(self, content: dict) -> str | None:
        """Id del timeline raiz = content['id']; el mismo que nombra la carpeta
        Timelines/<id>/ (que CapCut tambien lee)."""
        return content.get("id") or None

    def _build_photo_material(self, content: dict, abs_path: str, width: int,
                              height: int, duration_us: int, name: str) -> dict:
        mat = copy.deepcopy(canonical.PHOTO_MATERIAL)
        mat["id"] = new_id()
        mat["path"] = abs_path
        mat["duration"] = duration_us
        mat["width"] = width
        mat["height"] = height
        mat["material_name"] = name
        return mat

    def _build_photo_segment(self, content: dict, mat_id: str, start_us: int,
                             duration_us: int, cover_scale: float = 1.0,
                             zoom_mult: float = 1.0) -> dict:
        seg = copy.deepcopy(canonical.PHOTO_SEGMENT)
        seg["id"] = new_id()
        seg["material_id"] = mat_id
        seg["render_index"] = 0
        seg["track_render_index"] = 0
        seg["source_timerange"] = {"start": 0, "duration": duration_us}
        seg["target_timerange"] = {"start": start_us, "duration": duration_us}
        # Punto 2 y Tarea 2: ORDEN ESTRICTO DE OPERACIONES:
        # 1. Primero se aplica la escala 'cover' como escala base en clip.scale,
        #    asegurando que la imagen cubre toda la pantalla sin dejar bordes negros.
        seg["clip"]["scale"] = {"x": cover_scale, "y": cover_scale}
        seg["uniform_scale"] = {"on": True, "value": 1.0}
        # 2. Segundo, los keyframes de zoom (aumento del 10% o 15%) parten
        #    estrictamente de esa nueva escala base (keyframe inicial = 1.0 relativo
        #    a clip.scale, keyframe final = zoom_mult). Esto evita revelar los bordes.
        seg["common_keyframes"] = _zoom_keyframes(duration_us, zoom_mult)
        return seg

    def _build_audio_material(self, content: dict, abs_path: str,
                              duration_us: int, name: str) -> dict:
        mat = copy.deepcopy(canonical.AUDIO_MATERIAL)
        mat["id"] = new_id()
        mat["music_id"] = str(uuid.uuid4())
        mat["local_material_id"] = str(uuid.uuid4())
        mat["path"] = abs_path
        mat["duration"] = duration_us
        mat["name"] = name
        return mat

    def _build_audio_segment(self, content: dict, mat_id: str,
                             duration_us: int, track_index: int) -> dict:
        seg = copy.deepcopy(canonical.AUDIO_SEGMENT)
        seg["id"] = new_id()
        seg["material_id"] = mat_id
        seg["render_index"] = 0
        seg["track_render_index"] = track_index
        seg["source_timerange"] = {"start": 0, "duration": duration_us}
        seg["target_timerange"] = {"start": 0, "duration": duration_us}
        return seg

    # -- generacion ----------------------------------------------------------
    def generate(
        self,
        project_name: str,
        items: list[TimelineItem],
        audio_path: str | Path,
        audio_duration_us: int,
        cancel_event: threading.Event | None = None,
        allow_test_names: bool = False,
    ) -> Path:
        project_name = project_name.strip()
        if not project_name:
            raise CapCutProjectError("El nombre del proyecto no puede estar vacío.")
        if is_test_name(project_name) and not allow_test_names:
            raise CapCutProjectError(
                f"El nombre '{project_name}' coincide con los prefijos de pruebas "
                f"{TEST_NAME_PREFIXES}. Genera con allow_test_names=True solo en tests."
            )

        # BUG 2: el proyecto se crea en la carpeta PADRE de la plantilla
        base = self.template_dir.parent
        base.mkdir(parents=True, exist_ok=True)
        new_dir = base / project_name
        if new_dir.exists():
            raise CapCutProjectError(
                f"Ya existe un proyecto llamado '{project_name}' en {base}"
            )

        def _check_cancelled() -> None:
            if cancel_event is not None and cancel_event.is_set():
                log.info("Generación cancelada por el usuario.")
                shutil.rmtree(new_dir, ignore_errors=True)
                raise GenerationCancelled("Generación cancelada por el usuario.")

        _check_cancelled()

        # 1) clonado de la plantilla
        log.info("Proyecto se creará en: %s", new_dir)
        shutil.copytree(self.template_dir, new_dir)
        _check_cancelled()

        # 2) deep-copy: el JSON final es superconjunto del de la plantilla
        content = copy.deepcopy(self.content)
        materials = content.setdefault("materials", {})

        audio_src = Path(audio_path)

        audio_duration_us = max(int(audio_duration_us), 0)
        if audio_duration_us <= 0:
            audio_duration_us = max((it.end_us for it in items), default=1_000_000)
        target_us = audio_duration_us

        # Duración REAL del archivo (WAV): si hay silencio final los cues pueden
        # quedarse cortos; el video y el audio deben terminar a la vez.
        measured_us = measure_audio_duration_us(audio_src)
        if measured_us is not None:
            target_us = max(measured_us, audio_duration_us)

        # Punto 5: si la suma de duraciones de las imágenes es menor que el
        # audio total, reparte el excedente proporcionalmente entre TODAS (nunca
        # estira solo la última). Entra una sola vez, antes de crear segmentos.
        items = redistribute_gap(items, target_us)

        canvas_w, canvas_h = _canvas_size(content)

        # 3) materials.videos (fotos) + segments de la pista de video.
        #    Se referencian las rutas ABSOLUTAS de los archivos fuente (mismo
        #    formato que el draft real 0921: D:/.../escenas 2/xxx.jpg), nunca
        #    rutas relativas que CapCut no resuelve y muestra como "Media Not Found".
        photo_materials: list[dict] = []
        video_segments: list[dict] = []
        prev_end = 0
        for it in items:
            _check_cancelled()
            if it.image_path is None:
                log.warning("Escena %d sin imagen; se omite material.", it.order)
                continue

            # Evita segmentos de duracion 0 (CapCut no muestra bien 0 us)
            start_us = it.start_us if it.duration_us > 0 else prev_end
            duration_us = it.duration_us if it.duration_us > 0 else 1_000_000
            prev_end = start_us + duration_us

            width, height = _image_size(it.image_path)
            abs_path = it.image_path.resolve().as_posix()

            # Punto 2: escala 'cover' por imagen (cubre el lienzo sin deformar).
            cover_scale = _cover_scale(canvas_w, canvas_h, width, height)
            # Punto 3: zoom aleatorio por imagen (10% o 15%) al final de la misma.
            zoom_mult = random.choice(ZOOM_END_OPTIONS)

            mat = self._build_photo_material(
                content, abs_path, width, height, duration_us, it.image_path.stem)
            photo_materials.append(mat)
            video_segments.append(
                self._build_photo_segment(
                    content, mat["id"], start_us, duration_us, cover_scale, zoom_mult))

        # 4) materials.audios + pista de audio (ruta absoluta, sin recortar)
        audio_mat = self._build_audio_material(
            content, audio_src.resolve().as_posix(), target_us, audio_src.stem)
        audio_seg = self._build_audio_segment(content, audio_mat["id"],
                                              target_us, track_index=1)

        # materials: mantener TODAS las claves de la plantilla, remplazando
        # videos/audios y vaciando el resto (presentes en el esqueleto como []).
        for key in materials:
            if key in ("videos", "audios"):
                continue
            if isinstance(materials[key], list):
                materials[key] = []
        materials["videos"] = photo_materials
        materials["audios"] = [audio_mat]

        # 5) tracks: solo video(fotos) + audio generados
        video_track = copy.deepcopy(canonical.VIDEO_TRACK)
        video_track["id"] = new_id()
        video_track["segments"] = video_segments
        audio_track = copy.deepcopy(canonical.AUDIO_TRACK)
        audio_track["id"] = new_id()
        audio_track["segments"] = [audio_seg]
        content["tracks"] = [video_track, audio_track]

        # 6) duración raiz = duración total del audio (real del archivo si existe)
        content["duration"] = target_us
        content["update_time"] = _now_ms()

        # 7) escribir JSON en RAÍZ y en Timelines/<id>/ (CapCut lee ambos)
        _check_cancelled()
        self._write_draft_content(new_dir, content)

        # 8) draft_meta_info.json (rutas coherentes con la carpeta padre)
        _check_cancelled()
        meta = copy.deepcopy(self.meta)
        now_ms = _now_ms()
        meta["draft_id"] = str(uuid.uuid4())
        meta["draft_name"] = project_name
        meta["draft_fold_path"] = new_dir.as_posix()
        meta["draft_root_path"] = base.as_posix()
        meta["tm_draft_create"] = now_ms
        meta["tm_draft_modified"] = now_ms
        for k in ("tm_draft_last_modified", "tm_draft_last_open"):
            if k in meta:
                meta[k] = now_ms
        (new_dir / META_JSON).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 9) validacion post-generacion: nunca dejar un proyecto vacío
        _check_cancelled()
        final = json.loads((new_dir / CONTENT_JSON).read_text(encoding="utf-8"))
        n_tracks = len(final.get("tracks") or [])
        n_segments = sum(
            len(t.get("segments") or []) for t in (final.get("tracks") or [])
        )
        if n_tracks == 0 or n_segments == 0:
            shutil.rmtree(new_dir, ignore_errors=True)
            raise CapCutProjectError(
                "Proyecto generado vacío (sin pistas o sin segmentos); se eliminó."
            )
        log.info("Proyecto generado con %d pistas / %d segmentos.",
                 n_tracks, n_segments)

        # 10) copia del JSON generado a backups para inspeccion + esquema full
        try:
            self.dump_full_schema()
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo volcar schema_plantilla_full.json (%s)", exc)
        try:
            bak = self.backup_originals()
            shutil.copy2(new_dir / CONTENT_JSON, bak / f"{CONTENT_JSON}.generado")
            shutil.copy2(new_dir / META_JSON, bak / f"{META_JSON}.generado")
        except Exception as exc:  # noqa: BLE001 - copia de inspeccion no critica
            log.warning("No se pudo copiar JSON generado a backups (%s)", exc)

        log.info("PROYECTO GENERADO: %s", new_dir)
        return new_dir

    def _write_draft_content(self, project_dir: Path, content: dict) -> None:
        """Escribe draft_content.json en la raiz y en Timelines/<id>/ (si existe)."""
        text = json.dumps(content, ensure_ascii=False, indent=2)
        (project_dir / CONTENT_JSON).write_text(text, encoding="utf-8")
        timeline_id = self._timeline_id(content)
        if timeline_id:
            tdir = project_dir / "Timelines" / timeline_id
            if tdir.is_dir():
                (tdir / CONTENT_JSON).write_text(text, encoding="utf-8")
                log.info("draft_content.json escrito también en %s", tdir)
        log.info("draft_content.json generado con %d pistas de foto + 1 de audio.",
                 len(content.get("tracks") or []))