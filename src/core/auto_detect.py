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
from src.core.config import load_user_config

log = logging.getLogger("capcutauto")

# ---------------------------------------------------------------------------
# Exclusion helpers (v1.7.0)
# ---------------------------------------------------------------------------
def _load_excluded_paths() -> list[Path]:
    """Carga las rutas excluidas desde config_user.json."""
    raw = load_user_config().get("excluded_paths", "")
    if isinstance(raw, str) and raw.strip():
        return [Path(p.strip()) for p in raw.split(",") if p.strip()]
    return []


def _is_excluded(path: Path, excluded: list[Path]) -> bool:
    """True si ``path`` coincide con alguna de las exclusiones (archivo o carpeta).
    Normaliza rutas con os.path.normcase + abspath para evitar problemas
    de mayúsculas/separadores en Windows."""
    import os
    if not excluded:
        return False
    norm_path = os.path.normcase(os.path.abspath(path))
    for exc in excluded:
        norm_exc = os.path.normcase(os.path.abspath(exc))
        # Excluir si es el mismo archivo
        if norm_path == norm_exc:
            return True
        # Excluir si está dentro de una carpeta excluida
        if norm_path.startswith(norm_exc + os.sep):
            return True
    return False

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
    video_paths: list[Path] = field(default_factory=list)
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
    def media_paths(self) -> list[Path]:
        """Imagenes y videos mezclados, ordenados naturalmente."""
        all_media = list(self.image_paths) + list(self.video_paths)
        return sorted(all_media, key=natural_sort_key)

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


def _collect_videos(folder: Path) -> list[Path]:
    try:
        children = folder.iterdir()
    except OSError:
        return []
    videos = [
        p for p in children
        if p.is_file() and p.suffix.lower() in config.VIDEO_EXTENSIONS
    ]
    return sorted(videos, key=natural_sort_key)


def _collect_media(folder: Path) -> tuple[list[Path], list[Path]]:
    """Devuelve (images, videos) en la carpeta dada."""
    images = _collect_images(folder)
    videos = _collect_videos(folder)
    return images, videos


def _file_size_mb(path: Path) -> int:
    try:
        return round(path.stat().st_size / (1024 * 1024))
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Detecciones individuales
# ---------------------------------------------------------------------------
def _detect_audio(root: Path, warnings: list[str]) -> Path | None:
    excluded = _load_excluded_paths()
    candidates: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() not in config.AUDIO_EXTENSIONS:
            continue
        if _is_excluded(p, excluded):
            continue
        if p.is_file() and _AUDIO_EXCLUDE_RE.search(p.name):
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
    excl_by_name = [p.name for p in root.rglob("*")
                     if p.is_file() and _AUDIO_EXCLUDE_RE.search(p.name)
                     and not _is_excluded(p, excluded)]
    excl_by_list = [p.name for p in root.rglob("*")
                     if _is_excluded(p, excluded)]
    excl_str = ", ".join(excl_by_name + excl_by_list) if (excl_by_name or excl_by_list) else "—"
    warnings.append(f"Audio elegido: {best.name} (score {best_score}) — "
                    f"descartados: {descartados} — excluidos por nombre: {excl_str}")
    return best


def _detect_scenes_txt(
    root: Path,
    warnings: list[str],
    ask_scene: Callable[[list[Path]], Path | None] | None,
) -> tuple[Path | None, int]:
    excluded = _load_excluded_paths()
    valid: list[Path] = []
    for p in root.rglob("*.txt"):
        if not p.is_file():
            continue
        if _is_excluded(p, excluded):
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


def _detect_images(root: Path, warnings: list[str]) -> tuple[Path | None, list[Path], list[Path]]:
    """Detecta imagenes y videos en root (raiz o primera subcarpeta con >= 2).

    Devuelve (dir, image_paths, video_paths).
    """
    excluded = _load_excluded_paths()

    def _filter(paths: list[Path]) -> list[Path]:
        if not excluded:
            return paths
        return [p for p in paths if not _is_excluded(p, excluded)]

    # Raiz
    root_images = _filter(_collect_images(root))
    root_videos = _filter(_collect_videos(root))
    if len(root_images) + len(root_videos) >= _MIN_IMAGES:
        warnings.append(f"Carpeta de imagenes: {root.name} (raiz, "
                        f"{len(root_images)} imgs + {len(root_videos)} vids).")
        return root, root_images, root_videos

    # Subcarpetas
    try:
        subfolders = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        subfolders = []
    for sub in sorted(subfolders, key=lambda d: d.name.lower()):
        images = _filter(_collect_images(sub))
        videos = _filter(_collect_videos(sub))
        if len(images) + len(videos) >= _MIN_IMAGES:
            warnings.append(f"Carpeta de imagenes: {sub.name} "
                            f"({len(images)} imgs + {len(videos)} vids).")
            return sub, images, videos

    warnings.append("No se encontro carpeta de imagenes "
                    "(raiz o primera subcarpeta con >= 2 .jpg/.mp4/etc.).")
    return None, [], []


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
    images_dir, image_paths, video_paths = _detect_images(root, warnings)

    all_media = list(image_paths) + list(video_paths)
    if all_media and scene_count != len(all_media):
        warnings.append(
            f"Los archivos multimedia ({len(all_media)}) no coinciden con las "
            f"escenas ({scene_count})."
        )

    return DetectionResult(
        audio_path=audio,
        scene_txt_path=scene_txt,
        images_dir=images_dir,
        image_paths=image_paths,
        video_paths=video_paths,
        scene_count=scene_count,
        warnings=warnings,
    )


def detect_audios(video_dir: str | Path) -> dict:
    """Escanea audios en video_dir de forma recursiva y devuelve {"guion": path|None, "otros": [paths]}."""
    video_dir = Path(video_dir)
    if not video_dir.is_dir():
        return {"guion": None, "otros": []}

    excluded = _load_excluded_paths()
    audios = [
        p for p in video_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in config.AUDIO_EXTENSIONS
        and not _is_excluded(p, excluded)
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


# ---------------------------------------------------------------------------
# v1.6.0 — Parser del archivo de estructura de sonidos
# ---------------------------------------------------------------------------
_SOUNDBLOCK_RE = re.compile(
    r"""
    ^\s*
    (?:SONIDO|SOUND|AUDIO)           # "SONIDO", "SOUND" o "AUDIO" (case-insensitive)
    [\s_\-]*                         # separadores opcionales
    (\d+)                            # número N
    [\s_\-]*                         # más separadores opcionales después del número
    (?:[—–-][^\n]*)?                 # separador con posible texto extra (opcional)
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

_VOLUME_RE = re.compile(
    r"volumen\s*:\s*"
    r"-?[\d.]+\s*db\s+(?:a|-)\s*-?[\d.]+\s*db",
    re.IGNORECASE,
)

_START_PHRASE_RE = re.compile(
    r"frase\s+de\s+inicio\s*:\s*(.+)",
    re.IGNORECASE,
)

_END_PHRASE_RE = re.compile(
    r"frase\s+de\s+fin\s*:\s*(.+)",
    re.IGNORECASE,
)


@dataclass
class SoundBlock:
    """Bloque SONIDO N extraido del archivo de estructura."""
    number: int
    volume_db_low: float           # volumen mas bajo (p.ej. -21 dB)
    volume_db_high: float          # volumen mas alto (p.ej. -17 dB)
    start_phrase: str              # frase de inicio exacta
    end_phrase: str                # frase de fin exacta


def _extract_volume_range(line: str) -> tuple[float, float] | None:
    m = _VOLUME_RE.search(line)
    if not m:
        return None
    nums = re.findall(r"-?[\d.]+", line[m.start():m.end()])
    if len(nums) < 2:
        return None
    try:
        a, b = float(nums[0]), float(nums[1])
        return (min(a, b), max(a, b))
    except ValueError:
        return None


def parse_sound_structure(text: str) -> list[SoundBlock]:
    """Parsea el texto de estructura de sonidos y devuelve los bloques encontrados.

    Cada bloque debe tener:
    - Un numero identificativo (SONIDO N, Sonido N, AUDIO N, sonido_N, etc.)
    - Una linea "Volumen: -X dB a -Y dB"
    - Una linea "Frase de inicio: ..."
    - Una linea "Frase de fin: ..."

    Si dos bloques tienen el mismo numero se lanza ValueError.
    Se ignoran campos como nombre, prompt, duracion y estilo.
    """
    lines = text.splitlines()
    blocks: list[SoundBlock] = []
    current: dict[str, object] | None = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # Check for new block header
        sm = _SOUNDBLOCK_RE.match(line)
        if sm:
            if current is not None and "number" in current:
                blocks.append(SoundBlock(
                    number=int(current["number"]),   # type: ignore[arg-type]
                    volume_db_low=float(current["vol_low"]),    # type: ignore[arg-type]
                    volume_db_high=float(current["vol_high"]),  # type: ignore[arg-type]
                    start_phrase=str(current["start_phrase"]),
                    end_phrase=str(current["end_phrase"]),
                ))
            current = {"number": int(sm.group(1)), "vol_low": 0.0, "vol_high": 0.0,
                       "start_phrase": "", "end_phrase": ""}
            continue

        if current is None:
            continue

        # Parse volumen
        vm = _extract_volume_range(line)
        if vm is not None:
            current["vol_low"] = vm[0]
            current["vol_high"] = vm[1]
            continue

        # Parse start phrase
        sp = _START_PHRASE_RE.search(line)
        if sp:
            current["start_phrase"] = sp.group(1).strip()
            continue

        # Parse end phrase
        ep = _END_PHRASE_RE.search(line)
        if ep:
            current["end_phrase"] = ep.group(1).strip()
            continue

    # Flush last block
    if current is not None and "number" in current:
        blocks.append(SoundBlock(
            number=int(current["number"]),   # type: ignore[arg-type]
            volume_db_low=float(current["vol_low"]),    # type: ignore[arg-type]
            volume_db_high=float(current["vol_high"]),  # type: ignore[arg-type]
            start_phrase=str(current["start_phrase"]),
            end_phrase=str(current["end_phrase"]),
        ))

    # Validate: no duplicate numbers
    seen: set[int] = set()
    for b in blocks:
        if b.number in seen:
            raise ValueError(f"bloque SONIDO {b.number} duplicado en la estructura")
        seen.add(b.number)

    return blocks


def find_sound_structure_file(root: Path) -> Path | None:
    """Busca un archivo .txt en root (y subcarpetas) que contenga al menos
    un bloque SONIDO N con 'Frase de inicio' y 'Frase de fin'.

    Devuelve la primera ruta valida encontrada (orden natural por nombre),
    o None si no se encuentra ninguno.
    """
    excluded = _load_excluded_paths()
    candidates: list[tuple[list, Path]] = []
    try:
        for p in root.rglob("*.txt"):
            if not p.is_file():
                continue
            if _is_excluded(p, excluded):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                blocks = parse_sound_structure(text)
                # Solo interesa si tiene al menos 1 bloque con ambas frases
                valid = [b for b in blocks if b.start_phrase and b.end_phrase]
                if valid:
                    candidates.append((natural_sort_key(p), p))
            except ValueError:
                continue
    except OSError:
        return None

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]