"""Check de src/core/bootstrap.ensure_dependencies (TAREA 1).

Verifica que:

1) Si TODAS las dependencias ya existen en disco (bin/ con crispasr.exe,
   crispasr-quantize.exe, openblas.dll, LICENSE, THIRD_PARTY_NOTICES.txt y
   models/ con el GGUF), ensure_dependencies NO llama a _download_file.
2) Si falta un binario de CrispASR, se descarga el .zip oficial
   (config.CRISPASR_DOWNLOAD_URL).
3) Si falta el modelo GGUF, se descarga desde config.MODEL_DOWNLOAD_URL.

Corre 100% offline (no toca la red): se parachea _download_file para registrar
las llamadas y se apuntan las rutas de config a directorios temporales.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import bootstrap  # noqa: E402
from src.core import config  # noqa: E402


def _touches_bins(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in bootstrap.BIN_DEPENDENCIES:
        (bin_dir / name).write_text("binario", encoding="ascii")


def _point_config(bin_dir: Path, models_dir: Path) -> None:
    fakes = {
        "BIN_DIR": bin_dir,
        "MODELS_DIR": models_dir,
        "CACHE_DIR": bin_dir.parent / "cache",
        "ALIGN_MODEL_PATH": models_dir / config.ALIGN_MODEL_FILENAME,
        "CRISPASR_EXE": bin_dir / "crispasr.exe",
        "CRISPASR_ZIP_NAME": "crispasr-windows-x86_64-cpu.zip",
        "CRISPASR_DOWNLOAD_URL": config.CRISPASR_DOWNLOAD_URL,
        "MODEL_DOWNLOAD_URL": config.MODEL_DOWNLOAD_URL,
    }
    for key, val in fakes.items():
        setattr(config, key, val)
        setattr(bootstrap.config, key, val)
    bin_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)


def main() -> None:
    ok = True
    work = Path(tempfile.mkdtemp(prefix="capcutauto_boot_"))
    bin_dir, models_dir = work / "bin", work / "models"
    _point_config(bin_dir, models_dir)
    (models_dir / config.ALIGN_MODEL_FILENAME).write_text("modelo", encoding="ascii")
    checks: dict[str, bool] = {}

    # --- Caso 1: TODAS las dependencias presentes -> no se descarga nada.
    _touches_bins(bin_dir)
    with mock.patch.object(bootstrap, "_download_file") as dl:
        bootstrap.ensure_dependencies()
    checks["1) dependencias presentes -> NO se descarga"] = dl.call_count == 0
    ok = ok and dl.call_count == 0

    # --- Caso 2: falta un binario -> se descarga el .zip de CrispASR.
    (bin_dir / "openblas.dll").unlink()
    with mock.patch.object(bootstrap, "_flatten_bin") as flat, \
            mock.patch.object(bootstrap, "_download_file") as dl, \
            mock.patch("zipfile.ZipFile") as zf:
        (bin_dir / "openblas.dll").unlink(missing_ok=True)
        zf.return_value.__enter__.return_value.extractall.side_effect = (
            lambda *a, **k: (bin_dir / "openblas.dll").write_text(
                "binario", encoding="ascii"))
        bootstrap.ensure_dependencies()
    checks["2) falta openblas.dll -> descarga el .zip de CrispASR"] = (
        dl.call_count == 1 and dl.call_args[0][0] == config.CRISPASR_DOWNLOAD_URL
        and flat.call_count == 1 and zf.call_count == 1)
    ok = ok and dl.call_count == 1 and dl.call_args[0][0] == config.CRISPASR_DOWNLOAD_URL

    # --- Caso 3: falta el modelo GGUF -> solo se descarga el modelo.
    _touches_bins(bin_dir)
    (models_dir / config.ALIGN_MODEL_FILENAME).unlink()
    with mock.patch.object(bootstrap, "_download_file") as dl:
        bootstrap.ensure_dependencies()
    checks["3) falta el GGUF -> descarga el modelo"] = (
        dl.call_count == 1 and dl.call_args[0][0] == config.MODEL_DOWNLOAD_URL)
    ok = ok and dl.call_count == 1 and dl.call_args[0][0] == config.MODEL_DOWNLOAD_URL

    for k, v in checks.items():
        print(("  ok  " if v else "  FAIL ") + k)
        ok = ok and v

    if not ok:
        print("BOOTSTRAP_FAIL")
        sys.exit(1)
    print("BOOTSTRAP_OK")


if __name__ == "__main__":
    main()