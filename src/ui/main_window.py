"""Ventana principal de CapCut Auto con CustomTkinter.

3 secciones + subtítulos + cancelacion + persistencia:

1. Carpeta CapCut Drafts: se guarda en config_user.json y rellena el combo de
   plantillas detectadas (subcarpetas con draft_content.json + draft_meta_info.json).
2. Carpeta del video: escaneo inteligente (src.core.auto_detect) y resumen
   con estado ✓/✗ de audio, escenas e imagenes.
3. Subtítulos (.srt): selector que escanea la carpeta del video en busca de
   archivos .srt; cada cue se divide en fragmentos de 2-5 palabras con timing
   proporcional (TAREA 2) durante la generacion.
4. Nombre del nuevo proyecto.

Al terminar la generacion con exito se muestra un cartel verde modal
(#28a745) con "COMPLETADO" y boton "✕" para cerrarlo; se abre con after()
para no bloquear el main thread.

Todo el procesamiento corre en un threading.Thread; los logs llegan por una
cola (QueueHandler) y la UI los consume con after(). El boton Cancelar setea
un threading.Event compartido con el hilo de trabajo.
"""

from __future__ import annotations

import logging
import queue
import threading
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from src.core import config
from src.core.auto_detect import DetectionResult, detect_video_inputs, find_capcut_templates
from src.core.capcut_project import CapCutProject
from src.core.config import load_user_config, save_user_config
from src.core.scene_parser import parse_scenes
from src.core.timeline_builder import GenerationCancelled, build_timeline, parse_srt
from src.core.transcriber import align_audio_to_text
from src.utils.logger import drain_queue, setup_logging

log = logging.getLogger("capcutauto")

ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"
BG = "#121212"
PANEL = "#1e1e1e"
TEXT = "#e5e7eb"
MUTED = "#9ca3af"
GREEN = "#4ade80"
RED = "#ff6b6b"
AMBER = "#ffd54f"
SUCCESS = "#28a745"  # cartel de completado (TAREA 1)

NO_TEMPLATES = "— sin plantillas —"
NO_SRT = "— sin subtítulos (.srt) —"

# Punto 1: tipos de edición disponibles; el nombre por defecto cambia según el
# tipo seleccionado.
EDIT_TYPES = ["Nexus Paradoja"]
DEFAULT_PROJECT_NAME = "Nexus Paradoja video"

LOG_TAGS = {
    "INFO": "#4fc3f7",
    "WARNING": "#ffd54f",
    "ERROR": "#ff6b6b",
    "CRITICAL": "#ff3b3b",
    "OK": "#4ade80",
}


class MainWindow(ctk.CTk):
    def __init__(self, log_queue: queue.Queue):
        super().__init__(fg_color=BG)
        self.log_queue = log_queue
        self.cancel_event = threading.Event()
        self._thread_done = threading.Event()
        self._running = False
        self._job_succeeded = False
        self._success_modal: ctk.CTkToplevel | None = None

        self._user_config = load_user_config()
        self._drafts_dir: Path | None = None
        self._template_name: str = ""
        self._video_dir: Path | None = None
        self._detection: DetectionResult | None = None
        self._srt_dir: Path | None = None  # carpeta donde esta el .srt elegido
        self._srt_name: str = ""           # nombre del .srt elegido

        self.title("CapCut Auto")
        self.configure(fg_color=BG)
        self._center(920, 780)
        ctk.set_appearance_mode("dark")

        self._build_ui()
        self.after(100, self._poll_queue)
        self.after(200, self._restore_session)

    # ------------------------------------------------------------------ UI
    def _center(self, w: int, h: int) -> None:
        self.geometry(f"{w}x{h}")
        self.update_idletasks()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(880, 680)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color=BG)
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 2))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="CapCut Auto",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Genera un proyecto de CapCut con imágenes sincronizadas al audio",
            font=ctk.CTkFont(size=12), text_color=MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(0, 4))

        # Split pane (dos columnas) usando CTkPanedWindow o CTkFrame con dos columnas
        splitter = ctk.CTkFrame(self, fg_color=BG)
        splitter.grid(row=2, column=0, sticky="nsew", padx=24, pady=(2, 16))
        splitter.grid_columnconfigure(0, weight=3)
        splitter.grid_columnconfigure(1, weight=4)
        splitter.grid_rowconfigure(0, weight=1)

        # Panel izquierdo con Scrollbar general para todos los controles
        left_outer = ctk.CTkScrollableFrame(splitter, fg_color=BG, corner_radius=0)
        left_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)
        left_outer.grid_columnconfigure(0, weight=1)

        self._build_section1_drafts(left_outer, row=0)
        self._build_section2_video(left_outer, row=1)
        self._build_section_subtitles(left_outer, row=2)
        self._build_section_edit_type(left_outer, row=3)
        self._build_section3_name(left_outer, row=4)

        # Botones y barra de progreso en el panel izquierdo al final
        buttons_frame = ctk.CTkFrame(left_outer, fg_color=BG)
        buttons_frame.grid(row=5, column=0, sticky="ew", padx=0, pady=(10, 4))
        buttons_frame.grid_columnconfigure(0, weight=1)
        buttons_frame.grid_columnconfigure(1, weight=1)

        self.generate_btn = ctk.CTkButton(
            buttons_frame, text="Generar proyecto", height=42, corner_radius=10,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#16a34a", hover_color="#15803d",
            command=self._on_generate, state="disabled",
        )
        self.generate_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.cancel_btn = ctk.CTkButton(
            buttons_frame, text="Cancelar", height=42, corner_radius=10,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#dc2626", hover_color="#b91c1c",
            command=self._on_cancel, state="disabled",
        )
        self.cancel_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.progress = ctk.CTkProgressBar(
            left_outer, mode="indeterminate", height=8,
            progress_color=ACCENT, fg_color="#2a2a2a",
        )
        self.progress.grid(row=6, column=0, sticky="ew", padx=0, pady=(6, 12))
        self.progress.set(0)

        # Panel derecho: única y exclusivamente el área de texto de logs
        right_panel = ctk.CTkFrame(splitter, fg_color=PANEL, corner_radius=10)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=0)
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_rowconfigure(0, weight=1)

        self.log_box = ctk.CTkTextbox(
            right_panel, fg_color="#101010", text_color=TEXT,
            font=ctk.CTkFont(family="Consolas", size=12), wrap="word",
        )
        self.log_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.log_box.configure(state="disabled")
        for tag, color in LOG_TAGS.items():
            self.log_box.tag_config(tag, foreground=color)

    def _section_title(self, parent, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent, text=text, font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT,
        )

    def _build_section1_drafts(self, parent, row: int) -> None:
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=row, column=0, sticky="ew", padx=0, pady=6)
        panel.grid_columnconfigure(1, weight=1)

        self._section_title(panel, "1 · Carpeta CapCut Drafts").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(8, 4))

        ctk.CTkButton(
            panel, text="Seleccionar carpeta…", width=150, height=30,
            corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._browse_drafts,
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 4))

        self._drafts_path_label = ctk.CTkLabel(
            panel, text="Sin seleccionar", font=ctk.CTkFont(size=12),
            text_color=MUTED, anchor="w", justify="left",
        )
        self._drafts_path_label.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 4))

        ctk.CTkButton(
            panel, text="Cambiar…", width=80, height=26, corner_radius=8,
            fg_color="#334155", hover_color="#475569",
            command=self._browse_drafts,
        ).grid(row=1, column=2, sticky="e", padx=12, pady=(0, 4))

        self._template_var = ctk.StringVar(value=NO_TEMPLATES)
        self._template_menu = ctk.CTkOptionMenu(
            panel, values=[NO_TEMPLATES], variable=self._template_var,
            height=30, corner_radius=8, state="disabled",
            fg_color="#2a2a2a", button_color="#334155",
            button_hover_color="#475569",
            command=self._on_template_changed,
        )
        self._template_menu.grid(
            row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))

    def _build_section2_video(self, parent, row: int) -> None:
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=row, column=0, sticky="ew", padx=0, pady=6)
        panel.grid_columnconfigure(1, weight=1)

        self._section_title(panel, "2 · Carpeta del video").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 4))

        ctk.CTkButton(
            panel, text="Seleccionar carpeta…", width=150, height=30,
            corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._browse_video,
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 6))

        self._video_path_label = ctk.CTkLabel(
            panel, text="Sin seleccionar", font=ctk.CTkFont(size=12),
            text_color=MUTED, anchor="w", justify="left",
        )
        self._video_path_label.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 6))

        self._audio_status = self._status_label(panel, 2, "Audio")
        self._scene_status = self._status_label(panel, 3, "Escenas")
        self._img_status = self._status_label(panel, 4, "Imágenes")
        self._status_footer = ctk.CTkLabel(
            panel, text="", font=ctk.CTkFont(size=11), text_color=MUTED,
            anchor="w", justify="left",
        )
        self._status_footer.grid(
            row=5, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10))

    def _build_section_subtitles(self, parent, row: int) -> None:
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=row, column=0, sticky="ew", padx=0, pady=6)
        panel.grid_columnconfigure(1, weight=1)

        self._section_title(panel, "3 · Subtítulos (.srt)").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(8, 4))

        ctk.CTkButton(
            panel, text="Buscar .srt…", width=150, height=30,
            corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._browse_srt,
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 4))

        self._srt_path_label = ctk.CTkLabel(
            panel, text=NO_SRT, font=ctk.CTkFont(size=12),
            text_color=MUTED, anchor="w", justify="left",
        )
        self._srt_path_label.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 4))
        self._srt_path_label.bind("<Button-1>", lambda _e: self._browse_srt())

        self._srt_var = ctk.StringVar(value=NO_SRT)
        self._srt_menu = ctk.CTkOptionMenu(
            panel, values=[NO_SRT], variable=self._srt_var,
            height=30, corner_radius=8, state="disabled",
            fg_color="#2a2a2a", button_color="#334155",
            button_hover_color="#475569",
            command=self._on_srt_changed,
        )
        self._srt_menu.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 4))

        self._srt_footer = ctk.CTkLabel(
            panel, text="Los subtítulos se dividen en fragmentos de 2-5 palabras.",
            font=ctk.CTkFont(size=11), text_color=MUTED,
            anchor="w", justify="left",
        )
        self._srt_footer.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))

    def _build_section_edit_type(self, parent, row: int) -> None:
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=row, column=0, sticky="ew", padx=0, pady=6)
        panel.grid_columnconfigure(0, weight=1)

        self._section_title(panel, "4 · Tipo de edición").grid(
            row=0, column=0, sticky="w", padx=12, pady=(8, 4))

        self._edit_type_var = ctk.StringVar(value=EDIT_TYPES[0])
        self._edit_type_menu = ctk.CTkOptionMenu(
            panel, values=list(EDIT_TYPES), variable=self._edit_type_var,
            height=32, corner_radius=8,
            fg_color="#2a2a2a", button_color=ACCENT, button_hover_color=ACCENT_HOVER,
            command=self._on_edit_type_changed,
        )
        self._edit_type_menu.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))

    def _build_section3_name(self, parent, row: int) -> None:
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=row, column=0, sticky="ew", padx=0, pady=6)
        panel.grid_columnconfigure(0, weight=1)

        self._section_title(panel, "5 · Nombre del nuevo proyecto").grid(
            row=0, column=0, sticky="w", padx=12, pady=(8, 4))

        self.name_entry = ctk.CTkEntry(
            panel, placeholder_text="ej. mi_video_diapositivas", height=34,
            corner_radius=8, fg_color="#2a2a2a", text_color=TEXT,
        )
        self.name_entry.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        self.name_entry.bind("<KeyRelease>", lambda _e: self._update_ui_state())
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, DEFAULT_PROJECT_NAME)

    # --------------------------------------------------- persistencia / estado
    def _save_user_config(self) -> None:
        self._user_config["capcut_drafts_dir"] = str(self._drafts_dir) if self._drafts_dir else ""
        self._user_config["last_template_name"] = self._template_name or ""
        self._user_config["last_video_dir"] = str(self._video_dir) if self._video_dir else ""
        self._user_config["last_srt_dir"] = str(self._srt_dir) if self._srt_dir else ""
        self._user_config["last_srt_name"] = self._srt_name or ""
        save_user_config(self._user_config)

    def _scan_srt_files(self, folder: Path) -> list[Path]:
        """Busca archivos .srt en la carpeta del video (y un nivel hacia abajo
        del caché donde la alineación los guarda). Devuelve ordenados."""
        found: set[Path] = set()
        if folder is not None and folder.is_dir():
            found.update(folder.rglob("*.srt"))
        cache = Path(config.CACHE_DIR)
        if cache.is_dir():
            found.update(cache.glob("alineacion_*.srt"))
        return sorted(found, key=lambda p: p.name.lower())

    def _apply_srt_dir(self, srt: Path | None, persist: bool) -> None:
        """Guarda la seleccion de .srt elegida por el usuario (o None si elige
        el placeholder). Actualiza label, combo y estado."""
        if srt is None:
            self._srt_dir = None
            self._srt_name = ""
            self._srt_var.set(NO_SRT)
            self._srt_path_label.configure(text=NO_SRT, text_color=MUTED)
            if persist:
                self._save_user_config()
            self._update_ui_state()
            return
        self._srt_dir = srt.parent
        self._srt_name = srt.name
        self._srt_var.set(str(srt))
        self._srt_path_label.configure(text=str(srt), text_color=TEXT)
        if persist:
            self._save_user_config()
        log.info("Subtítulos: %s", srt)
        self._update_ui_state()

    def _browse_srt(self) -> None:
        start = Path(self._video_dir) if self._video_dir else Path.home()
        path = filedialog.askopenfilename(
            initialdir=start, title="Elegir archivo de subtítulos (.srt)",
            filetypes=[("Subtítulos SRT", "*.srt"), ("Todos los archivos", "*.*")],
        )
        if not path:
            return
        self._apply_srt_dir(Path(path), persist=True)

    def _restore_session(self) -> None:
        drafts = self._user_config.get("capcut_drafts_dir", "")
        if drafts:
            self._apply_drafts_dir(Path(drafts), persist=False)
        video = self._user_config.get("last_video_dir", "")
        if video and Path(video).is_dir():
            self._apply_video_dir(Path(video), persist=False)
        srt_dir = self._user_config.get("last_srt_dir", "")
        srt_name = self._user_config.get("last_srt_name", "")
        if srt_dir and srt_name:
            srt = Path(srt_dir) / srt_name
            if srt.is_file():
                self._apply_srt_dir(srt, persist=False)
        self._update_ui_state()

    def _update_ui_state(self) -> None:
        running = self._running
        detection = self._detection
        ok = (
            not running
            and self._drafts_dir is not None
            and self._template_name
            and self._video_dir is not None
            and detection is not None
            and detection.complete
            and bool(self.name_entry.get().strip())
        )
        self.generate_btn.configure(state="normal" if ok else "disabled")
        self.cancel_btn.configure(state="disabled" if not running else "normal")

    # ---------------------------------------------- seccion 1 (drafts folder)
    def _browse_drafts(self) -> None:
        initial = str(self._drafts_dir) if self._drafts_dir else str(Path.home())
        path = filedialog.askdirectory(initialdir=initial)
        if not path:
            return
        self._apply_drafts_dir(Path(path), persist=True)

    def _apply_drafts_dir(self, drafts_dir: Path, persist: bool) -> None:
        templates = find_capcut_templates(drafts_dir)
        if not templates:
            self._status_footer.configure(text="")
            messagebox.showerror(
                "CapCut Auto",
                f"No se encontraron plantillas válidas en:\n{drafts_dir}\n\n"
                "Se busca una subcarpeta que contenga a la vez "
                f"{config.DRAFT_CONTENT_FILE} y {config.DRAFT_META_FILE}.",
            )
            log.warning("La carpeta elegida no tiene plantillas válidas: %s", drafts_dir)
            return

        self._drafts_dir = drafts_dir
        self._drafts_path_label.configure(text=str(drafts_dir), text_color=TEXT)

        names = [t.name for t in templates]
        self._template_menu.configure(values=names, state="normal")

        saved = self._user_config.get("last_template_name") or ""
        selected = names[0]
        if len(names) == 1:
            selected = names[0]
        elif saved in names:
            selected = saved
        self._template_var.set(selected)
        self._template_name = selected
        self._template_menu.configure(variable=self._template_var)

        if persist:
            self._save_user_config()
        log.info("Plantillas detectadas en drafts: %s", ", ".join(names))
        self._update_ui_state()

    def _on_template_changed(self, value: str) -> None:
        if value == NO_TEMPLATES:
            return
        self._template_name = value
        self._save_user_config()
        log.info("Plantilla seleccionada: %s", value)
        self._update_ui_state()

    # ---------------------------------------------- seccion 2 (video folder)
    def _browse_video(self) -> None:
        initial = str(self._video_dir) if self._video_dir else str(Path.home())
        path = filedialog.askdirectory(initialdir=initial)
        if not path:
            return
        self._apply_video_dir(Path(path), persist=True)

    def _apply_video_dir(self, video_dir: Path, persist: bool) -> None:
        self._video_dir = video_dir
        self._video_path_label.configure(text=str(video_dir), text_color=TEXT)

        self._detection = detect_video_inputs(video_dir, ask_scene=self._ask_scene_user)
        self._refresh_video_status()
        for warning in self._detection.warnings:
            log.info("Detección · %s", warning)

        self._refresh_srt_menu()

        if persist:
            self._save_user_config()
        self._update_ui_state()

    def _refresh_srt_menu(self) -> None:
        """Rellena el combo de .srt con lo encontrado en la carpeta del video
        (más los SRT de alineación del caché). Preserva la selección previa si
        el archivo sigue existiendo."""
        srt_files = self._scan_srt_files(self._video_dir)
        values = [NO_SRT] + [str(p) for p in srt_files]
        self._srt_menu.configure(values=values, state="normal" if values else "disabled")

        current = self._srt_name
        if current and self._srt_dir is not None:
            candidate = self._srt_dir / current
            if candidate.is_file() and str(candidate) in values:
                self._srt_var.set(str(candidate))
                self._srt_path_label.configure(text=str(candidate), text_color=TEXT)
                return
        self._srt_dir = None
        self._srt_name = ""
        self._srt_var.set(NO_SRT)
        self._srt_path_label.configure(text=NO_SRT, text_color=MUTED)

    def _on_srt_changed(self, value: str) -> None:
        if value == NO_SRT or not value:
            self._apply_srt_dir(None, persist=False)
            return
        srt = Path(value)
        if srt.is_file():
            self._apply_srt_dir(srt, persist=True)
        else:
            log.warning("El .srt elegido ya no existe: %s", value)
            self._refresh_srt_menu()

    def _ask_scene_user(self, candidates: list[Path]) -> Path | None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Elegir archivo de escenas")
        dialog.geometry("520x180")
        dialog.transient(self)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            dialog,
            text="Hay varios .txt de escenas con puntaje similar.\n¿Cuál quieres usar?",
            font=ctk.CTkFont(size=13), text_color=TEXT,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))
        var = ctk.StringVar(value=candidates[0].name)
        menu = ctk.CTkOptionMenu(
            dialog, values=[p.name for p in candidates], variable=var,
            height=30, corner_radius=8, fg_color="#2a2a2a",
            button_color="#334155", button_hover_color="#475569",
        )
        menu.grid(row=1, column=0, sticky="ew", padx=16, pady=4)
        result: dict[str, Path | None] = {"path": None}

        def _confirm() -> None:
            result["path"] = next(p for p in candidates if p.name == var.get())
            dialog.destroy()

        ctk.CTkButton(
            dialog, text="Usar este archivo", height=32, corner_radius=8,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, command=_confirm,
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(8, 12))
        dialog.wait_window()
        return result["path"]

    def _refresh_video_status(self) -> None:
        d = self._detection
        if d is None:
            self._paint_status(self._audio_status, False, "No se encontró")
            self._paint_status(self._scene_status, False, "No se encontró")
            self._paint_status(self._img_status, False, "No se encontró")
            self._status_footer.configure(text="")
            return

        if d.audio_path is not None:
            self._paint_status(self._audio_status, True, d.audio_path.name)
        else:
            self._paint_status(self._audio_status, False, "No se encontró archivo de audio")

        if d.scene_txt_path is not None:
            self._paint_status(
                self._scene_status, True,
                f"{d.scene_txt_path.name} ({d.scene_count} escenas)",
            )
        else:
            self._paint_status(self._scene_status, False, "No se encontró .txt de escenas")

        if d.images_dir is not None:
            shown = d.images_dir.name
            if d.images_dir == self._video_dir:
                shown = f"{self._video_dir.name} (raíz)" if self._video_dir else shown
            else:
                shown = f".\\{d.images_dir.name}"
            self._paint_status(self._img_status, True, f"{shown} ({len(d.image_paths)} archivos)")
        else:
            self._paint_status(self._img_status, False, "No se encontró carpeta de imágenes")

        if d.image_scene_mismatch:
            self._status_footer.configure(
                text=f"⚠ {len(d.image_paths)} imágenes vs {d.scene_count} escenas; "
                     "se pedirá decisión al generar.", text_color=AMBER)
        else:
            self._status_footer.configure(text="✓ Detección correcta", text_color=GREEN)

    def _on_edit_type_changed(self, value: str) -> None:
        if value == "Nexus Paradoja":
            self.name_entry.delete(0, "end")
            self.name_entry.insert(0, DEFAULT_PROJECT_NAME)
        log.info("Tipo de edición cambiado a: %s", value)

    def _status_label(self, parent, row, title):
        label = ctk.CTkLabel(
            parent, text="", font=ctk.CTkFont(size=12), text_color=MUTED,
            anchor="w", justify="left",
        )
        label._status_title = title
        label.grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 2))
        return label

    @staticmethod
    def _paint_status(label: ctk.CTkLabel, ok: bool, text: str) -> None:
        color = GREEN if ok else RED
        prefix = "✓" if ok else "✗"
        title = label._status_title  # type: ignore[attr-defined]
        label.configure(text=f"{prefix} {title}: {text}", text_color=color)

    # ------------------------------------------------------------- logs / hilo
    def _log_widget(self, line: str, level: str) -> None:
        self.log_box.configure(state="normal")
        tag = level if level in LOG_TAGS else "INFO"
        self.log_box.insert("end", line + "\n", (tag,))
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    def _poll_queue(self) -> None:
        for line in drain_queue(self.log_queue):
            level = "INFO"
            if "WARNING" in line:
                level = "WARNING"
            elif "ERROR" in line or "Traceback" in line:
                level = "ERROR"
            self._log_widget(line, level)

        if self._running and self._thread_done.is_set():
            was_cancelled = self.cancel_event.is_set()
            succeeded = self._job_succeeded
            self._running = False
            self.progress.stop()
            self.progress.set(0)
            self.cancel_event.clear()
            if was_cancelled:
                self._log_widget("⏹ Generación cancelada. Revisa los logs de arriba.", "WARNING")
            elif succeeded:
                self._log_widget("✔ Proceso terminado. Revisa los logs de arriba.", "OK")
                # TAREA 1: cartel verde "COMPLETADO" no bloqueante, se abre con
                # after() para no congelar el main thread (sin grab_set).
                self.after(150, self._show_success_modal)
            else:
                self._log_widget("✘ La generación falló. Revisa los logs de arriba.", "ERROR")
            self._update_ui_state()

        self.after(100, self._poll_queue)

    def _show_success_modal(self) -> None:
        """Cartel verde modal de éxito: #28a745, 'COMPLETADO' grande y botón '✕'
        arriba a la derecha. Se crea con after() y sin grab_set() para que no
        bloquee la ventana principal."""
        if self._success_modal is not None and self._success_modal.winfo_exists():
            self._success_modal.lift()
            return
        modal = ctk.CTkToplevel(self)
        self._success_modal = modal
        modal.title("Éxito")
        modal.geometry("420x210")
        modal.resizable(False, False)
        modal.configure(fg_color=SUCCESS)
        modal.transient(self)
        modal.after(100, modal.lift)

        # Botón "✕" arriba a la derecha (cierra sin bloquear nada).
        ctk.CTkButton(
            modal, text="✕", width=36, height=36, corner_radius=8,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#1e7e34", hover_color="#186a2b", text_color="#ffffff",
            command=modal.destroy,
        ).place(relx=1.0, x=-12, y=12, anchor="ne")

        modal.grid_rowconfigure(0, weight=1)
        modal.grid_rowconfigure(1, weight=1)
        modal.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            modal, text="COMPLETADO", font=ctk.CTkFont(size=34, weight="bold"),
            text_color="#ffffff",
        ).grid(row=0, column=0, sticky="s")
        ctk.CTkLabel(
            modal, text="¡PROYECTO GENERADO CON ÉXITO!",
            font=ctk.CTkFont(size=14, weight="bold"), text_color="#eafff0",
        ).grid(row=1, column=0, sticky="n", pady=(6, 0))
        self._center_modal(modal)

    @staticmethod
    def _center_modal(modal: ctk.CTkToplevel) -> None:
        try:
            modal.update_idletasks()
            w, h = 420, 210
            x = (modal.winfo_screenwidth() - w) // 2
            y = (modal.winfo_screenheight() - h) // 2
            modal.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------- generacion
    def _on_generate(self) -> None:
        if self._running:
            return
        detection = self._detection
        if detection is None or not detection.complete:
            messagebox.showwarning("CapCut Auto", "Debes seleccionar una carpeta de video válida.")
            return
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("CapCut Auto", "Debes escribir un nombre para el proyecto.")
            return

        template_dir = self._drafts_dir / self._template_name
        if not ((template_dir / config.DRAFT_CONTENT_FILE).is_file()
                and (template_dir / config.DRAFT_META_FILE).is_file()):
            messagebox.showerror("CapCut Auto", "La plantilla seleccionada no es válida.")
            return

        try:
            scenes = parse_scenes(detection.scene_txt_path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("CapCut Auto", f"Error al parsear escenas: {exc}")
            return
        if not scenes:
            messagebox.showerror("CapCut Auto", "El .txt de escenas no contiene ninguna escena.")
            return

        images = list(detection.image_paths)
        if len(images) != len(scenes):
            decision = self._resolve_image_mismatch(len(images), len(scenes))
            if decision is None:
                log.info("Generación abortada por el usuario (desajuste imágenes/escenas).")
                return
            images = decision

        self.cancel_event.clear()
        self._running = True
        self._thread_done.clear()
        self._job_succeeded = False
        self.generate_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.start()
        self._log_widget("▶ Iniciando generación en hilo secundario...", "INFO")

        data = {
            "template": template_dir,
            "name": name,
            "audio": detection.audio_path,
            "scenes_txt": detection.scene_txt_path,
            "images": images,
            "subtitle_srt": None,
        }
        if self._srt_name and self._srt_dir is not None:
            srt = self._srt_dir / self._srt_name
            if srt.is_file():
                data["subtitle_srt"] = srt
                log.info("Subtítulos: se generarán desde %s", srt)
        t = threading.Thread(target=self._run_job, args=(data,), daemon=True)
        t.start()

    def _resolve_image_mismatch(self, n_images: int, n_scenes: int) -> list[Path] | None:
        d = self._detection
        assert d is not None
        question = (
            f"Desajuste: {n_images} imágenes vs {n_scenes} escenas.\n\n"
            "¿Sí  → usar solo las primeras N imágenes.\n"
            "¿No  → duplicar la última imagen para cubrir las restantes.\n"
            "Cancelar → abortar la generación."
        )
        answer = messagebox.askyesnocancel("Desajuste imágenes ↔ escenas", question)
        images = list(d.image_paths)
        if answer is None:
            log.info("Desajuste imágenes/escenas: generación cancelada por el usuario.")
            return None
        if answer is True:
            images = images[:n_scenes]
            log.info("Desajuste imágenes/escenas: se usan solo las primeras %d imágenes.", n_scenes)
        else:
            last = images[-1]
            while len(images) < n_scenes:
                images.append(last)
            log.info(
                "Desajuste imágenes/escenas: última imagen (%s) duplicada hasta cubrir %d escenas.",
                last.name, n_scenes,
            )
        return images

    def _run_job(self, data: dict) -> None:
        try:
            log.info("== CapCut Auto — inicio de generación ==")
            log.info("Plantilla : %s", data["template"])
            log.info("Audio     : %s", data["audio"])
            log.info("Escenas   : %s", data["scenes_txt"])
            log.info("Imágenes  : %d archivos", len(data["images"]))
            log.info("Nombre    : %s", data["name"])

            if self.cancel_event.is_set():
                log.info("Generación cancelada por el usuario.")
                return

            scenes = parse_scenes(data["scenes_txt"])
            align_lines = [s.key_text for s in scenes if s.key_text.strip()]

            log.info("Paso 1/5 — Preparando alineación (CrispASR + modelo español)...")
            srt_path = config.CACHE_DIR / f"alineacion_{Path(data['audio']).stem}.srt"
            aligned = align_audio_to_text(
                data["audio"], align_lines, srt_path, cancel_event=self.cancel_event)
            if self.cancel_event.is_set():
                log.info("Generación cancelada por el usuario.")
                return
            cues = parse_srt(aligned)
            log.info("Alineación completada: %d cues (%d líneas).",
                     len(cues), len(align_lines))

            total_us = max((int(round(end * 1_000_000)) for _s, end, _t in cues), default=0)
            log.info("Duración total del audio: %d us (%s s).", total_us, f"{total_us / 1e6:.2f}")

            log.info("Paso 2/5 — Sincronizando escenas con el SRT alineado...")
            items, _seg_total_us = build_timeline(
                scenes, aligned, data["images"], cancel_event=self.cancel_event)
            ok_items = sum(1 for it in items if it.is_synced)
            log.info("Escenas sincronizadas: %d/%d.", ok_items, len(items))

            log.info("Paso 3/5 — Preparando proyecto CapCut (clone + edit)...")
            project = CapCutProject(data["template"])
            project.backup_originals()
            project.dump_schema()

            log.info("Paso 4/5 — Generando proyecto...")
            out = project.generate(
                data["name"], items, data["audio"], total_us,
                cancel_event=self.cancel_event,
                subtitle_srt=data.get("subtitle_srt"),
            )

            log.info("Paso 5/5 — ✔ Proyecto creado en: %s", out)
            log.info("IMPORTANTE: cierra la app antes de abrir CapCut.")
            self._job_succeeded = True
        except GenerationCancelled:
            log.info("Generación cancelada por el usuario.")
        except Exception:  # noqa: BLE001
            if self.cancel_event.is_set():
                log.info("Generación cancelada por el usuario.")
            else:
                log.error("FALLO durante la generación:")
                log.error(traceback.format_exc())
        finally:
            self._thread_done.set()

    def _on_cancel(self) -> None:
        if not self._running:
            return
        log.info("Cancelación solicitada por el usuario...")
        self.cancel_btn.configure(state="disabled")
        self.cancel_event.set()


def launch() -> None:
    config.ensure_dirs()
    log_queue: queue.Queue = queue.Queue()
    setup_logging(log_queue, config.APP_LOG_FILE)
    log.info("CapCut Auto iniciado.")
    log.info("Los proyectos se generarán en la carpeta de la plantilla elegida.")
    app = MainWindow(log_queue)
    app.mainloop()