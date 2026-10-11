"""Orquestador del pipeline de generación de proyectos CapCut.

Conecta config → loader → schema → generación del proyecto.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.core import config
from src.core.profile_loader import get_profile, load_profiles

log = logging.getLogger("capcutauto")


def get_current_profile(
    profiles_dir: str | Path | None = None,
    dyc_assets_dir: str | None = None,
):
    """Carga los perfiles y devuelve el perfil activo según config_user.json."""
    if profiles_dir is None:
        profiles_dir = config.profiles_dir()

    profiles = load_profiles(profiles_dir, dyc_assets_dir=dyc_assets_dir)
    if not profiles:
        log.warning("No hay perfiles disponibles.")
        return profiles, None, None

    user_config = config.load_user_config()
    active_id = user_config.get("last_profile_name", "")
    if not active_id:
        active_id = next(iter(profiles.keys()))
        log.info("No hay perfil activo guardado; usando '%s'.", active_id)
    elif active_id not in profiles:
        log.warning("El perfil activo '%s' no existe; usando el primero disponible.", active_id)
        active_id = next(iter(profiles.keys()))

    active_profile = get_profile(profiles, active_id)
    return profiles, active_profile, active_id


def generate_project(
    template_dir: Path,
    project_name: str,
    items,
    audio_path,
    audio_duration_us: int,
    cancel_event=None,
    subtitle_srt=None,
    profiles_dir: str | Path | None = None,
    dyc_assets_dir: str | None = None,
    profile_name: str | None = None,
    allow_test_names: bool = False,
):
    """Genera un proyecto CapCut usando el perfil especificado."""
    from src.core.capcut_project import CapCutProject

    profiles, active_profile, _ = get_current_profile(profiles_dir, dyc_assets_dir=dyc_assets_dir)

    if profile_name:
        profile_data = get_profile(profiles, profile_name)
    else:
        profile_data = active_profile
        if profile_data is None:
            raise RuntimeError("No hay perfiles disponibles.")

    from src.core.profile_loader import build_edit_profile
    edit_profile = build_edit_profile(profile_data)

    project = CapCutProject(template_dir)
    project.backup_originals()
    project.dump_schema()

    out = project.generate(
        project_name,
        items,
        audio_path,
        audio_duration_us,
        cancel_event=cancel_event,
        subtitle_srt=subtitle_srt,
        edit_profile=edit_profile,
        allow_test_names=allow_test_names,
    )

    log.info("Proyecto creado en: %s", out)
    log.info("IMPORTANTE: cierra la app antes de abrir CapCut.")
    return out
