"""Checks de la logica de auto_detect + cancelacion, sin abrir la UI.

Ejecutar desde la raiz:
    & .venv\\Scripts\\python.exe tests\\auto_detect_check.py

Todo se sintetiza en un directorio temporal y no toca la plantilla real.
"""

from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.core.auto_detect import (  # noqa: E402
    detect_video_inputs,
    find_capcut_templates,
    natural_sort_key,
)
from src.core.capcut_project import CapCutProject  # noqa: E402
from src.core.config import load_user_config, save_user_config  # noqa: E402
from src.core.timeline_builder import GenerationCancelled, build_timeline  # noqa: E402

_FAIL = []
_PASS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _PASS
    if cond:
        _PASS += 1
        print(f"  ok  {name}")
    else:
        _FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


def _make_scene_txt(path: Path, scenes: int, voz: bool = True) -> None:
    lines: list[str] = []
    for n in range(1, scenes + 1):
        lines.append(f"ESCENA #{n}")
        lines.append(f'VOZ EN OFF: "Frase número {n} de la historia"')
        lines.append("DURACIÓN ESTIMADA: 2 segundos")
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) if voz else "\n".join(
            ["notas sueltas", "sin patron", "no escenas aqui"]
        ))


def test_natural_sort() -> None:
    print("[natural_sort_key]")
    t = tempfile.mkdtemp()
    names = ["10.jpg", "2.jpg", "1.jpg", "a2.png", "a10.png", "b1.webp"]
    paths = [Path(t) / n for n in names]
    ordered = [p.name for p in sorted(paths, key=natural_sort_key)]
    check("numeric order", ordered[:3] == ["1.jpg", "2.jpg", "10.jpg"], str(ordered))
    check("suffix order", ordered[3:] == ["a2.png", "a10.png", "b1.webp"], str(ordered))


def test_audio_detection() -> None:
    print("[audio]")
    t = Path(tempfile.mkdtemp())
    (t / "musica.mp3").write_bytes(b"x" * (30 * 1024 * 1024))
    (t / "guion.wav").write_bytes(b"x" * (12 * 1024 * 1024))
    (t / "trailer.aac").write_bytes(b"x" * (30 * 1024 * 1024))
    res = detect_video_inputs(t)
    check("audio=guion.wav", res.audio_path is not None and res.audio_path.name == "guion.wav",
          str(res.audio_path))
    check("musica descartada",
          any("musica.mp3" in w for w in res.warnings), "; ".join(res.warnings))


def test_scenes_detection() -> None:
    print("[escenas]")
    t = Path(tempfile.mkdtemp())
    _make_scene_txt(t / "escenas.txt", 25)
    _make_scene_txt(t / "notas.txt", 0, voz=False)
    res = detect_video_inputs(t)
    check("scenes=escenas.txt", res.scene_txt_path is not None and res.scene_txt_path.name == "escenas.txt",
          str(res.scene_txt_path))
    check("scene_count=25", res.scene_count == 25, str(res.scene_count))


def test_scene_ask_callback() -> None:
    print("[escenas empate -> ask]")
    t = Path(tempfile.mkdtemp())
    _make_scene_txt(t / "guion_a.txt", 3)
    _make_scene_txt(t / "guion_b.txt", 3)
    asked: list[list[Path]] = []

    def ask(candidates):
        asked.append(candidates)
        return [c for c in candidates if c.name == "guion_b.txt"][0]

    res = detect_video_inputs(t, ask_scene=ask)
    check("ask invocado", len(asked) == 1, str(len(asked)))
    check("elegido=guion_b.txt", res.scene_txt_path is not None and res.scene_txt_path.name == "guion_b.txt",
          str(res.scene_txt_path))
    check("decision en warnings", any("usuario eligió" in w for w in res.warnings),
          "; ".join(res.warnings))


def test_images_detection() -> None:
    print("[imagenes]")
    t = Path(tempfile.mkdtemp())
    (t / "escenas 2").mkdir()
    for n in [1, 2, 10]:
        Image_write((t / "escenas 2" / f"{n}.jpg"))
    res = detect_video_inputs(t)
    check("images_dir=escenas 2", res.images_dir is not None and res.images_dir.name == "escenas 2",
          str(res.images_dir))
    check("orden natural", [p.name for p in res.image_paths] == ["1.jpg", "2.jpg", "10.jpg"],
          str([p.name for p in res.image_paths]))

    t2 = Path(tempfile.mkdtemp())
    for n in [1, 2, 3]:
        Image_write(t2 / f"root_{n}.png")
    res2 = detect_video_inputs(t2)
    check("raiz usada si >=2", res2.images_dir == t2, str(res2.images_dir))


def test_cross_validation_warning() -> None:
    print("[validacion cruzada]")
    t = Path(tempfile.mkdtemp())
    _make_scene_txt(t / "escenas.txt", 2)
    (t / "imgs").mkdir()
    for n in [1, 2, 3, 4]:
        Image_write(t / "imgs" / f"{n}.jpg")
    res = detect_video_inputs(t)
    check("warning de desajuste", any("no coinciden" in w for w in res.warnings), "; ".join(res.warnings))
    check("image_scene_mismatch=True", res.image_scene_mismatch is True)
    check("no aborta", res.scene_txt_path is not None and len(res.image_paths) == 4)


def test_templates_finder() -> None:
    print("[plantillas]")
    t = Path(tempfile.mkdtemp())
    (t / "1.PLANTILLA").mkdir(parents=True)
    (t / "1.PLANTILLA" / config.DRAFT_CONTENT_FILE).write_text("{}", encoding="utf-8")
    (t / "1.PLANTILLA" / config.DRAFT_META_FILE).write_text("{}", encoding="utf-8")
    (t / "sin_meta").mkdir(parents=True)
    (t / "sin_meta" / config.DRAFT_CONTENT_FILE).write_text("{}", encoding="utf-8")
    templates = find_capcut_templates(t)
    check("solo 1.PLANTILLA", [p.name for p in templates] == ["1.PLANTILLA"], str(templates))


def test_user_config_roundtrip() -> None:
    print("[config_user.json]")
    import src.core.config as cfgmod
    orig = cfgmod.USER_CONFIG_FILE
    try:
        tmp = Path(tempfile.mkdtemp()) / "config_user.json"
        cfgmod.USER_CONFIG_FILE = tmp
        save_user_config({"capcut_drafts_dir": "D:/x/CapCut Drafts",
                          "last_template_name": "1.PLANTILLA",
                          "last_video_dir": "D:/y/VIDEO_1",
                          "clave_extra": "ignorada"})
        got = load_user_config()
        check("persiste drafts", got["capcut_drafts_dir"] == "D:/x/CapCut Drafts", str(got))
        check("persiste template", got["last_template_name"] == "1.PLANTILLA", str(got))
        check("persiste video", got["last_video_dir"] == "D:/y/VIDEO_1", str(got))
        check("ignora extra", "clave_extra" not in got, str(got))
    finally:
        cfgmod.USER_CONFIG_FILE = orig


def test_timeline_cancel() -> None:
    print("[cancel timeline]")
    from src.core.scene_parser import Scene
    scenes = [Scene(number=i, voice=f"frase numero {i}") for i in range(1, 6)]
    images = [Path(f"img{i}.jpg") for i in range(1, 6)]
    srt = Path(tempfile.mkdtemp()) / "align.srt"
    srt.write_text(
        "".join(
            f"{i}\n00:00:00,{i * 100:03d} --> 00:00:00,{i * 100 + 50:03d}\n"
            f"frase numero {i}\n\n"
            for i in range(1, 6)
        ),
        encoding="utf-8",
    )
    ev = threading.Event()
    ev.set()
    try:
        build_timeline(scenes, srt, images, cancel_event=ev)
        check("timeline lanza GenerationCancelled", False, "no lanzó")
    except GenerationCancelled:
        check("timeline lanza GenerationCancelled", True)


def test_generate_cancel_cleanup() -> None:
    print("[cancel generate -> cleanup]")
    from tests.build_helpers import make_synthetic_template, make_wav  # noqa: E402
    work = Path(tempfile.mkdtemp())
    template = make_synthetic_template(work / "plantilla")
    audio = make_wav(work / "audio.wav")
    original_content = (template / config.DRAFT_CONTENT_FILE).read_bytes()
    ev = threading.Event()
    ev.set()
    try:
        project = CapCutProject(template)
        project.generate("ProyectoCancel", [], audio, 1_000_000, cancel_event=ev)
        check("generate lanza GenerationCancelled", False, "no lanzó")
    except GenerationCancelled:
        check("generate lanza GenerationCancelled", True)

    leftover = work / "ProyectoCancel"
    check("carpeta a medias limpiada", not leftover.exists(), str(leftover))
    check("plantilla original intacta",
          (template / config.DRAFT_CONTENT_FILE).read_bytes() == original_content)


def Image_write(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (4, 4), (10, 20, 30)).save(str(path))


def main() -> None:
    config.ensure_dirs()
    tests = [
        test_natural_sort, test_audio_detection, test_scenes_detection,
        test_scene_ask_callback, test_images_detection, test_cross_validation_warning,
        test_templates_finder, test_user_config_roundtrip,
        test_timeline_cancel, test_generate_cancel_cleanup,
    ]
    for fn in tests:
        fn()

    print(f"\nRESULTADO: {_PASS} checks ok, {len(_FAIL)} fallos.")
    if _FAIL:
        print("FALLOS:", ", ".join(_FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()