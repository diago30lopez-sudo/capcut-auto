"""Prueba exhaustiva (TAREA 3) del parser ultra-flexible de escenas.

Valida los 4 formatos que piden las IAs (ChatGPT, Claude, etc.):

  A) Formato del usuario actual (una linea, comillas, DURACIÓN + Prompt Image):
         ESCENA #001 VOZ EN OFF: "Hola mundo." DURACIÓN: 4s
         Prompt Image: 001 Wide shot...
  B) Formato tradicional multilínea:
         ESCENA #1
         VOZ EN OFF:
         Hola mundo.
  C) Formato sin "VOZ EN OFF":
         Escena 1: Hola mundo.
  D) Formato con minúsculas:
         escena #2 voz en off: "Hola."

Ejecuta:  python tests/scene_parser_bulletproof.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.scene_parser import parse_scenes


def _write(tmp: Path, name: str, content: str) -> Path:
    p = tmp / name
    p.write_text(content, encoding="utf-8")
    return p


def _check(label: str, cond: bool, detail: str) -> bool:
    if cond:
        print(f"  OK   {label} -> {detail}")
        return True
    print(f"  FAIL {label} -> {detail}")
    return False


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="scene_bp_"))
    results: list[bool] = []

    # A) Formato del usuario actual (una linea) -------------------------------
    print("A) Formato del usuario actual:")
    p = _write(tmp, "a.txt", (
        "ESCENA #001 VOZ EN OFF: \"Hola mundo.\" DURACIÓN: 4s\n"
        "Prompt Image: 001 Wide shot establishing shot.\n"
    ))
    scenes = parse_scenes(p)
    results.append(_check(
        "una escena", len(scenes) == 1, f"count={len(scenes)}",
    ))
    if scenes:
        results.append(_check(
            "number=1", scenes[0].number == 1, f"number={scenes[0].number}",
        ))
        results.append(_check(
            "key_text limpio", scenes[0].key_text == "Hola mundo.",
            f"key_text={scenes[0].key_text!r}",
        ))

    # B) Formato tradicional multilínea --------------------------------------
    print("B) Formato tradicional multilínea:")
    p = _write(tmp, "b.txt", (
        "ESCENA #1\n"
        "VOZ EN OFF:\n"
        "Hola mundo.\n"
    ))
    scenes = parse_scenes(p)
    results.append(_check(
        "una escena", len(scenes) == 1, f"count={len(scenes)}",
    ))
    if scenes:
        results.append(_check(
            "key_text", scenes[0].key_text == "Hola mundo.",
            f"key_text={scenes[0].key_text!r}",
        ))

    # C) Formato sin "VOZ EN OFF" --------------------------------------------
    print("C) Formato sin VOZ EN OFF:")
    p = _write(tmp, "c.txt", "Escena 1: Hola mundo.\n")
    scenes = parse_scenes(p)
    results.append(_check(
        "una escena", len(scenes) == 1, f"count={len(scenes)}",
    ))
    if scenes:
        results.append(_check(
            "key_text", scenes[0].key_text == "Hola mundo.",
            f"key_text={scenes[0].key_text!r}",
        ))

    # D) Formato con minúsculas ----------------------------------------------
    print("D) Formato con minúsculas:")
    p = _write(tmp, "d.txt", "escena #2 voz en off: \"Hola.\"\n")
    scenes = parse_scenes(p)
    results.append(_check(
        "una escena", len(scenes) == 1, f"count={len(scenes)}",
    ))
    if scenes:
        results.append(_check(
            "number=2", scenes[0].number == 2, f"number={scenes[0].number}",
        ))
        results.append(_check(
            "key_text", scenes[0].key_text == "Hola.",
            f"key_text={scenes[0].key_text!r}",
        ))

    # E) BONUS: varias escenas mezcladas en un solo archivo -------------------
    print("E) BONUS: archivo mixto (varias escenas, formatos distintos):")
    p = _write(tmp, "e.txt", (
        "ESCENA #001 VOZ EN OFF: \"Frase uno.\" DURACIÓN: 4s\n"
        "Prompt Image: 001 Wide shot.\n"
        "ESCENA #2\n"
        "VOZ EN OFF:\n"
        "Frase dos.\n"
        "Escena 3: Frase tres.\n"
        "escena #4 voz en off: \"Frase cuatro.\"\n"
    ))
    scenes = parse_scenes(p)
    expect = {"1": "Frase uno.", "2": "Frase dos.", "3": "Frase tres.", "4": "Frase cuatro."}
    got = {str(s.number): s.key_text for s in scenes}
    results.append(_check(
        "cuatro escenas", len(scenes) == 4, f"count={len(scenes)}",
    ))
    for num, text in expect.items():
        results.append(_check(
            f"escena {num}", got.get(num) == text, f"got={got.get(num)!r} want={text!r}",
        ))

    # F) BONUS: archivo sin escenas pero con la palabra ESCENA (advertencia) --
    print("F) BONUS: 0 escenas pero contiene 'ESCENA' (debe advertir + lanzar error):")
    p = _write(tmp, "f.txt", "Esto habla de la ESCENA pero sin numeracion valida.")
    try:
        parse_scenes(p)
        results.append(_check("lanza ValueError", False, "no lanzo error"))
    except ValueError as exc:
        results.append(_check(
            "lanza ValueError", "no contiene ninguna escena reconocible" in str(exc),
            str(exc)[:80],
        ))

    ok = all(results)
    if ok:
        print("\nTODAS LAS PRUEBAS DE FORMATO PASARON (A, B, C, D + bonus).")
        return 0
    print(f"\n{results.count(False)} comprobacion(es) FALLARON.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
