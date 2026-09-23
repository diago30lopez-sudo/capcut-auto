"""E2E real autorizado: descarga CrispASR + modelo y alinea el guion real.

Replica paso a paso el flujo de la app (sin UI): deteccion de entradas,
parseo de escenas, alineacion con CrispASR (1ª ejecucion: descarga bin/models),
timeline SRT y generacion del proyecto CapCut.

Ejecutar desde la raiz:
    & .venv\\Scripts\\python.exe -X utf8 tests\\fase2_e2e.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.core.auto_detect import detect_video_inputs  # noqa: E402
from src.core.capcut_project import CapCutProject  # noqa: E402
from src.core.scene_parser import parse_scenes  # noqa: E402
from src.core.timeline_builder import build_timeline, parse_srt  # noqa: E402
from src.core.transcriber import align_audio_to_text  # noqa: E402

DRAFTS = r"D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts"
TEMPLATE_NAME = "1.PLANTILLA"
VIDEO = r"D:\YOUTUBE AUTOMATIZADO\1.historias hipoteticas\VIDEO\VIDEO_1"
PROJECT_NAME = "AutosyncFase2_Test"


def main() -> None:
    config.ensure_dirs()
    print(f"bin  -> {config.BIN_DIR}")
    print(f"model-> {config.MODELS_DIR}")

    det = detect_video_inputs(Path(VIDEO))
    print(f"audio  : {det.audio_path}")
    print(f"escenas: {det.scene_txt_path} ({det.scene_count})")
    print(f"imagenes: {len(det.image_paths)}")
    if det.audio_path is None or det.scene_txt_path is None:
        raise SystemExit("deteccion incompleta")

    scenes = parse_scenes(det.scene_txt_path)
    lines = [s.key_text for s in scenes if s.key_text.strip()]
    print(f"escenas parseadas: {len(scenes)}; lineas con texto: {len(lines)}")

    srt_path = config.CACHE_DIR / f"alineacion_{Path(det.audio_path).stem}.srt"
    align_audio_to_text(det.audio_path, lines, srt_path)
    cues = parse_srt(srt_path)
    print(f"cues alineados: {len(cues)}")
    if cues:
        print("  1er cue:", cues[0])
        print("  ultimo cue:", cues[-1])

    items, total_us = build_timeline(scenes, srt_path, list(det.image_paths))
    synced = sum(1 for it in items if it.is_synced)
    print(f"timeline: {synced}/{len(items)} escenas sincronizadas; total {total_us} us")

    # BUG 2/3: el proyecto se genera en la carpeta PADRE de la plantilla; para que
    # el test no ensucie la carpeta real de drafts, se copia la plantilla real a un
    # directorio temporal y se genera ahi.
    work = Path(tempfile.mkdtemp(prefix="capcutauto_e2e_"))
    project = CapCutProject(shutil.copytree(Path(DRAFTS) / TEMPLATE_NAME, work / TEMPLATE_NAME))
    project.backup_originals()
    project.dump_schema()
    out = project.generate(PROJECT_NAME, items, det.audio_path, total_us,
                           allow_test_names=True)
    print(f"PROYECTO GENERADO: {out}")


if __name__ == "__main__":
    main()