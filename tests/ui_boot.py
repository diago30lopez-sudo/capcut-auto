"""Arranca la UI real unos instantes y cierra para verificar que no hay
errores de construccion ni de CustomTkinter sin necesidad de interaccion."""

from __future__ import annotations

import queue
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config
from src.utils.logger import setup_logging
from src.ui.main_window import MainWindow

config.ensure_dirs()

q: queue.Queue = queue.Queue()
setup_logging(q, config.APP_LOG_FILE)

app = MainWindow(q)
app.after(900, app.destroy)
app.mainloop()
print("UI_BOOT_OK")
