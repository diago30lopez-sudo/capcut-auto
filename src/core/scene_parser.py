"""Parser del archivo .txt de escenas (formato exportado de ChatGPT).

Formato esperado por bloque:

    ESCENA #137
    VOZ EN OFF: "Ahora es mas rapido, mas fuerte, pero tambien mas humano que nunca."
    DURACION ESTIMADA: 4 segundos
    BUSQUEDA DE IMAGEN (Google/Pinterest): "..."
    NOTA: "..."

Reglas:
- Cada escena comienza por "ESCENA #<número>".
- La frase clave es la linea VOZ EN OFF (el texto entre comillas).
- La duracion estimada (si aparece) se usa como respaldo cuando el fuzzy
  matching no encuentra un segmento concreto en la transcripcion.
- Las escenas se ordenan por orden de aparicion en el archivo, NO por numero.

Este modulo solo usa caracteres ASCII en el codigo fuente (los caracteres
latinos como comillas se construyen con secuencias \\u...) para evitar
problemas de codificacion al leer el archivo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_DQ_L = "\u201c"
_DQ_R = "\u201d"
_SQ_L = "\u2018"
_SQ_R = "\u2019"
_OPEN = '["' + _DQ_L + _SQ_L
_CLOSE = '"]' + _DQ_R + _SQ_R

_LINE_KEY_RE = re.compile(
    r"^(?P<key>[A-Za-zÁÉÍÓÚáéíóúÑñ\s]+)\s*:\s*(?P<value>.*)$"
)
_SCENE_RE = re.compile(r"^\s*ESCENA\s+#\s*(\d+)\s*$", re.IGNORECASE)
_SQ_TEXT = re.compile(
    r"[\"" + _DQ_L + _SQ_L + r"](?P<body>.*?)[\"" + _DQ_R + _SQ_R + r"]"
)


def _decode_quoted(value: str) -> str:
    """Extrae el contenido entre las comillas (ascii o latinas)."""
    m = _SQ_TEXT.search(value)
    if m:
        return m.group("body").strip()
    value = value.strip()
    if value.startswith(("'", _SQ_L)):
        value = value[1:]
        if value.endswith(("'", _SQ_R)):
            value = value[:-1]
    return value.strip()


def _extract_duration(value: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)", value)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


@dataclass
class Scene:
    number: int
    voice: str = ""
    duration_estimated: float | None = None
    search: str = ""
    note: str = ""

    @property
    def key_text(self) -> str:
        """Texto usado para el fuzzy matching contra la transcripcion."""
        return (self.voice or self.note or self.search or "").strip()


def _role(key_lower: str) -> str:
    if any(tok in key_lower for tok in ("voz", "off", "voice")):
        return "voice"
    if any(tok in key_lower for tok in ("duras", "duration", "duracion")):
        return "duration"
    if any(tok in key_lower for tok in ("busqued", "imagen", "search")):
        return "search"
    if any(tok in key_lower for tok in ("nota", "note")):
        return "note"
    return ""


def parse_scenes(path: str | Path) -> list[Scene]:
    """Parsea el .txt de escenas en orden de aparicion."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No se encuentra el archivo de escenas: {path}")

    scenes: list[Scene] = []
    current: Scene | None = None

    text = path.read_text(encoding="utf-8", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        m = _SCENE_RE.match(line)
        if m:
            if current is not None:
                scenes.append(current)
            current = Scene(number=int(m.group(1)))
            continue

        if current is None:
            continue

        km = _LINE_KEY_RE.match(line)
        if not km:
            continue
        role = _role(km.group("key").strip().lower())
        value = km.group("value")

        if role == "voice":
            voice = _decode_quoted(value)
            current.voice = voice
        elif role == "duration":
            current.duration_estimated = _extract_duration(value)
        elif role == "search":
            current.search = _decode_quoted(value)
        elif role == "note":
            current.note = _decode_quoted(value)

    if current is not None:
        scenes.append(current)

    return scenes
