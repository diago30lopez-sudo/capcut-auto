# Ronda 8 — Reversión Total al Estado Pre-Ronda-8

**Fecha:** 2026-10-08  
**Estado:** Reversión completa ejecutada y verificada

---

## ORDEN DEL USUARIO

> "Revierte TODA la configuración de la app hasta antes de donde empezamos a arreglar lo de que no cargaba los assets. Ahora mismo ejecuta eso: que vire hacia esa versión. Nada más. Después vemos qué hacer."

---

## ACCIÓN EJECUTADA

Se revirtieron **todos** los archivos fuente modificados durante la Ronda 8 al estado exacto del commit `0f7d689` (HEAD), que es el estado pre-Ronda-8.

### Archivos revertidos a HEAD

| Archivo | Método | Estado |
|---------|--------|--------|
| `src/core/timeline_builder.py` | `git checkout HEAD --` | ✅ IDÉNTICO a HEAD |
| `src/core/capcut_project.py` | `git checkout HEAD --` | ✅ IDÉNTICO a HEAD |
| `src/ui/main_window.py` | `git checkout HEAD --` | ✅ IDÉNTICO a HEAD |
| `src/core/subtitles.py` | `git checkout HEAD --` | ✅ IDÉNTICO a HEAD |
| `src/core/edit_types.py` | `git checkout HEAD --` | ✅ IDÉNTICO a HEAD |
| `src/core/transcriber.py` | `git checkout HEAD --` | ✅ IDÉNTICO a HEAD |
| `src/core/auto_detect.py` | `git checkout HEAD --` | ✅ IDÉNTICO a HEAD |
| `src/core/bootstrap.py` | `git checkout HEAD --` | ✅ IDÉNTICO a HEAD |
| `src/core/config.py` | `git checkout HEAD --` | ✅ IDÉNTICO a HEAD |

### Archivos no rastreados eliminados (creados durante Ronda 8)

| Archivo/Dir | Acción |
|-------------|--------|
| `src/core/profile_schema.py` | Eliminado |
| `src/core/profile_loader.py` | Eliminado |
| `src/core/pipeline.py` | Eliminado |
| `check_fields.py` | Eliminado |
| `report_fields.py` | Eliminado |
| `test_fix.py` | Eliminado |
| `tests/profile_schema_check.py` | Eliminado |
| `planes/` | Eliminado |
| `profiles/` | Eliminado |
| `scripts/` | Eliminado |
| `tmp/` | Eliminado |

### Archivos NO tocados (cambios pre-existentes a Ronda 8)

- `.gitignore`, `README.md`, `config_user.json` — modificaciones previas, no de Ronda 8
- `tests/*.py` — modificaciones previas, no de Ronda 8
- Entries `tmp/colores modificados/` y `tmp/nuevo (sin modificar colores)/` — archivos temporales de CapCut generados durante tests, no código fuente

---

## VERIFICACIONES

### 1. py_compile de todos los archivos fuente
```
.venv\Scripts\python.exe -m py_compile \
  src/core/timeline_builder.py \
  src/core/capcut_project.py \
  src/ui/main_window.py \
  src/core/subtitles.py \
  src/core/edit_types.py \
  src/core/transcriber.py \
  src/core/auto_detect.py \
  src/core/bootstrap.py \
  src/core/config.py
```
✅ **OK** — 0 errores de sintaxis.

### 2. Diferencia contra HEAD (archivos fuente)
```
git diff HEAD --stat -- src/core/ src/ui/
```
✅ **Output vacío** — ningún archivo fuente difiere de HEAD.

### 3. Firma de build_timeline()
```python
def build_timeline(
    scenes: list[Scene],
    srt_path: str | Path,
    image_paths: list[Path],
    cancel_event: threading.Event | None = None,
) -> tuple[list[TimelineItem], int]:
```
✅ **Sin `match_threshold`** — firma idéntica al estado pre-Ronda-8.

### 4. Arranque de la app (Python 3.14)
```python
from src.ui.main_window import MainWindow
```
✅ **App startup OK** — sin ImportError.

### 5. Dry-run PRUEBA6 (Nexus, VIDEO_5, SRT word-level)
```
Match escenas<->SRT: 300/300
Delta final: 0 us
Audio dur: 698800208 us, Sum after: 698800208 us
```
✅ **300/300, delta=0** — comportamiento original restaurado.

---

## COMPROBACIÓN DE COHERENCIA CON PRE-RONDA-8

| Elemento | Estado Pre-Ronda-8 (HEAD) | Estado Actual | ¿Coincide? |
|----------|---------------------------|---------------|------------|
| `timeline_builder.py` | Sin `match_threshold`, sin matcher | Sin `match_threshold`, sin matcher | ✅ |
| `capcut_project.py` | Importa de `edit_types` (no `profile_schema`) | Importa de `edit_types` | ✅ |
| `main_window.py` | Selector de tipo de edición | Selector de tipo de edición | ✅ |
| `subtitles.py` | Importa `EditProfile` de `edit_types` | Importa `EditProfile` de `edit_types` | ✅ |
| `profile_schema.py` | No existe | No existe | ✅ |
| `profile_loader.py` | No existe | No existe | ✅ |
| Dry-run PRUEBA6 | 300/300, delta=0 | 300/300, delta=0 | ✅ |
| App arranque | Funcional | Funcional | ✅ |

---

## RESULTADO

El repositorio `D:\capcut-auto` está **exactamente en el mismo estado** que tenía antes de que comenzara la Ronda 8:

- **Commit base:** `0f7d689` (v1.7.0)
- **Todos los archivos fuente:** idénticos a HEAD (0 líneas de diff)
- **Archivos no rastreables de Ronda 8:** eliminados
- **Pipeline funcional:** 300/300, delta=0
- **Sin errores de importación:** la app arranca correctamente

NOTA: El problema original de los assets (Issue 1) permanece sin resolver, tal como estaba en el estado pre-Ronda-8. El usuario indicará cómo proceder.

Reversión total completada. Esperando confirmación.