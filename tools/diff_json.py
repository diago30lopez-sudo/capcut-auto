"""Compara dos draft_content.json (plantilla vs generado) y reporta diferencias.

Uso:
    python tools/diff_json.py <base.json> <generado.json> [--solo-estructural]

Salida (por defecto estructural + valores):
    - claves presentes en base y ausentes en generado  (superconjunto roto)
    - claves en generado y ausentes en base            (habitual: medidas correctas)
    - cambios de tipo en claves compartidas
    - diferencias de longitud en listas y, si ambas son listas de dicts,
      diferencias campo a campo del primer elemento.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402

MISSED = "SOLO_EN_BASE"
ADDED = "SOLO_EN_GEN"
TYPE = "TIPO"
LEN = "LONGITUD"
VAL = "VALOR"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def diff_paths(base, gen, path=()):
    """Devuelve dict { (tupla de claves, tipo_diferencia): (a, b) }."""
    out = {}
    if isinstance(base, dict) and isinstance(gen, dict):
        for k in base:
            if k not in gen:
                out[(path + (k,), MISSED)] = (base[k], None)
        for k in gen:
            if k not in base:
                out[(path + (k,), ADDED)] = (None, gen[k])
        for k in base.keys() & gen.keys():
            out.update(diff_paths(base[k], gen[k], path + (k,)))
        return out
    if isinstance(base, list) and isinstance(gen, list):
        if len(base) != len(gen):
            out[(path, LEN)] = (len(base), len(gen))
        for i, (bv, gv) in enumerate(zip(base, gen)):
            out.update(diff_paths(bv, gv, path + (f"[{i}]",)))
        return out
    if type(base) is not type(gen):
        if isinstance(base, (int, float)) and isinstance(gen, (int, float)):
            pass  # int <-> float equivalente
        elif base is None or gen is None:
            pass  # null <-> algo (implica MISSED/ADDED si aplica)
        else:
            out[(path, TYPE)] = (type(base).__name__, type(gen).__name__)
    if base != gen:
        out[(path, VAL)] = (base, gen)
    return out


def _clip(v, ln=80):
    s = json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= ln else s[:ln] + "…"


def report(diffs: dict) -> list[str]:
    lines = []
    missed = {k: v for k, v in diffs.items() if k[1] == MISSED}
    added = {k: v for k, v in diffs.items() if k[1] == ADDED}
    types = {k: v for k, v in diffs.items() if k[1] == TYPE}
    lens = {k: v for k, v in diffs.items() if k[1] == LEN}
    vals = {k: v for k, v in diffs.items() if k[1] == VAL}

    lines.append(f"claves SOLO en base (superconjunto roto): {len(missed)}")
    for (p, _), (a, _) in sorted(missed.items(), key=lambda kv: kv[0][0]):
        lines.append(f"  - {'/'.join(p)}  (ej. base: {_clip(a)})")
    lines.append(f"claves SOLO en generado: {len(added)}")
    for (p, _), (_, b) in sorted(added.items(), key=lambda kv: kv[0][0]):
        lines.append(f"  + {'/'.join(p)}  (ej. gen: {_clip(b)})")
    lines.append(f"cambios de tipo: {len(types)}")
    for (p, _), (a, b) in sorted(types.items(), key=lambda kv: kv[0][0]):
        lines.append(f"  ~ {'/'.join(p)}: {a} -> {b}")
    lines.append(f"longitudes distintas de listas: {len(lens)}")
    for (p, _), (a, b) in sorted(lens.items(), key=lambda kv: kv[0][0]):
        lines.append(f"  # {'/'.join(p)}: {a} -> {b}")
    lines.append(f"valores distintos en clave compartida: {len(vals)}")
    for (p, _), (a, b) in sorted(vals.items(), key=lambda kv: kv[0][0]):
        lines.append(f"  != {'/'.join(p)}: {_clip(a)}  ->  {_clip(b)}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("generado")
    args = parser.parse_args()

    base = load(Path(args.base))
    gen = load(Path(args.generado))
    diffs = diff_paths(base, gen)
    print("\n".join(report(diffs)))
    print(f"\ntotal diferencias registradas: {len(diffs)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except json.JSONDecodeError as exc:
        print(f"ERROR: JSON inválido ({exc})", file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)