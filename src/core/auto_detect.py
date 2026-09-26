"""Deteccion inteligente de los inputs de un video (100% sin dependencia de UI).

Escanee una carpeta raiz y devuelve un :class:`DetectionResult` con:

- El audio mas probable (nombre + tamano).
- El .txt de escenas valido (patron ``ESCENA #`` + ``VOZ EN OFF:``).
- La carpeta de imagenes correcta (raiz o primera subcarpeta con >= 2 imagenes).

Toda decision tomada se registra en ``warnings`` para que la UI pueda
mostrarla. Recibe una ruta, devuelve un dataclass: testeable en aislamiento.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.core import config

log = logging.getLogger("capcutauto")

_SCENE_RE = re.compile(r"ESCENA\s*#", re.IGNORECASE)
_VOICE_RE = re.compile(r"VOZ\s+EN\s+OFF\s*:", re.IGNORECASE)
_AUDIO_HINT_RE = re.compile(r"(guion|voz|voice|narration|locucion|narra)", re.IGNORECASE)
_AUDIO_EXCLUDE_RE = re.compile(r"(musica|music|bgm|background)", re.IGNORECASE)
_SCENE_NAME_RE = re.compile(r"(escena|scene|guion|script)", re.IGNORECASE)

_HEAD_LINES = 200
_MIN_IMAGES = 2
_SCORE_TIE_RANGE = 2


@dataclass
class DetectionResult:
    audio_path: Path | None = None
    scene_txt_path: Path | None = None
    images_dir: Path | None = None
    image_paths: list[Path] = field(default_factory=list)
    scene_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return (
            self.audio_path is not None
            and self.scene_txt_path is not None
            and bool(self.image_paths)
        )

    @property
    def image_scene_mismatch(self) -> bool:
        return bool(self.image_paths) and self.scene_count != len(self.image_paths)


def natural_sort_key(path: Path) -> list:
    """Clave de orden natural: ``2.jpg`` < ``10.jpg``."""
    return [
        (1, int(part)) if part.isdigit() else (0, part.lower())
        for part in re.split(r"(\d+)", path.name)
    ]


# ---------------------------------------------------------------------------
# Auxiliares internos
# ---------------------------------------------------------------------------
def _scan_txt_head(path: Path) -> tuple[bool, int]:
    """Valida las primeras lineas: >= 2 'ESCENA #' y al menos 1 'VOZ EN OFF:'."""
    scene_hits = 0
    has_voice = False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for _ in range(_HEAD_LINES):
                line = fh.readline()
                if not line:
                    break
                if _SCENE_RE.search(line):
                    scene_hits += 1
                elif _VOICE_RE.search(line):
                    has_voice = True
    except OSError as exc:
        log.warning("No se pudo leer %s para validar escenas (%s)", path, exc)
        return False, 0
    return scene_hits >= 2 and has_voice, scene_hits


def _count_scenes(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return len(_SCENE_RE.findall(text))


def _collect_images(folder: Path) -> list[Path]:
    try:
        children = folder.iterdir()
    except OSError:
        return []
    images = [
        p for p in children
        if p.is_file() and p.suffix.lower() in config.IMAGE_EXTENSIONS
    ]
    return sorted(images, key=natural_sort_key)


def _file_size_mb(path: Path) -> int:
    try:
        return round(path.stat().st_size / (1024 * 1024))
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Detecciones individuales
# ---------------------------------------------------------------------------
def _detect_audio(root: Path, warnings: list[str]) -> Path | None:
    candidates: list[Path] = []
    excluded: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() not in config.AUDIO_EXTENSIONS:
            continue
        if p.is_file() and _AUDIO_EXCLUDE_RE.search(p.name):
            excluded.append(p)
            continue
        if p.is_file():
            candidates.append(p)

    if not candidates:
        warnings.append("No se encontró ningún archivo de audio válido "
                        "(.wav/.mp3/.m4a/.aac/.flac/.ogg).")
        return None

    scored: list[tuple[int, Path]] = []
    for p in candidates:
        score = 3 if _AUDIO_HINT_RE.search(p.stem) else 0
        score += min(_file_size_mb(p), 10)
        scored.append((score, p))

    scored.sort(key=lambda entry: (entry[0], entry[1].name.lower()), reverse=True)
    best_score, best = scored[0]
    descartados = ", ".join(p.name for s, p in scored[1:]) if len(scored) > 1 else "—"
    excl = ", ".join(p.name for p in excluded) if excluded else "—"
    warnings.append(f"Audio elegido: {best.name} (score {best_score}) — "
                    f"descartados: {descartados} — excluidos por nombre: {excl}")
    return best


def _detect_scenes_txt(
    root: Path,
    warnings: list[str],
    ask_scene: Callable[[list[Path]], Path | None] | None,
) -> tuple[Path | None, int]:
    valid: list[Path] = []
    for p in root.rglob("*.txt"):
        if not p.is_file():
            continue
        ok, _ = _scan_txt_head(p)
        if ok:
            valid.append(p)

    if not valid:
        warnings.append("No se encontró ningún .txt de escenas válido "
                        "(debe contener 'ESCENA #' y 'VOZ EN OFF:').")
        return None, 0

    scored: list[tuple[int, float, Path, int]] = []
    for p in valid:
        count = _count_scenes(p)
        score = 5 if _SCENE_NAME_RE.search(p.stem) else 0
        score += count // 10
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        scored.append((score, mtime, p, count))

    scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    top_score, _mtime, best, best_count = scored[0]

    similares = [entry for entry in scored if top_score - entry[0] <= _SCORE_TIE_RANGE]
    chosen, chosen_count = best, best_count
    if len(similares) > 1 and ask_scene is not None:
        candidates = [entry[2] for entry in similares]
        picked = ask_scene(candidates)
        if picked is not None:
            chosen = picked
            chosen_count = _count_scenes(chosen)
            warnings.append(
                "El usuario eligió el archivo de escenas: "
                f"{chosen.name} ({chosen_count} escenas)."
            )
            return chosen, chosen_count

    warnings.append(
        f"Archivo de escenas elegido: {best.name} "
        f"({best_count} escenas, score {top_score})."
    )
    if len(similares) > 1:
        warnings.append(
            "Varios .txt de escenas con puntaje similar; se tomó el mejor "
            f"({best.name})."
        )
    return best, best_count


def _detect_images(root: Path, warnings: list[str]) -> tuple[Path | None, list[Path]]:
    root_images = _collect_images(root)
    if len(root_images) >= _MIN_IMAGES:
        warnings.append(f"Carpeta de imágenes: {root.name} (raíz, "
                        f"{len(root_images)} archivos).")
        return root, root_images

    try:
        subfolders = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        subfolders = []
    for sub in sorted(subfolders, key=lambda d: d.name.lower()):
        images = _collect_images(sub)
        if len(images) >= _MIN_IMAGES:
            warnings.append(f"Carpeta de imágenes: {sub.name} "
                            f"({len(images)} archivos).")
            return sub, images

    warnings.append("No se encontró carpeta de imágenes "
                    "(raíz o primera subcarpeta con ≥ 2 .jpg/.jpeg/.png/.webp).")
    return None, []


def detect_audios(video_dir: str | Path) -> dict:
    """Escanea audios en video_dir y devuelve {"guion": path|None, "otros": [paths]}."""
    video_dir = Path(video_dir)
    if not video_dir.is_dir():
        return {"guion": None, "otros": []}

    audios = [p for p in video_dir.iterdir()
              if p.suffix.lower() in config.AUDIO_EXTENSIONS]

    guion = None
    # 1. Buscar "guion"
    for p in audios:
        if _AUDIO_HINT_RE.search(p.name):
            guion = p
            break
    
    # 2. Si no hay guion, buscar el primer .wav
    if not guion:
        wavs = [p for p in audios if p.suffix.lower() == ".wav"]
        if wavs:
            guion = wavs[0]

    otros = [p for p in audios if p != guion]
    return {"guion": guion, "otros": otros}
def detect_video_inputs(
    root: str | Path,
    ask_scene: Callable[[list[Path]], Path | None] | None = None,
) -> DetectionResult:
    """Detecta audio / escenas / imagenes bajo ``root``.

    ``ask_scene`` (opcional) recibe la lista de candidatos con puntaje similar
    y devuelve el elegido (o None para usar el mejor por heuristica).
    """
    root = Path(root)
    warnings: list[str] = []
    if not root.is_dir():
        warnings.append(f"La carpeta de video no existe: {root}")
        return DetectionResult(warnings=warnings)

    audio = _detect_audio(root, warnings)
    scene_txt, scene_count = _detect_scenes_txt(root, warnings, ask_scene)
    images_dir, image_paths = _detect_images(root, warnings)

    if image_paths and scene_count != len(image_paths):
        warnings.append(
            f"Las imágenes ({len(image_paths)}) no coinciden con las escenas "
            f"({scene_count})."
        )

    return DetectionResult(
        audio_path=audio,
        scene_txt_path=scene_txt,
        images_dir=images_dir,
        image_paths=image_paths,
        scene_count=scene_count,
        warnings=warnings,
    )


def detect_audios(video_dir: str | Path) -> dict:
    """Escanea audios en video_dir de forma recursiva y devuelve {"guion": path|None, "otros": [paths]}."""
    video_dir = Path(video_dir)
    if not video_dir.is_dir():
        return {"guion": None, "otros": []}

    audios = [
        p for p in video_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in config.AUDIO_EXTENSIONS
    ]
    audios = sorted(audios, key=natural_sort_key)

    guion = None
    # 1. Buscar "guion"
    for p in audios:
        name_norm = "".join(
            c for c in unicodedata.normalize("NFKD", p.stem.lower())
            if not unicodedata.combining(c)
        )
        if "guion" in name_norm:
            guion = p
            break

    # 2. Si no hay guion, el primer .wav encontrado
    if not guion:
        for p in audios:
            if p.suffix.lower() == ".wav":
                guion = p
                break

    # 3. Si no hay .wav, el primer audio por orden natural
    if not guion and audios:
        guion = audios[0]

    otros = [p for p in audios if p != guion]
    return {"guion": guion, "otros": otros}


def find_capcut_templates(drafts_dir: str | Path) -> list[Path]:
    """Subcarpetas que contienen a la vez draft_content.json y draft_meta_info.json."""
    drafts_dir = Path(drafts_dir)
    if not drafts_dir.is_dir():
        return []
    templates = [
        d for d in drafts_dir.iterdir()
        if d.is_dir()
        and (d / config.DRAFT_CONTENT_FILE).is_file()
        and (d / config.DRAFT_META_FILE).is_file()
    ]
    return sorted(templates, key=natural_sort_key)