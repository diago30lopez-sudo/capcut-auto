"""Helpers sinteticos compartidos por los checks (sin tocar plantillas reales)."""

from __future__ import annotations

import json
import struct
import wave
from pathlib import Path


def make_synthetic_template(folder: Path) -> Path:
    """Crea una plantilla CapCut minima y realista en ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    photo_id = "AAAAAAAA000000000000000000000001"
    photo = {
        "type": "photo", "id": photo_id, "path": "img/plantilla.png",
        "width": 1080, "height": 1080, "duration": 1_000_000,
        "material_name": "plantilla", "extra_info": {},
    }
    photo_seg = {
        "id": "SSSSSSSS000000000000000000000001", "material_id": photo_id,
        "target_timerange": {"start": 0, "duration": 1_000_000},
        "source_timerange": {"start": 0, "duration": 1_000_000},
        "speed": 1, "visible": True, "audio_fade": {"type": "none", "duration": 0},
    }
    audio_id = "AAAAAAAA000000000000000000000002"
    audio_mat = {
        "type": "audio", "id": audio_id, "path": "audio/molde.wav",
        "duration": 1_000_000, "material_name": "molde",
    }
    audio_seg = {
        "id": "SSSSSSSS000000000000000000000002", "material_id": audio_id,
        "target_timerange": {"start": 0, "duration": 1_000_000},
        "source_timerange": {"start": 0, "duration": 1_000_000},
        "speed": 1, "visible": True, "audio_fade": {"type": "none", "duration": 0},
    }
    content = {
        "platform": 1,
        "materials": {
            "videos": [photo], "audios": [audio_mat], "texts": [], "stickers": [],
            "effects": [], "transitions": [],
        },
        "tracks": [
            {"id": "TTTTTTTT000000000000000000000001", "type": "video", "flag": 0,
             "segment": photo_seg},
            {"id": "TTTTTTTT000000000000000000000002", "type": "audio", "flag": 0,
             "segment": audio_seg},
        ],
    }
    (folder / "draft_content.json").write_text(
        json.dumps(content, ensure_ascii=False), encoding="utf-8")
    meta = {
        "draft_id": "MMMMMM00 00000000000000000000001",
        "draft_name": "Plantilla Sintetica",
        "draft_fold_path": folder.absolute().as_posix(),
        "draft_root_path": folder.absolute().parent.as_posix(),
        "tm_draft_create": 0, "tm_draft_modified": 0,
    }
    (folder / "draft_meta_info.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return folder


def make_wav(path: Path, secs: float = 1.0) -> Path:
    """WAV mono sintetico."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    n = int(secs * rate)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(8000 * ((i % rate) / rate))) for i in range(n)
        )
        w.writeframes(frames)
    return path