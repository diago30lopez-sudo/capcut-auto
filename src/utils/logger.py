"""Configuracion del logging: cola hacia la UI + fichero en logs/app.log."""

from __future__ import annotations

import logging
import queue
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"

LEVEL_COLORS = {
    "DEBUG": "#9e9e9e",
    "INFO": "#4fc3f7",
    "WARNING": "#ffd54f",
    "ERROR": "#ff6b6b",
    "CRITICAL": "#ff3b3b",
}


def setup_logging(log_queue: queue.Queue, log_file: Path) -> logging.Logger:
    """Instala handlers en el logger 'capcutauto' y lo devuelve."""
    logger = logging.getLogger("capcutauto")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT, "%H:%M:%S")

    qh = logging.handlers.QueueHandler(log_queue)
    qh.setFormatter(formatter)
    logger.addHandler(qh)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        log_file, maxBytes=4 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter(LOG_FORMAT, "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)

    return logger


def drain_queue(log_queue: queue.Queue) -> list[str]:
    """Extrae records de la cola y los devuelve como lineas ya formateadas."""
    lines: list[str] = []
    try:
        while True:
            record = log_queue.get_nowait()
            try:
                msg = record.getMessage()
            except Exception:  # noqa: BLE001
                msg = str(record.msg)
            ts = record.asctime or ""
            level = record.levelname or ""
            lines.append(f"{ts} | {level:8s} | {msg}")
    except queue.Empty:
        pass
    return lines