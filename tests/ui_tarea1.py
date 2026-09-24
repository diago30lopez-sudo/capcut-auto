"""Verifica TAREA 1 (UI): arranca la ventana real, conecta drafts+video reales,
escanea el selector de .srt, simula una generacion exitosa y confirma que
aparece el cartel verde "COMPLETADO" no bloqueante con boton "✕".

Cierra la app y reporta OK si todo pasa. No genera proyecto real (solo
simula el estado de exito del hilo para probar el modal)."""

from __future__ import annotations

import queue
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config
from src.core.auto_detect import detect_video_inputs
from src.ui.main_window import NO_SRT, MainWindow, SUCCESS
from src.utils.logger import setup_logging

DRAFTS = r"D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts"
VIDEO = r"D:\YOUTUBE AUTOMATIZADO\1.historias hipoteticas\VIDEO\VIDEO_1"

config.ensure_dirs()

q: queue.Queue = queue.Queue()
setup_logging(q, config.APP_LOG_FILE)

app = MainWindow(q)
state = {"modal_seen": False, "modal_color": None, "x_btn_ok": False, "srt_found": False}


def check_after_boot() -> None:
    try:
        # 1) resta siete sesion con drafts + video reales
        app._apply_drafts_dir(Path(DRAFTS), persist=False)
        app._apply_video_dir(Path(VIDEO), persist=False)
        app._update_ui_state()

        # 2) el selector de .srt debe escanear la carpeta y ver la alineacion
        #    guardada en cache (o cualquier .srt del video).
        srt_files = app._scan_srt_files(app._video_dir)
        state["srt_found"] = bool(srt_files)
        if srt_files:
            first = srt_files[0]
            app._apply_srt_dir(first, persist=False)

        # 3) simular que el hilo termino con exito (sin ejecutar generate real)
        app._job_succeeded = True
        app._running = True
        app._thread_done.set()
        # espera a que el after() de _poll_queue muestre el modal
        app.after(500, check_modal)
    except Exception:
        app.after(50, check_after_boot) if not hasattr(app, "_checked") else None
        app._checked = True
        app.destroy()
        raise


def check_modal() -> None:
    modal = app._success_modal
    if modal is None or not modal.winfo_exists():
        print("error: no se creo el cartel verde")
        app.destroy()
        return
    state["modal_seen"] = True
    state["modal_color"] = modal.cget("fg_color")
    # buscar el boton "✕" (primer CTkButton con texto x)
    for child in modal.winfo_children():
        try:
            if (child.cget("text") or "") == "✕":
                state["x_btn_ok"] = True
                break
        except Exception:
            pass
    ok = (
        state["srt_found"]
        and state["modal_seen"]
        and state["modal_color"] == SUCCESS
        and state["x_btn_ok"]
    )
    print("UI_TAREA1",
          "OK" if ok else "FALLO",
          f"· srt={len(app._scan_srt_files(app._video_dir))} · modal={state['modal_color']} · x={state['x_btn_ok']}")
    modal.destroy()
    app.destroy()


app.after(200, check_after_boot)
app.mainloop()

assert state["srt_found"], "no se escanearon .srt del video"
assert state["modal_seen"], "no aparecio el cartel"
assert state["modal_color"] == SUCCESS, state["modal_color"]
assert state["x_btn_ok"], "no hay boton X"
print("UI_TAREA1_OK")