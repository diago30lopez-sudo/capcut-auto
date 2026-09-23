"""Arranque de CapCut Auto — deteccion inteligente + cancelacion + persistencia.

Uso:
    python src/main.py      (desde la raiz del proyecto)
    python -m src.main      (equivalente)
"""

from __future__ import annotations

import queue
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from src.core import config
    from src.ui.main_window import MainWindow
    from src.utils.logger import setup_logging

    config.ensure_dirs()
    log_queue: queue.Queue = queue.Queue()
    setup_logging(log_queue, config.APP_LOG_FILE)
    app = MainWindow(log_queue)
    app.mainloop()


if __name__ == "__main__":
    main()
