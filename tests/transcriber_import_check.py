"""Check unitario anti-typo: CRISPASR (sin T) se mantiene consistente.

Ejecutar desde la raiz:
    & .venv\\Scripts\\python.exe -X utf8 tests\\transcriber_import_check.py

Regresion del bug "module 'src.core.config' has no attribute 'CRISPASTR_EXE'":
se verifica que config expone CRISPASR_EXE, que transcriber._ensure_crispasr_exe
existe y puede ejecutarse (sin red ni descargas) sin AttributeError, y que
ningun .py de src/ contiene el typo CRISPASTR.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.core import transcriber  # noqa: E402

FAIL: list[str] = []
PASS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


def main() -> None:
    print("[transcriber import / typo CRISPASR]")

    check("config.CRISPASR_EXE definido",
          hasattr(config, "CRISPASR_EXE") and isinstance(config.CRISPASR_EXE, Path))

    fn = getattr(transcriber, "_ensure_crispasr_exe", None)
    check("transcriber._ensure_crispasr_exe existe", callable(fn))

    if callable(fn):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "crispasr.exe"
            exe.write_bytes(b"")
            old = config.CRISPASR_EXE
            config.CRISPASR_EXE = exe
            try:
                got = fn()
                check("_ensure_crispasr_exe se ejecuta sin AttributeError",
                      got == exe, str(got))
            except AttributeError as exc:
                check("_ensure_crispasr_exe se ejecuta sin AttributeError",
                      False, str(exc))
            finally:
                config.CRISPASR_EXE = old

    bad = [
        p for p in Path(ROOT, "src").rglob("*.py")
        if "CRISPASTR" in p.read_text(encoding="utf-8")
    ]
    check("ningun .py de src/ contiene CRISPASTR", not bad, str([str(p) for p in bad]))

    print(f"\nRESULTADO: {PASS} checks ok, {len(FAIL)} fallos.")
    if FAIL:
        print("FALLOS:", ", ".join(FAIL))
        sys.exit(1)
    print("TRANSCRIBER_IMPORT_OK")


if __name__ == "__main__":
    main()