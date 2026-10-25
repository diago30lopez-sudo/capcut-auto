r"""Parser ULTRA-flexible del .txt de escenas (formatos generados por IA).

Divide el archivo COMPLETO con una expresion regular robusta cada vez que
aparece una cabecera tipo ``ESCENA`` (caso-insensitivo, con/sin ``#``,
con/sin espacios, numeros con ceros a la izquierda). Funciona aunque todo
el guion este en una sola linea, con comillas, con ``Prompt Image``, etc.

Deteccion de cabecera: ``(?:ESCENA|Escena)\s*#?\s*(\d+)``
  - ``ESCENA #001``, ``Escena 1``, ``ESCENA#5``, ``escena #2``, etc.

Extraccion de la narracion para cada bloque:
  1. Busca ``VOZ EN OFF:`` (sin distinguir mayusculas/minusculas).
  2. Captura todo el texto tras los dos puntos hasta encontrar
     ``DURACIÓN``, ``Prompt Image`` o el final del bloque.
  3. Si no hay ``VOZ EN OFF:``, usa la primera frase/parrafo del bloque.
  4. Limpieza: elimina comillas dobles/simples y espacios sobrantes.

Tolerancia a fallos:
  - Si el archivo tiene 0 escenas pero contiene ``ESCENA``, se emite un
    log de ADVERTENCIA indicando exactamente que bloque fallo.

Devuelve una lista de :class:`Scene` con ``number`` y ``key_text``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("capcutauto")

# Cabecera de escena. Un solo grupo de captura (dígitos) para que re.split
# entregue de forma intercalada (numero, bloque, numero, bloque, ...).
_SCENE_SPLIT_RE = re.compile(r"(?:ESCENA|Escena)\s*#?\s*(\d+)", re.IGNORECASE)

# Marcador de narración: "VOZ EN OFF:" (con o sin espacios / puntos).
_VOICE_RE = re.compile(r"VOZ\s+EN\s+OFF\s*:?", re.IGNORECASE)

# Terminadores del texto de narración dentro del bloque.
_END_RE = re.compile(r"DURACION|DURACIÓN|Prompt\s*Image", re.IGNORECASE)

# Cualquier "ESCENA" sin número (para detectar archivos fallidos).
_SCENA_WORD_RE = re.compile(r"ESCENA", re.IGNORECASE)


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


def _clean(text: str) -> str:
    """Quita comillas dobles/simples y espacios en blanco sobrantes."""
    text = text.replace('"', "").replace("'", "")
    return text.strip()


def _extract_block_text(block: str) -> str:
    """Extrae la narracion limpia de un bloque de escena.

    Prioridad: 1) VOZ EN OFF: ... (hasta DURACIÓN / Prompt Image / fin).
               2) Primera frase/parrafo del bloque (formato sin VOZ EN OFF).
    """
    block = block.strip()
    if not block:
        return ""

    voice = _VOICE_RE.search(block)
    if voice:
        rest = block[voice.end():]
        terminator = _END_RE.search(rest)
        if terminator:
            rest = rest[:terminator.start()]
        cleaned = _clean(rest)
        if cleaned:
            return cleaned

    # Fallback: primera frase/parrafo del bloque (sin marcadores de campo).
    pre = _END_RE.split(block, maxsplit=1)[0]
    first = ""
    for line in pre.splitlines():
        line = line.strip()
        if line:
            first = line
            break
    # Quita la puntuación/separador que pueda quedar tras la cabecera
    # (p.ej. el ':' de "Escena 1: Hola mundo.").
    first = re.sub(r"^[\s:\._\-\)\]\*]+,?|^,", "", first)
    return _clean(first)


def parse_scenes(path: str | Path) -> list[Scene]:
    """Parsea el .txt de escenas con el formato de IA mas variado posible."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No se encuentra el archivo de escenas: {path}")

    text = path.read_text(encoding="utf-8", errors="replace")
    parts = re.split(_SCENE_SPLIT_RE, text)

    scenes: list[Scene] = []
    # parts[0] es el texto anterior a la primera "ESCENA" (no es una escena).
    # Cada cabecera aporta un par: (numero capturado, bloque posterior).
    for i in range(2, len(parts), 2):
        number = int(parts[i - 1])
        block = parts[i]
        key_text = _extract_block_text(block)
        scenes.append(Scene(number=number, voice=key_text))

    # Se descartan bloques sin narracion (por ejemplo una cabecera suelta al
    # final que no va seguida de texto) para no crear escenas fantasma.
    valid_scenes = [s for s in scenes if s.key_text.strip()]

    if not valid_scenes:
        name = path.name
        if _SCENA_WORD_RE.search(text):
            failed = (parts[0] if not scenes else parts[-1]).strip()
            log.warning(
                "Parser de escenas: se encontro 'ESCENA' en %s pero no se pudo "
                "parsear ninguna escena valida. Bloque que fallo (primeros 500 "
                "caracteres): %r",
                name, (failed or text)[:500],
            )
        raise ValueError(
            f"El archivo {name} no contiene ninguna escena reconocible. "
            "Se esperaba al menos una cabecera del tipo 'ESCENA #1' seguida de "
            "'VOZ EN OFF: ...'."
        )

    return valid_scenes
