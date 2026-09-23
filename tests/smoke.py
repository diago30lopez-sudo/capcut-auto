"""Prueba de humo: genera un proyecto CapCut completo SIN abrir la UI.

Genera una plantilla y unos medios sinteticos que imitan la estructura de un
draft_content.json real de CapCut y deja el esquema volcado en
logs/schema_plantilla.json.
"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
import wave
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.core.capcut_project import CapCutProject  # noqa: E402
from src.core.scene_parser import parse_scenes  # noqa: E402
from src.core.timeline_builder import build_timeline  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
config.ensure_dirs()
WORK = Path(tempfile.mkdtemp(prefix="capcutauto_smoke_"))


def make_wav(path: Path, freq: int = 440, secs: float = 2.0) -> None:
    rate = 16000
    n = int(secs * rate)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        data = b"".join(
            struct.pack("<h", int(32000 * ((i % rate) / rate))) for i in range(n)
        )
        w.writeframes(data)


def make_template(folder: Path, model: bool = False) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    photo = {
        "type": "photo",
        "id": "AAAA".ljust(32, "A"),
        "path": "img/plantilla.png",
        "width": 1080,
        "height": 1080,
        "duration": 0,
        "material_name": "plantilla",
        "extra_info": {},
    }
    photo_seg = {
        "id": "SEGC1".ljust(32, "C"),
        "material_id": photo["id"],
        "target_timerange": {"start": 0, "duration": 2_000_000},
        "source_timerange": {"start": 0, "duration": 2_000_000},
        "speed": 1,
        "visible": True,
        "audio_fade": {"type": "none", "duration": 0},
    }
    video_track = {
        "id": "TRACK1".ljust(32, "T"),
        "type": "video",
        "flag": 0,
        "segment": photo_seg,
    }
    audio_mat = {
        "type": "audio",
        "id": "AUD1".ljust(32, "A"),
        "path": "audio/molde.mp3",
        "duration": 0,
        "material_name": "molde",
    }
    audio_seg = {
        "id": "SEGA1".ljust(32, "A"),
        "material_id": audio_mat["id"],
        "target_timerange": {"start": 0, "duration": 2_000_000},
        "source_timerange": {"start": 0, "duration": 2_000_000},
        "speed": 1,
        "visible": True,
        "audio_fade": {"type": "none", "duration": 0},
    }
    audio_track = {
        "id": "TRACK2".ljust(32, "A"),
        "type": "audio",
        "flag": 0,
        "segment": audio_seg,
    }
    content = {
        "platform": 1,
        "materials": {
            "videos": [photo],
            "audios": [audio_mat],
            "texts": [],
            "stickers": [],
            "effects": [],
            "transitions": [],
        },
        "tracks": [video_track, audio_track],
        "ai_used_extract_image": "test",
    }
    (folder / "draft_content.json").write_text(
        json.dumps(content, ensure_ascii=False), encoding="utf-8"
    )
    meta = {
        "draft_id": "META".ljust(32, "M"),
        "draft_name": "Plantilla Sintetica",
        "draft_fold_path": folder.absolute().as_posix(),
        "draft_root_path": folder.absolute().parent.as_posix(),
        "tm_draft_create": 0,
        "tm_draft_modified": 0,
    }
    (folder / "draft_meta_info.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return folder


def main() -> None:
    # audio sintetico
    audio = WORK / "voz.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    make_wav(audio)

    # plantilla sintetica
    template = make_template(WORK / "PlantillaSintetica")
    scenes_txt = WORK / "escenas.txt"
    scenes_txt.write_text(
        "ESCENA #101\n"
        'VOZ EN OFF: "Hola mundo, esta es la primera frase"\n'
        "DURACIÓN ESTIMADA: 1 segundo\n"
        'BÚSQUEDA DE IMAGEN (Google/Pinterest): "hola mundo"'
        "\nNOTA: \"primera\"\n\n"
        "ESCENA #102\n"
        'VOZ EN OFF: "Hola mundo, esta es la segunda frase"\n'
        "DURACIÓN ESTIMADA: 1 segundo\n"
        'BÚSQUEDA DE IMAGEN (Google/Pinterest): "segunda"\n',
        encoding="utf-8",
    )

    scenes = parse_scenes(scenes_txt)
    srt = WORK / "alineacion.srt"
    srt.write_text(
        "1\n00:00:00,050 --> 00:00:01,000\nHola mundo, esta es la primera frase\n\n"
        "2\n00:00:01,100 --> 00:00:02,050\nHola mundo, esta es la segunda frase\n\n",
        encoding="utf-8",
    )
    images = WORK / "imagenes"
    images.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), (200, 40, 40)).save(images / "escena01.jpg")
    Image.new("RGB", (800, 600), (40, 200, 100)).save(images / "escena02.jpg")

    items, total_us = build_timeline(scenes, srt, sorted(images.glob("*.jpg")))
    print("items:", [(it.image_path.name, it.duration_us, it.segment_text) for it in items])

    project = CapCutProject(template)
    project.backup_originals()
    project.dump_schema()
    out = project.generate("ProyectoSmoke", items, audio, total_us, allow_test_names=True)
    print("GENERADO:", out)
    data = json.loads((out / "draft_content.json").read_text(encoding="utf-8"))
    print("videos:", len(data["materials"]["videos"]))
    print("tracks:", [(t.get("type"), len(t.get("segments") or [])) for t in data["tracks"]])
    print("schema_plantilla.json -> logs/schema_plantilla.json")


if __name__ == "__main__":
    main()
