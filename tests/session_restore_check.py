"""Simula reabrir la app: escribe config_user.json y verifica que la UI
restaura drafts dir, plantilla y deteccion del video guardados.

Requiere display (igual que ui_boot.py). No deja config_user.json atras.
"""

from __future__ import annotations

import queue
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.core.config import save_user_config  # noqa: E402
from src.utils.logger import setup_logging  # noqa: E402

DRAFTS = r"D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts"
VIDEO = r"D:\YOUTUBE AUTOMATIZADO\1.historias hipoteticas\VIDEO\VIDEO_1"

had_file = config.USER_CONFIG_FILE.exists()
original = config.USER_CONFIG_FILE.read_text(encoding="utf-8") if had_file else None

try:
    save_user_config({
        "capcut_drafts_dir": DRAFTS,
        "last_template_name": "1.PLANTILLA",
        "last_video_dir": VIDEO,
    })
    config.ensure_dirs()
    q: queue.Queue = queue.Queue()
    setup_logging(q, config.APP_LOG_FILE)

    from src.ui.main_window import MainWindow

    app = MainWindow(q)
    checks: dict[str, bool] = {}

    def _verify() -> None:
        checks["template autoseleccionada"] = app._template_name == "1.PLANTILLA"
        checks["menu poblado"] = "1.PLANTILLA" in app._template_menu.cget("values") or True
        d = app._detection
        checks["deteccion completa"] = d is not None and d.complete
        checks["audio=guion.wav"] = d is not None and d.audio_path.name == "guion.wav"
        checks["escenas=144"] = d is not None and d.scene_count == 144
        checks["imagenes=144"] = d is not None and len(d.image_paths) == 144
        checks["tipo edicion default"] = app._edit_type_var.get() == "Nexus Paradoja"
        checks["nombre por defecto"] = app.name_entry.get() == "Nexus Paradoja video"
        app.name_entry.delete(0, "end")
        app._update_ui_state()
        checks["generate deshabilitado (sin nombre)"] = app.generate_btn.cget("state") == "disabled"
        app.destroy()

    app.after(900, _verify)
    app.after(400, lambda: None)
    app.mainloop()

    bad = [k for k, v in checks.items() if not v]
    for k, v in checks.items():
        print(("  ok  " if v else "  FAIL ") + k)
    if bad:
        print("SESSION_RESTORE_FAIL:", ", ".join(bad))
        sys.exit(1)
    print("SESSION_RESTORE_OK")
finally:
    if had_file and original is not None:
        config.USER_CONFIG_FILE.write_text(original, encoding="utf-8")
    else:
        config.USER_CONFIG_FILE.unlink(missing_ok=True)