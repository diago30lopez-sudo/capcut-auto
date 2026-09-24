"""Verifica las 3 partes de FASE 1 sobre el proyecto generado por smoke.py:

1. El volumen del audio SIEMPRE es exactamente 6.0 dB (lineal 10^(6/20)).
2. Cada segmento de foto lleva el color grading estático (KFTypeContrast,
   KFTypeTemperature, KFTypeHightLight, KFTypeVignetting) en common_keyframes.
3. El pool de transiciones incluye las 4 cinematográficas (Cross Dissolve,
   Fade to Black, Light Sweep II, Barrido con inclinación) y TRANSITION_RATIO
   sigue en 0.98.

Ejecutar desde la raiz con el Python del proyecto (ver run.bat / configuración
de Python 3.14 local) y tests/fase1_check.py.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.capcut_project import (  # noqa: E402
    AUDIO_GAIN_DB,
    AUDIO_GAIN_LINEAR,
    COLOR_GRADE,
    TRANSITION_RATIO,
    TRANSITIONS,
)


def _generate_mini_project() -> dict | None:
    """Genera un mini-proyecto real con CapCutProject.generate (fotos, audio y
    transiciones) y devuelve el contenido JSON final para poder validar los
    3 criterios de FASE 1 sobre el JSON que CapCut leerá de verdad."""
    try:
        import tempfile

        import PIL.Image
        from src.core import config
        from src.core.capcut_project import CapCutProject
        from src.core.scene_parser import parse_scenes
        from src.core.timeline_builder import build_timeline
        from smoke import make_template, make_wav

        config.ensure_dirs()
        work = Path(tempfile.mkdtemp(prefix="fase1_check_"))
        audio = work / "voz.wav"
        make_wav(audio)
        template = make_template(work / "Plantilla")

        scenes_txt = work / "escenas.txt"
        scenes_txt.write_text(
            "ESCENA #1\n"
            'VOZ EN OFF: "Primera frase"\n'
            "DURACIÓN ESTIMADA: 1 segundo\n"
            'BÚSQUEDA DE IMAGEN: "primera"\n\n'
            "ESCENA #2\n"
            'VOZ EN OFF: "Segunda frase"\n'
            "DURACIÓN ESTIMADA: 1 segundo\n"
            'BÚSQUEDA DE IMAGEN: "segunda"\n',
            encoding="utf-8",
        )
        srt = work / "alineacion.srt"
        srt.write_text(
            "1\n00:00:00,050 --> 00:00:01,000\nPrimera frase\n\n"
            "2\n00:00:01,100 --> 00:00:02,050\nSegunda frase\n\n",
            encoding="utf-8",
        )
        images = work / "imagenes"
        images.mkdir(parents=True, exist_ok=True)
        PIL.Image.new("RGB", (800, 600), (200, 40, 40)).save(images / "escena01.jpg")
        PIL.Image.new("RGB", (800, 600), (40, 200, 100)).save(images / "escena02.jpg")

        scenes = parse_scenes(scenes_txt)
        items, total_us = build_timeline(
            scenes, srt, sorted(images.glob("*.jpg")))
        project = CapCutProject(template)
        out = project.generate(
            "Fase1Check", items, audio, total_us, allow_test_names=True)
        return json.loads(
            (out / "draft_content.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reportar el fallo como error de check
        print("  ERROR al generar el proyecto de verificación:", exc)
        return None


def main() -> None:
    errors: list[str] = []

    # --- 1. Volumen 6.0 dB lineal -----------------------------------------
    expected = 10 ** (6 / 20)
    if not math.isclose(AUDIO_GAIN_DB, 6.0):
        errors.append(f"AUDIO_GAIN_DB={AUDIO_GAIN_DB} != 6.0")
    if not math.isclose(AUDIO_GAIN_LINEAR, expected):
        errors.append(f"AUDIO_GAIN_LINEAR={AUDIO_GAIN_LINEAR} != {expected}")

    # --- 2. Color grading (constantes documentadas en el modulo) ----------
    COLOR_KEYS = {"KFTypeContrast", "KFTypeTemperature",
                  "KFTypeHightLight", "KFTypeVignetting"}
    have = {k for k, _ in COLOR_GRADE}
    missing = COLOR_KEYS - have
    if missing:
        errors.append(f"COLOR_GRADE le faltan: {sorted(missing)}")
    if not (0 < dict(COLOR_GRADE)["KFTypeVignetting"] <= 1):
        errors.append("KFTypeVignetting fuera de rango 0..1")

    # --- 3. Transiciones cinematograficas en el pool ----------------------
    CINEMATIC = {
        "6724846004274729480",  # Cross Dissolve
        "6724239388189921806",  # Fade to Black
        "7224393850444321282",  # Light Leaks (Light Sweep II)
        "7563310372044983557",  # Whip Pan (Barrido con inclinación)
    }
    pool_ids = {t[0] for t in TRANSITIONS}
    missing_t = CINEMATIC - pool_ids
    if missing_t:
        errors.append(f"Transiciones cinematográficas ausentes: {sorted(missing_t)}")
    if not math.isclose(TRANSITION_RATIO, 0.98):
        errors.append(f"TRANSITION_RATIO={TRANSITION_RATIO} != 0.98")

    # --- 4. Estructura real generada por uno de los tests E2E -------------
    project = _generate_mini_project()
    if project is None:
        errors.append("No se pudo generar el proyecto de verificación")
    else:
        audio_segs = [
            t["segments"][0]
            for t in project.get("tracks", [])
            if t.get("type") == "audio" and t.get("segments")
        ]
        if not audio_segs:
            errors.append("Generación sin pista de audio")
        elif not math.isclose(audio_segs[0].get("volume", 0.0), expected, rel_tol=1e-6):
            errors.append(f"volume generado = {audio_segs[0].get('volume')} != 6dB")
        if not math.isclose(audio_segs[0].get("last_nonzero_volume", 0.0), expected, rel_tol=1e-6):
            errors.append("last_nonzero_volume no refleja 6dB")

        video_segs = [
            seg
            for t in project.get("tracks", [])
            if t.get("type") == "video"
            for seg in (t.get("segments") or [])
        ]
        seen: set[str] = set()
        for seg in video_segs:
            seen.update(
                kf.get("property_type", "")
                for kf in (seg.get("common_keyframes") or []))
        missing_in_json = {"KFTypeContrast", "KFTypeTemperature",
                           "KFTypeHightLight", "KFTypeVignetting"} - seen
        if missing_in_json:
            errors.append(f"Faltan keyframes de color en el JSON: {sorted(missing_in_json)}")

    if errors:
        print("FASE 1  KO")
        for e in errors:
            print("  -", e)
        raise SystemExit(1)
    print("FASE 1  OK  (audio 6.0 dB · color grading estático · 4 transiciones cinematográficas)")


if __name__ == "__main__":
    main()