"""Parser del archivo .txt de escenas (formato exportado de ChatGPT).

Soporta multiples formatos de cabecera de escena:
  - Estándar multi-línea:
      ESCENA #1
      VOZ EN OFF: "texto..."
  - Markdown bold en una sola linea:
      **ESCENA #1** VOZ EN OFF: "texto..."
  - Símbolos variados alrededor de la cabecera:
      ## ESCENA #1 ##
      >>> ESCENA 1 <<<
      [ESCENA #1]
      Escena 4:
      ESCENA 01
  - Case-insensitive, números con #/:/-/[ ], ceros a la izquierda.
  - Cabeceras alternativas: ESCENA, ESCENAS, VIDEO, CAPITULO, CAPITOL.

Reglas:
- Cada escena se identifica por una cabecera que contiene "ESCENA" + número.
- La frase clave es la línea VOZ EN OFF (texto entre comillas).
- La duración estimada (si aparece) se usa como respaldo en el fuzzy matching.
- Las escenas se ordenan por orden de aparición en el archivo, NO por número.
- Un archivo es válido si tiene AL MENOS 1 escena con VOZ EN OFF.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Caracteres permitidos alrededor de la cabecera (markdown, simbolos, etc.)
_HEADER_SYMS = r"*\s#:\-\[\]<>//_"

# Cabecera de escena: permite simbolos/markdown ANTES y DESPUES de la palabra clave.
# NO anclamos al final ($) porque la cabecera puede ir seguida de VOZ EN OFF en
# la misma linea (formato markdown single-line).
_SCENE_RE = re.compile(
    r"^\s*"
    r"[" + _HEADER_SYMS + r"]*"       # simbolos opcionales ANTES de la palabra
    r"(?:ESCENAS|ESCENA|VIDEO|CAPITUL[OÁ])"
    r"\s*[" + _HEADER_SYMS + r"]*\s*"  # simbolos opcionales entre palabra y numero
    r"(\d+)"
    r"\s*[" + _HEADER_SYMS + r"]*",     # simbolos opcionales DESPUES del numero
    re.IGNORECASE,
)

# VOZ EN OFF: captura texto entre comillas dobles o latinas.
_VOICE_RE = re.compile(
    r"VOZ\s+EN\s+OFF\s*:?\s*[\"„‟「」『』]"
    r"(.*?)"
    r"[\"„‟「」『』]",
    re.IGNORECASE | re.DOTALL,
)
# Sin comillas: fallback
_VOICE_NQ_RE = re.compile(
    r"VOZ\s+EN\s+OFF\s*:?\s*(\S(?:.*?)[^\s\"])",
    re.IGNORECASE | re.DOTALL,
)

# Campo clave:valor (DURACIÓN, BÚSQUEDA, NOTA, etc.)
_LINE_KEY_RE = re.compile(
    r"^(?P<key>[A-Za-zÁÉÍÓÚáéíóúÑñ\s]+?)"
    r"(?:\([^)]*\))?"
    r"\s*:\s*"
    r"(?P<value>.*)$",
    re.IGNORECASE,
)

# Comillas para extraer texto entre ellas.
_QUOTE_START = set('"„‟「」『』\'ʻ')
_QUOTE_END = set('"„‟「」『』\'\u2019')


def _extract_voice_inline(line: str) -> str:
    """Extrae VOZ EN OFF de una línea (con o sin comillas)."""
    m = _VOICE_RE.search(line)
    if m:
        return m.group(1).strip()
    m = _VOICE_NQ_RE.search(line)
    if m:
        return m.group(1).strip()
    # Buscar VOZ EN OFF: en el resto de la línea después de la cabecera
    idx = re.search(r"VOZ\s+EN\s+OFF\s*:", line, re.IGNORECASE)
    if idx:
        rest = line[idx.end():].strip()
        if rest and rest[0] in _QUOTE_START:
            rest = rest[1:]
        if rest and rest[-1] in _QUOTE_END:
            rest = rest[:-1]
        return rest.strip()
    return ""


def _decode_quoted(value: str) -> str:
    """Extrae el contenido entre comillas (ascii o latinas)."""
    value = value.strip()
    if value and value[0] in _QUOTE_START:
        value = value[1:]
    if value and value[-1] in _QUOTE_END:
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
        """Texto usado para el fuzzy matching contra la transcripción."""
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
    """Parsea el .txt de escenas en orden de aparición con formatos flexibles."""
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

        # Check for scene header (flexible: markdown, symbols, etc.)
        m = _SCENE_RE.match(line)
        if m:
            if current is not None:
                scenes.append(current)
            current = Scene(number=int(m.group(1)))
            # Check for VOZ EN OFF on the same line (after the header)
            voice_text = _extract_voice_inline(line)
            if voice_text:
                current.voice = voice_text
            continue

        if current is None:
            continue

        # Check for VOZ EN OFF anywhere in the line
        voice_text = _extract_voice_inline(line)
        if voice_text:
            current.voice = voice_text
            continue

        # Parse as line: "KEY: value"
        km = _LINE_KEY_RE.match(line)
        if not km:
            continue
        key = km.group("key").strip().lower()
        value = km.group("value").strip()

        role = _role(key)
        if role == "voice":
            current.voice = _decode_quoted(value)
        elif role == "duration":
            current.duration_estimated = _extract_duration(value)
        elif role == "search":
            current.search = _decode_quoted(value)
        elif role == "note":
            current.note = _decode_quoted(value)

    if current is not None:
        scenes.append(current)

    # Validate at least one valid scene with voice
    valid_scenes = [s for s in scenes if s.voice.strip()]
    if not valid_scenes:
        name = path.name if isinstance(path, Path) else "el archivo"
        raise ValueError(
            f"El archivo {name} no contiene ninguna escena reconocible. "
            "Se esperaba al menos una cabecera del tipo 'ESCENA #1' seguida de 'VOZ EN OFF: ...'."
        )

    return valid_scenes
