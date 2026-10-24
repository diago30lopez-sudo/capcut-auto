"""Ventana principal de CapCut Auto con CustomTkinter.UI con 7 campos + barra de perfiles arriba. Todo el procesamientocorre en un threading.Thread; los logs llegan por una cola (QueueHandler)y la UI los consume con after(). El botón Cancelar setea unthreading.Event compartido con el hilo de trabajo."""
from __future__ import annotations
import logging
import queue
import threading
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk
from src.core import config
from src.core.auto_detect import (
    DetectionResult, detect_video_inputs, find_capcut_templates, detect_audios,
)
from src.core.bootstrap import ensure_dependencies
from src.core.capcut_project import CapCutProject
from src.core.config import load_user_config, save_user_config
from src.core.profile_loader import load_profiles, get_profile, get_profile_names
from src.core.scene_parser import parse_scenes
from src.core.timeline_builder import GenerationCancelled, build_timeline, parse_srt
from src.core.transcriber import transcribe_audio_free, align_audio_to_text
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
SUCCESS = "#28a745"
NO_TEMPLATES = "— sin plantillas —"
NO_SRT = "— sin subtítulos (.srt) —"
EDIT_TYPES = []
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
        self._srt_dir: Path | None = None
        self._srt_name: str = ""
        self._audio_guion: Path | None = None
        self._audio_otros: list[Path] = []
        self._excluded_paths: list[Path] = []
        self._exclusion_labels: list[ctk.CTkLabel] = []
        self._profiles: dict[str, dict] = {}
        self._profile_id: str = self._user_config.get("last_profile_name", "") or ""
        self._profile_name: str = ""
        self._profiles_dir: Path = Path(config.profiles_dir())
        saved_pd = self._user_config.get("profiles_dir", "")
        if saved_pd and Path(saved_pd).is_dir():
            self._profiles_dir = Path(saved_pd)
        self._assets_frame: ctk.CTkFrame | None = None
        self._dyc_assets_dir: Path | None = None
        saved_dyc = self._user_config.get("dyc_assets_dir", "")
        if saved_dyc and Path(saved_dyc).is_dir():
            self._dyc_assets_dir = Path(saved_dyc)
        self._name_edited_by_user: dict[str, bool] = {}
        self.title("CapCut Auto")
        self.configure(fg_color=BG)
        self._center(920, 780)
        ctk.set_appearance_mode("dark")
        self._build_ui()
        self.after(100, self._poll_queue)
        self.after(200, self._restore_session)
        self.after(300, self._load_exclusions_from_config)
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
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header, text="CapCut Auto",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Genera un proyecto de CapCut con imágenes sincronizadas al audio",
            font=ctk.CTkFont(size=12), text_color=MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(0, 4))
        self._profiles_dir_label = ctk.CTkLabel(
            header, text=str(self._profiles_dir),
            font=ctk.CTkFont(size=11), text_color=MUTED, anchor="e",
        )
        self._profiles_dir_label.grid(row=0, column=1, sticky="ew", padx=(16, 0), pady=(8, 0))
        ctk.CTkButton(
            header, text="📁", width=36, height=28, corner_radius=6,
            fg_color="#334155", hover_color="#475569",
            command=self._browse_profiles_dir,
        ).grid(row=0, column=2, sticky="e", padx=(4, 0), pady=(8, 0))
        ctk.CTkButton(
            header, text="🔄", width=36, height=28, corner_radius=6,
            fg_color="#334155", hover_color="#475569",
            command=self._reload_profiles,
        ).grid(row=0, column=3, sticky="e", padx=(4, 0), pady=(8, 0))
        splitter = ctk.CTkFrame(self, fg_color=BG)
        splitter.grid(row=2, column=0, sticky="nsew", padx=24, pady=(2, 16))
        splitter.grid_columnconfigure(0, weight=3)
        splitter.grid_columnconfigure(1, weight=4)
        splitter.grid_rowconfigure(0, weight=1)
        left_outer = ctk.CTkScrollableFrame(splitter, fg_color=BG, corner_radius=0)
        left_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)
        left_outer.grid_columnconfigure(0, weight=1)
        self._build_section1_drafts(left_outer, row=0)
        self._build_section2_video(left_outer, row=1)
        self._build_section3_profile(left_outer, row=2)
        self._build_section_subtitles(left_outer, row=3)
        self._build_section5_assets(left_outer, row=4)
        self._build_section_audio(left_outer, row=5)
        self._build_section7_name(left_outer, row=6)
        buttons_frame = ctk.CTkFrame(left_outer, fg_color=BG)
        buttons_frame.grid(row=8, column=0, sticky="ew", padx=0, pady=(10, 4))
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
        self.progress.grid(row=9, column=0, sticky="ew", padx=0, pady=(6, 12))
        self.progress.set(0)
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
    def _resolve_audio_path(self, display_name: str) -> Path | None:
        if not display_name or display_name == "— sin detectar —":
            return None
        if not self._video_dir:
            return None
        val_lower = display_name.lower()
        for p in self._video_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in config.AUDIO_EXTENSIONS:
                if p.name.lower() == val_lower or p.stem.lower() == Path(display_name).stem.lower():
                    return p.resolve()
        return None
    def _build_section1_drafts(self, parent, row: int) -> None:
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=row, column=0, sticky="ew", padx=0, pady=6)
        panel.grid_columnconfigure(1, weight=1)
        self._section_title(panel, "1 · Draft / Plantilla").grid(
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
        self._section_title(panel, "2 · Carpeta del Video").grid(
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
        ctk.CTkLabel(
            panel, text="Excluir del escaneo:",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT,
        ).grid(row=6, column=0, sticky="w", padx=12, pady=(4, 2))
        self._add_exclusion_btn = ctk.CTkButton(
            panel, text="Añadir exclusión... ▾", width=180, height=28,
            corner_radius=8, fg_color="#334155", hover_color="#475569",
            command=self._show_add_exclusion_menu,
        )
        self._add_exclusion_btn.grid(row=7, column=0, sticky="w", padx=12, pady=(0, 2))
        self._exclusion_list_frame = ctk.CTkFrame(
            panel, fg_color="#1a1a1a", corner_radius=6, height=80)
        self._exclusion_list_frame.grid(
            row=8, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 6))
        self._exclusion_list_frame.grid_columnconfigure(0, weight=1)
        self._exclusion_scroll = ctk.CTkScrollableFrame(
            self._exclusion_list_frame, fg_color="#1a1a1a")
        self._exclusion_scroll.grid(
            row=0, column=0, sticky="nsew", padx=4, pady=4)
        self._exclusion_scroll.grid_columnconfigure(0, weight=1)
        self._exclusion_scroll.grid_rowconfigure(0, weight=1)
        self._exclusion_widgets: list[ctk.CTkLabel] = []
        self._exclusion_placeholder = ctk.CTkLabel(
            self._exclusion_scroll, text="Sin exclusiones",
            font=ctk.CTkFont(size=11), text_color=MUTED, anchor="w",
        )
        self._exclusion_placeholder.grid(row=0, column=0, sticky="w", padx=4, pady=2)
    def _build_section_subtitles(self, parent, row: int) -> None:
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=row, column=0, sticky="ew", padx=0, pady=6)
        panel.grid_columnconfigure(1, weight=1)
        self._section_title(panel, "4 · Subtítulos (.srt)").grid(
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
    def _build_section_audio(self, parent, row: int) -> None:
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=row, column=0, sticky="ew", padx=0, pady=6)
        panel.grid_columnconfigure(1, weight=1)
        self._section_title(panel, "6 · Audio del proyecto").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 4))
        ctk.CTkLabel(
            panel, text="Audio guion (narración principal):",
            font=ctk.CTkFont(size=12), text_color=TEXT,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 4))
        self._audio_guion_var = ctk.StringVar(value="— sin detectar —")
        self._audio_guion_menu = ctk.CTkOptionMenu(
            panel, values=["— sin detectar —"], variable=self._audio_guion_var,
            height=30, corner_radius=8, state="disabled",
            fg_color="#2a2a2a", button_color="#334155",
            button_hover_color="#475569",
            command=self._on_audio_guion_changed,
        )
        self._audio_guion_menu.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 6))
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
        self._profiles_dir = Path(self._user_config.get("profiles_dir", str(config.profiles_dir())))
        self._profiles_dir_label.configure(text=str(self._profiles_dir), text_color=TEXT)
        self._load_profiles_ui()
        self._update_ui_state()
    def _load_exclusions_from_config(self) -> None:
        from src.core.auto_detect import _load_excluded_paths as _load_exc
        raw = _load_exc()
        valid: list[Path] = []
        for p in raw:
            if p.is_file() or p.is_dir():
                valid.append(p)
        self._excluded_paths = valid
        self._render_exclusion_list()
    @staticmethod
    def _is_excluded_ui(path: Path, excluded: list[Path]) -> bool:
        import os
        if not excluded:
            return False
        norm_path = os.path.normcase(os.path.abspath(path))
        for exc in excluded:
            norm_exc = os.path.normcase(os.path.abspath(exc))
            if norm_path == norm_exc:
                return True
            if norm_path.startswith(norm_exc + os.sep):
                return True
        return False
    def _build_section3_profile(self, parent, row: int) -> None:
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=row, column=0, sticky="ew", padx=0, pady=6)
        panel.grid_columnconfigure(0, weight=1)
        self._section_title(panel, "3 · Perfil de edición").grid(
            row=0, column=0, sticky="w", padx=12, pady=(8, 4))
        self._profile_var = ctk.StringVar(value="")
        self._profile_menu = ctk.CTkOptionMenu(
            panel, values=[], variable=self._profile_var,
            height=32, corner_radius=8,
            fg_color="#2a2a2a", button_color=ACCENT, button_hover_color=ACCENT_HOVER,
            command=self._on_profile_changed,
        )
        self._profile_menu.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        self._load_profiles_ui()
    def _load_profiles_ui(self) -> None:
        from src.core.profile_loader import load_profiles, get_profile_names
        try:
            self._profiles = load_profiles(self._profiles_dir)
        except Exception as exc:
            log.warning("Error cargando perfiles: %s", exc)
            self._profiles = {}
        names = get_profile_names(self._profiles)
        if not names:
            log.warning("No se encontraron perfiles en %s. Añade archivos .json o cambia la carpeta.", self._profiles_dir)
        self._profile_menu.configure(values=names, state="normal" if names else "disabled")
        saved_id = self._user_config.get("last_profile_name", "")
        selected_name = ""
        for pid, data in self._profiles.items():
            meta = data.get("meta", {})
            if meta.get("id") == saved_id or pid == saved_id:
                selected_name = meta.get("name", pid)
                break
        if selected_name and selected_name in names:
            self._profile_var.set(selected_name)
            self._profile_id = saved_id
            self._profile_name = selected_name
        else:
            default_name = "Nexus Paradoja"
            if default_name in names:
                self._profile_var.set(default_name)
                for pid, data in self._profiles.items():
                    if data.get("meta", {}).get("name") == default_name:
                        self._profile_id = pid
                        self._profile_name = default_name
                        break
            elif names:
                self._profile_var.set(names[0])
                self._profile_id = next(iter(self._profiles.keys()))
                self._profile_name = names[0]
        self._update_assets_visibility()
    def _reload_profiles(self) -> None:
        self._load_profiles_ui()
        log.info("Perfiles recargados desde %s", self._profiles_dir)
    def _browse_profiles_dir(self) -> None:
        initial = str(self._profiles_dir)
        path = filedialog.askdirectory(initialdir=initial)
        if not path:
            return
        p = Path(path)
        if not p.is_dir():
            messagebox.showerror("CapCut Auto", f"La carpeta '{path}' no existe.")
            return
        self._profiles_dir = p.resolve()
        self._profiles_dir_label.configure(text=str(self._profiles_dir), text_color=TEXT)
        self._user_config["profiles_dir"] = str(self._profiles_dir)
        self._save_user_config()
        self._load_profiles_ui()
        log.info("Carpeta de perfiles cambiada a: %s", self._profiles_dir)
    def _update_assets_visibility(self) -> None:
        pass
    def _on_profile_changed(self, value: str) -> None:
        for pid, data in self._profiles.items():
            meta = data.get("meta", {})
            if meta.get("name") == value or pid == value:
                self._profile_id = pid
                self._profile_name = value
                break
        self._user_config["last_profile_name"] = self._profile_id
        self._save_user_config()
        log.info("Perfil cambiado a: %s (%s)", value, self._profile_id)
        self._name_edited_by_user[self._profile_id] = False
        self._update_project_name_suffix()
        self._update_assets_visibility()

    def _update_project_name_suffix(self) -> None:
        if self._profile_id in self._profiles:
            pdata = self._profiles[self._profile_id]
            default_name = pdata.get("meta", {}).get("default_project_name", "")
            if not default_name:
                default_name = pdata.get("project_name_suffix", "")
            if default_name:
                current = self.name_entry.get().strip()
                if not self._name_edited_by_user.get(self._profile_id, False):
                    self.name_entry.delete(0, "end")
                    self.name_entry.insert(0, default_name)
    def _build_section5_assets(self, parent, row: int) -> None:
        self._assets_frame = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        self._assets_frame.grid(row=row, column=0, sticky="ew", padx=0, pady=6)
        self._assets_frame.grid_columnconfigure(1, weight=1)
        self._section_title(self._assets_frame, "5 · Carpeta de assets").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 4))
        ctk.CTkButton(
            self._assets_frame, text="Seleccionar carpeta…", width=180, height=30,
            corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._browse_assets_dir,
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 4))
        self._assets_dir_label = ctk.CTkLabel(
            self._assets_frame, text="Sin seleccionar", font=ctk.CTkFont(size=12),
            text_color=MUTED, anchor="w", justify="left",
        )
        self._assets_dir_label.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 4))
    def _browse_assets_dir(self) -> None:
        initial = str(self._dyc_assets_dir) if self._dyc_assets_dir else str(Path.home())
        path = filedialog.askdirectory(initialdir=initial)
        if not path:
            return
        p = Path(path)
        if not p.is_dir():
            messagebox.showerror("CapCut Auto", f"La carpeta '{path}' no existe.")
            return
        self._dyc_assets_dir = p.resolve()
        self._assets_dir_label.configure(text=str(self._dyc_assets_dir), text_color=TEXT)
        self._save_user_config()
        log.info("Carpeta de assets seleccionada: %s", self._dyc_assets_dir)
    def _on_name_key_release(self) -> None:
        text = self.name_entry.get().strip()
        self._name_edited_by_user[self._profile_id] = bool(text)
        if not text:
            if self._profile_id in self._profiles:
                pdata = self._profiles[self._profile_id]
                default_name = pdata.get("meta", {}).get("default_project_name", "")
                if not default_name:
                    default_name = pdata.get("project_name_suffix", "")
                if default_name:
                    self.name_entry.delete(0, "end")
                    self.name_entry.insert(0, default_name)
                self._name_edited_by_user[self._profile_id] = False
        self._update_ui_state()
    def _build_section7_name(self, parent, row: int) -> None:
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=row, column=0, sticky="ew", padx=0, pady=6)
        panel.grid_columnconfigure(0, weight=1)
        self._section_title(panel, "7 · Nombre del proyecto").grid(
            row=0, column=0, sticky="w", padx=12, pady=(8, 4))
        self.name_entry = ctk.CTkEntry(
            panel, placeholder_text="ej. mi_video_diapositivas", height=34,
            corner_radius=8, fg_color="#2a2a2a", text_color=TEXT,
        )
        self.name_entry.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        self.name_entry.bind("<KeyRelease>", lambda _e: self._on_name_key_release())
        self.name_entry.delete(0, "end")
        if self._profile_id in self._profiles:
            pdata = self._profiles[self._profile_id]
            default_name = pdata.get("meta", {}).get("default_project_name", "")
            if not default_name:
                default_name = pdata.get("project_name_suffix", "")
            if default_name:
                self.name_entry.insert(0, default_name)
    def _save_user_config(self) -> None:
        self._user_config["capcut_drafts_dir"] = str(self._drafts_dir) if self._drafts_dir else ""
        self._user_config["last_template_name"] = self._template_name or ""
        self._user_config["last_video_dir"] = str(self._video_dir) if self._video_dir else ""
        self._user_config["last_srt_dir"] = str(self._srt_dir) if self._srt_dir else ""
        self._user_config["last_srt_name"] = self._srt_name or ""
        self._user_config["last_guion_name"] = self._user_config.get("last_guion_name", "")
        self._user_config["last_profile_name"] = self._profile_id or ""
        self._user_config.pop("last_edit_type", None)
        self._user_config["excluded_paths"] = ",".join(str(p) for p in self._excluded_paths)
        self._user_config["profiles_dir"] = str(self._profiles_dir)
        self._user_config["dyc_assets_dir"] = str(self._dyc_assets_dir) if self._dyc_assets_dir else ""
        save_user_config(self._user_config)

    def _scan_srt_files(self, folder: Path) -> list[Path]:
        found: set[Path] = set()
        if folder is not None and folder.is_dir():
            found.update(folder.rglob("*.srt"))
        cache = Path(config.CACHE_DIR)
        if cache.is_dir():
            found.update(cache.glob("alineacion_*.srt"))
        return sorted(found, key=lambda p: p.name.lower())
    def _apply_srt_dir(self, srt: Path | None, persist: bool) -> None:
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
        self._refresh_audio_menu()
        if persist:
            self._save_user_config()
        self._update_ui_state()
    def _refresh_srt_menu(self) -> None:
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
    def _refresh_audio_menu(self) -> None:
        if not self._video_dir:
            self._audio_guion_menu.configure(values=["— sin detectar —"], state="disabled")
            self._audio_guion_var.set("— sin detectar —")
            self._audio_guion = None
            self._audio_otros = []
            return
        all_audios = [
            p for p in self._video_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in config.AUDIO_EXTENSIONS
            and not any(self._is_excluded_ui(p, [exc]) for exc in self._excluded_paths)
        ]
        all_audios.sort(key=lambda p: p.name.lower())
        saved_name = self._user_config.get("last_guion_name", "")
        if saved_name:
            selected_name = saved_name
        else:
            selected_name = all_audios[0].name if all_audios else "— sin detectar —"
        selected_path = self._resolve_audio_path(selected_name) if selected_name != "— sin detectar —" else None
        if selected_path is not None:
            self._audio_guion = selected_path
            self._audio_otros = [p for p in all_audios if p != selected_path]
        else:
            self._audio_guion = None
            self._audio_otros = all_audios[:]
        if all_audios:
            dropdown_values = [p.name for p in all_audios]
        else:
            dropdown_values = ["— sin detectar —"]
        self._audio_guion_menu.configure(
            values=dropdown_values,
            state="normal" if dropdown_values != ["— sin detectar —"] else "disabled",
        )
        if self._audio_guion is not None:
            self._audio_guion_var.set(self._audio_guion.name)
        elif all_audios:
            self._audio_guion_var.set(all_audios[0].name)
        else:
            self._audio_guion_var.set("— sin detectar —")
    def _on_audio_guion_changed(self, value: str) -> None:
        if not value or value == "— sin detectar —":
            self._audio_guion = None
            self._user_config["last_guion_name"] = ""
            self._save_user_config()
            return
        audio_path = self._resolve_audio_path(value)
        if audio_path is not None:
            self._audio_guion = audio_path
            self._user_config["last_guion_name"] = audio_path.name
            self._save_user_config()
            log.info("Audio guion seleccionado: %s", audio_path.name)
            if self._video_dir:
                all_audios = [
                    p for p in self._video_dir.rglob("*")
                    if p.is_file() and p.suffix.lower() in config.AUDIO_EXTENSIONS
                    and not self._is_excluded_ui(p, self._excluded_paths)
                ]
                all_audios.sort(key=lambda p: p.name.lower())
                self._audio_otros = [p for p in all_audios if p != audio_path]
        else:
            log.warning("Audio guion no encontrado: %s", value)

    def _load_exclusions(self) -> None:
        from src.core.auto_detect import _load_excluded_paths as _load_exc
        raw = _load_exc()
        valid: list[Path] = []
        for p in raw:
            if p.is_file() or p.is_dir():
                valid.append(p)
            else:
                log.info("Exclusión inexistente omitida: %s", p)
        self._excluded_paths = valid
        self._render_exclusion_list()
        if self._audio_guion and self._excluded_paths:
            import os
            norm = os.path.normcase(os.path.abspath(self._audio_guion))
            for exc in self._excluded_paths:
                if norm == os.path.normcase(os.path.abspath(exc)) or \
                   norm.startswith(os.path.normcase(os.path.abspath(exc)) + os.sep):
                    self._audio_guion = None
                    self._user_config["last_guion_name"] = ""
                    self._save_user_config()
                    self._refresh_audio_menu()
                    break
    def _render_exclusion_list(self) -> None:
        for w in self._exclusion_widgets:
            w.destroy()
        self._exclusion_widgets.clear()
        if not self._excluded_paths:
            self._exclusion_placeholder.configure(text="Sin exclusiones")
            self._exclusion_placeholder.grid()
            return
        self._exclusion_placeholder.grid_remove()
        for i, p in enumerate(self._excluded_paths):
            row = i
            label = ctk.CTkLabel(
                self._exclusion_scroll,
                text=f"  {p.name if p.is_file() else '📁 '}{p.name}",
                font=ctk.CTkFont(size=11), text_color=TEXT, anchor="w",
            )
            label.grid(row=row, column=0, sticky="w", padx=4, pady=1)
            remove_btn = ctk.CTkButton(
                self._exclusion_scroll, text="✕", width=24, height=24,
                corner_radius=6, fg_color="#7f1d1d", hover_color="#991b1b",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#fca5a5",
                command=lambda pp=p: self._remove_exclusion(pp),
            )
            remove_btn.grid(row=row, column=1, padx=(4, 4), pady=1)
            self._exclusion_widgets.append(label)
            self._exclusion_widgets.append(remove_btn)
    def _show_add_exclusion_menu(self) -> None:
        menu = ctk.CTkToplevel(self)
        menu.title("Añadir exclusión")
        menu.geometry("220x100")
        menu.resizable(False, False)
        menu.configure(fg_color=PANEL)
        menu.transient(self)
        menu.grab_set()
        def _add_file() -> None:
            path = filedialog.askopenfilename(
                initialdir=self._video_dir or Path.home(),
                title="Seleccionar archivo para excluir",
            )
            if path:
                self._add_exclusion(Path(path))
            menu.destroy()
        def _add_folder() -> None:
            path = filedialog.askdirectory(
                initialdir=self._video_dir or Path.home(),
                title="Seleccionar carpeta para excluir",
            )
            if path:
                self._add_exclusion(Path(path))
            menu.destroy()
        ctk.CTkButton(
            menu, text="Seleccionar archivo…", height=34, corner_radius=8,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=_add_file,
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        ctk.CTkButton(
            menu, text="Seleccionar carpeta…", height=34, corner_radius=8,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=_add_folder,
        ).grid(row=1, column=0, sticky="ew", padx=16, pady=(6, 12))
        menu.grid_columnconfigure(0, weight=1)
        menu.wait_window()
    def _add_exclusion(self, path: Path) -> None:
        abs_path = path.resolve()
        if abs_path in self._excluded_paths:
            return
        self._excluded_paths.append(abs_path)
        self._save_user_config()
        self._render_exclusion_list()
        log.info("[EXCLUSION] Añadido: %s", abs_path)
        if self._video_dir is not None:
            self._apply_video_dir(self._video_dir, persist=False)
    def _remove_exclusion(self, path: Path) -> None:
        abs_path = path.resolve()
        if abs_path in self._excluded_paths:
            self._excluded_paths.remove(abs_path)
            self._save_user_config()
            self._render_exclusion_list()
            log.info("[EXCLUSION] Eliminado: %s", abs_path)
            if self._video_dir is not None:
                self._apply_video_dir(self._video_dir, persist=False)
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
    @staticmethod
    def _status_label(parent, row, title):
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
        title = label._status_title
        label.configure(text=f"{prefix} {title}: {text}", text_color=color)
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
                self.after(150, self._show_success_modal)
            else:
                self._log_widget("✘ La generación falló. Revisa los logs de arriba.", "ERROR")
            self._update_ui_state()
        self.after(100, self._poll_queue)
    def _show_success_modal(self) -> None:
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
        except Exception:
            pass

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
        except Exception as exc:
            messagebox.showerror("CapCut Auto", f"Error al parsear escenas: {exc}")
            return
        if not scenes:
            messagebox.showerror("CapCut Auto", "El .txt de escenas no contiene ninguna escena.")
            return
        if self._dyc_assets_dir is not None:
            meta = self._profiles.get(self._profile_id, {}).get("meta", {})
            if not meta.get("requires_assets", False):
                log.info(
                    "Carpeta de assets seleccionada pero el perfil '%s' no la requiere; se ignora.",
                    self._profile_name,
                )
        images = list(detection.image_paths)
        if len(images) != len(scenes):
            decision = self._resolve_image_mismatch(len(images), len(scenes))
            if decision is None:
                log.info("Generación abortada por el usuario (desajuste imágenes/escenas).")
                return
            images = decision
        audio_path = self._audio_guion or (self._detection.audio_path if self._detection and self._detection.audio_path else None)
        if audio_path is None:
            messagebox.showerror(
                "CapCut Auto",
                "No hay audio de guion seleccionado ni detectado.\n\n"
                "Asegúrate de:\n"
                "1. Que exista un archivo de audio en la carpeta del video, o\n"
                "2. Selecciona un audio en el bloque '6. Audio del proyecto'."
            )
            return
        data = {
            "template": template_dir,
            "name": name,
            "audio": audio_path,
            "scenes_txt": detection.scene_txt_path,
            "images": images,
            "subtitle_srt": None,
        }
        if self._srt_name and self._srt_dir is not None:
            srt = self._srt_dir / self._srt_name
            if srt.is_file():
                data["subtitle_srt"] = srt
                log.info("Subtítulos: se usarán los subtítulos del usuario: %s", srt)
        else:
            log.info("Subtítulos: ningún SRT seleccionado; se usará transcripción interna.")
        self.cancel_event.clear()
        self._running = True
        self._thread_done.clear()
        self._job_succeeded = False
        self.generate_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.start()
        self._log_widget("▶ Iniciando generación en hilo secundario...", "INFO")
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
            log.info("Audio     : %s  (seleccionado: %s)", data["audio"], getattr(self._audio_guion, 'name', 'auto'))
            log.info("Escenas   : %s", data["scenes_txt"])
            log.info("Imágenes  : %d archivos", len(data["images"]))
            log.info("Nombre    : %s", data["name"])
            if self.cancel_event.is_set():
                log.info("Generación cancelada por el usuario.")
                return
            scenes = parse_scenes(data["scenes_txt"])
            if data.get("subtitle_srt") and Path(data["subtitle_srt"]).is_file():
                log.info("Paso 1/5 — Usando SRT del usuario: %s", data["subtitle_srt"])
                aligned = Path(data["subtitle_srt"])
            else:
                align_lines = [s.key_text for s in scenes if s.key_text.strip()]
                if align_lines:
                    log.info("Paso 1/5 — Alineación con guion (%d líneas) via CrispASR...", len(align_lines))
                    srt_path = config.CACHE_DIR / f"alineacion_{Path(data['audio']).stem}.srt"
                    aligned = align_audio_to_text(
                        data["audio"], align_lines, srt_path,
                        cancel_event=self.cancel_event,
                    )
                else:
                    log.info("Paso 1/5 — Transcripción libre (sin guion disponible)...")
                    srt_path = config.CACHE_DIR / f"alineacion_{Path(data['audio']).stem}.srt"
                    aligned = transcribe_audio_free(
                        data["audio"], srt_path,
                        cancel_event=self.cancel_event,
                    )
            if self.cancel_event.is_set():
                log.info("Generación cancelada por el usuario.")
                return
            cues = parse_srt(aligned)
            log.info("Alineación completada: %d cues (%d escenas).",
                     len(cues), len(scenes))
            from src.core.timeline_builder import measure_audio_duration_us
            audio_dur_us = measure_audio_duration_us(data["audio"])
            if audio_dur_us is None:
                audio_dur_us = max((int(round(end * 1_000_000)) for _s, end, _t in cues), default=0)
            total_us = audio_dur_us
            log.info("Duración total del audio: %d us (%s s).", total_us, f"{total_us / 1e6:.2f}")
            log.info("Paso 2/5 — Sincronizando escenas con el SRT transcrito...")
            from src.core.profile_loader import build_edit_profile
            profile_data = self._profiles.get(self._profile_id, {})
            edit_profile = build_edit_profile(profile_data)
            if self._dyc_assets_dir is not None:
                import dataclasses
                edit_profile = dataclasses.replace(edit_profile, dyc_assets_dir=str(self._dyc_assets_dir))
            match_threshold = getattr(edit_profile, 'match_threshold', 75.0)
            min_duration_us = getattr(edit_profile, 'min_duration_us', 33333)
            items, _seg_total_us = build_timeline(
                scenes, aligned, data["images"], cancel_event=self.cancel_event,
                match_threshold=match_threshold, min_duration_us=min_duration_us,
            )
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
                subtitle_srt=data.get("subtitle_srt") or aligned,
                edit_profile=edit_profile,
            )
            log.info("Paso 5/5 — ✔ Proyecto creado en: %s", out)
            log.info("IMPORTANTE: cierra la app antes de abrir CapCut.")
            self._job_succeeded = True
        except GenerationCancelled:
            log.info("Generación cancelada por el usuario.")
        except Exception:
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


def _bootstrap_dependencies() -> None:
    """Hilo de fondo: comprueba y descarga (si falta) CrispASR + modelo español
    en el primer uso. No debe lanzar excepciones al hilo (log unicamente)."""
    try:
        ensure_dependencies()
    except Exception:
        log.error("No se pudieron comprobar/descargar las dependencias en el arranque:")
        log.error(traceback.format_exc())


def launch() -> None:
    config.ensure_dirs()
    log_queue: queue.Queue = queue.Queue()
    setup_logging(log_queue, config.APP_LOG_FILE)
    log.info("CapCut Auto iniciado.")
    log.info("Los proyectos se generarán en la carpeta de la plantilla elegida.")
    threading.Thread(
        target=_bootstrap_dependencies, daemon=True,
        name="bootstrap-deps",
    ).start()
    app = MainWindow(log_queue)
    app.mainloop()
