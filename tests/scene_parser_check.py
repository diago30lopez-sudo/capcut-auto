"""Test for the robust scene parser (BUG 2 fix).

Run: python tests/scene_parser_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.scene_parser import parse_scenes


def _write(tmp: Path, name: str, content: str) -> Path:
    p = tmp / name
    p.write_text(content, encoding="utf-8")
    return p


def main() -> None:
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="scene_test_"))
    failures = 0

    # 1. Standard multi-line
    p = _write(tmp, "std.txt", """
ESCENA #1
VOZ EN OFF: "Hello world one"
DURACIÓN ESTIMADA: 4 segundos
BÚSQUEDA DE IMAGEN: "Spider-Man"
NOTA: "first scene"

ESCENA #2
VOZ EN OFF: "Second voice"
DURACIÓN ESTIMADA: 6 segundos
BÚSQUEDA DE IMAGEN: "Iron Man"
NOTA: "second scene"
""")
    scenes = parse_scenes(p)
    assert len(scenes) == 2, f"Expected 2 scenes, got {len(scenes)}"
    assert scenes[0].number == 1
    assert scenes[1].number == 2
    assert "Hello world one" in scenes[0].voice
    assert "Second voice" in scenes[1].voice
    print("  OK: standard multi-line")

    # 2. Markdown bold single-line
    p = _write(tmp, "md.txt", """
**ESCENA #1** VOZ EN OFF: "Markdown bold voice" DURACIÓN ESTIMADA: 6 segundos BÚSQUEDA DE IMAGEN: "Captain America" NOTA: "md test"
**ESCENA #2** VOZ EN OFF: "Second line" DURACIÓN ESTIMADA: 3 segundos BÚSQUEDA DE IMAGEN: "Thor"
""")
    scenes = parse_scenes(p)
    assert len(scenes) == 2, f"Expected 2, got {len(scenes)}"
    assert "Markdown bold voice" in scenes[0].voice
    assert "Second line" in scenes[1].voice
    print("  OK: markdown bold single-line")

    # 3. Symbols around header
    p = _write(tmp, "sym.txt", """
## ESCENA #1 ##
VOZ EN OFF: "Symbol header"
>>> ESCENA 2 <<<
VOZ EN OFF: "Arrow header"
[ESCENA #3]
VOZ EN OFF: "Bracket header"
Escena 4:
VOZ EN OFF: "Plain colon header"
""")
    scenes = parse_scenes(p)
    assert len(scenes) == 4, f"Expected 4, got {len(scenes)}"
    print("  OK: symbols around header")

    # 4. Mixed formats
    p = _write(tmp, "mixed.txt", """
ESCENA #1
VOZ EN OFF: "First"

## ESCENA #2 ##
VOZ EN OFF: "Second"

**ESCENA #3** VOZ EN OFF: "Third" DURACIÓN ESTIMADA: 5 segundos
""")
    scenes = parse_scenes(p)
    assert len(scenes) == 3, f"Expected 3, got {len(scenes)}"
    print("  OK: mixed formats")

    # 5. Case-insensitive
    p = _write(tmp, "lower.txt", """
escena 1
VOZ EN OFF: "lowercase header"
escena 2
VOZ EN OFF: "second lower"
""")
    scenes = parse_scenes(p)
    assert len(scenes) == 2, f"Expected 2, got {len(scenes)}"
    print("  OK: case-insensitive")

    # 6. Arabic numbers with # / : / - / []
    p = _write(tmp, "nums.txt", """
ESCENA #137
VOZ EN OFF: "Arabic number"
ESCENA 1:
VOZ EN OFF: "colon header"
ESCENA 01
VOZ EN OFF: "zero-padded"
""")
    scenes = parse_scenes(p)
    assert len(scenes) == 3, f"Expected 3, got {len(scenes)}"
    print("  OK: arabic numbers with symbols")

    # 7. Empty / no scenes -> error message
    p = _write(tmp, "empty.txt", "This is not a scene file at all.")
    try:
        parse_scenes(p)
        print("  FAIL: expected ValueError for empty file")
        failures += 1
    except ValueError as e:
        msg = str(e)
        assert "no contiene ninguna escena reconocible" in msg, f"Unexpected error: {msg}"
        print("  OK: empty file raises clear error")

    # 8. File with header but no voice -> error
    p = _write(tmp, "no_voice.txt", """
ESCENA #1
DURACIÓN ESTIMADA: 4 segundos
BÚSQUEDA DE IMAGEN: "something"
""")
    try:
        parse_scenes(p)
        print("  FAIL: expected ValueError for header without voice")
        failures += 1
    except ValueError as e:
        msg = str(e)
        assert "no contiene ninguna escena reconocible" in msg, f"Unexpected error: {msg}"
        print("  OK: header without voice raises clear error")

    if failures:
        print(f"\n{failures} test(s) FAILED")
        sys.exit(1)
    print("\nAll scene parser tests passed.")


if __name__ == "__main__":
    main()