# CapCut Auto

Genera automáticamente un **proyecto CapCut** (Windows) a partir de:

1. Un proyecto **plantilla** de CapCut (carpeta dentro de una carpeta
   "CapCut Drafts" que contenga `draft_content.json` + `draft_meta_info.json`).
2. Una carpeta de **video** con **audio**, un **.txt de escenas** y una
   **carpeta de imágenes** — todos detectados automáticamente.
3. Un **nombre** para el nuevo proyecto.

La app:

- **Detecta** el audio, el .txt de escenas y las imágenes de forma inteligente
  (`src/core/auto_detect.py`) sin que el usuario tenga que elegir archivo a
  archivo.
- **Alinea** el audio con el guion (VOZ EN OFF de cada escena) mediante
  **forced alignment** con **CrispASR** y el modelo español
  `stt-es-fastconformer-hybrid-ctc-large-GGUF` (Q4_K, ~70 MB). Genera un SRT
  donde cada línea = una escena; sin fuzzy matching, sin transcripción.
- **Clona la plantilla**, edita `draft_content.json` y `draft_meta_info.json`,
  y escribe el nuevo proyecto en la carpeta de proyectos de CapCut.
- Permite **cancelar** la generación en cualquier momento (clic en *Cancelar*);
  si se llega a clonar, limpia la carpeta a medias y **nunca toca la plantilla**.
- Persiste tu configuración en `config_user.json` para rellenar la UI al
  reabrir la app.

> ⚠️ **IMPORTANTE:** NO abras CapCut mientras se genera. La app copia la
> plantilla y edita los JSON **después**: crea el proyecto nuevo primero y
> luego edita el JSON de ¡ESE proyecto nuevo! (nunca la plantilla original).
> El proyecto se crea con **CapCut cerrado**.

---

## Requisitos

- Windows 10/11 con **CapCut instalado**.
- Python 3.11+.
- Internet la **primera vez** (descarga de CrispASR ~8 MB y del modelo español
  GGUF Q4_K (~70 MB) a `bin/` y `models/`); las siguientes ejecuciones van
  totalmente en local.

---

## Instalación

```powershell
python -m venv .venv
& .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Ejecución

```powershell
& .venv\Scripts\Activate.ps1
python src\main.py
```

o directamente `run.bat`.

---

## La nueva interfaz

La ventana tiene **3 secciones** + botones **Generar proyecto** y **Cancelar**:

1. **Carpeta CapCut Drafts**
   - Botón *Seleccionar carpeta…* (y un pequeño *Cambiar…* junto a la ruta).
   - Debajo, un desplegable con las **plantillas detectadas**: subcarpetas que
     contienen a la vez `draft_content.json` y `draft_meta_info.json`.
   - Si solo hay una plantilla se autoselecciona; si hay varias, se conserva la
     última elegida. Si la carpeta no tiene plantillas válidas se muestra un
     error y **no se guarda**.
   - La ruta se guarda en `config_user.json` y se recupera al reabrir la app.

2. **Carpeta del video**
   - Botón *Seleccionar carpeta…*. Al elegirla se ejecuta el **escaneo
     inteligente** (ver abajo) y se muestran 3 resúmenes con ✓/✗:

     ```
     ✓ Audio   : guion.wav
     ✓ Escenas : escenas.txt (144 escenas)
     ✓ Imágenes: .\escenas 2 (144 archivos)
     ```

   - Si algo no se detecta, su etiqueta sale en **rojo** con `✗ No se
     encontró …` y el botón *Generar proyecto* se deshabilita.

3. **Nombre del nuevo proyecto** — campo de texto (igual que antes).

Los botones *Generar* (verde) y *Cancelar* (rojo) están deshabilitados salvo
que correspondan; debajo están la barra de progreso y el área de logs
(read-only con scroll).

### Configuración persistida (`config_user.json`)

Se crea en la raíz del proyecto (`D:\capcut-auto\config_user.json`) con:

```json
{
  "capcut_drafts_dir": "D:\\...\\CapCut Drafts",
  "last_template_name": "1.PLANTILLA",
  "last_video_dir": "D:\\...\\VIDEO_1"
}
```

Se **guarda** tras cada cambio de carpeta o de plantilla y se **carga al
arrancar**: restaura drafts, plantilla seleccionada y re-escanea la carpeta de
video si sigue existiendo.

---

## Detección inteligente (`src/core/auto_detect.py`)

Función `detect_video_inputs(root) -> DetectionResult`, 100 % sin UI: recibe
una ruta y devuelve un dataclass con `audio_path`, `scene_txt_path`,
`images_dir`, `image_paths`, `scene_count` y `warnings`. Toda decisión queda
registrada en `warnings`.

- **Audio**: usa recursividad sobre extensiones `.wav/.mp3/.m4a/.aac/.flac/.ogg`
  excluyendo nombres con *musica/music/bgm/background*. Puntúa:
  `+3` si el nombre sugiere guion/voz (*guion|voz|voice|narration|locucion|narra`)
  y `+1` por MB (cap a +10). Gana el de mayor score.
- **Escenas (.txt)**: lista los `.txt` recursivos, valida las primeras 200
  líneas (al menos 2 `ESCENA #` y 1 `VOZ EN OFF:`). Puntúa: `+5` si el nombre
  sugiere *escena|scene|guion|script* y `+1` por cada 10 escenas. Desempate
  por `mtime` (más reciente). Si varios quedan a **≤ 2 puntos**, se pregunta al
  usuario en un diálogo.
- **Imágenes**: extensiones `.jpg/.jpeg/.png/.webp`. Si la raíz tiene ≥ 2
  imágenes usa la raíz; si no, la primera subcarpeta (por orden alfabético)
  cuyo contenido directo tenga ≥ 2. Orden **natural** (`2.jpg < 10.jpg` vía
  `natural_sort_key`).
- **Validación cruzada**: si `len(image_paths) != scene_count` se añade un
  warning; al generar, la UI pide decisión (usar primeras N / duplicar la
  última / cancelar).

---

## Formato del archivo de escenas

Por bloque (cada escena empieza con `ESCENA #<n>`):

```text
ESCENA #137
VOZ EN OFF: "Ahora es más rápido, más fuerte, pero también más humano que nunca."
DURACIÓN ESTIMADA: 4 segundos
BÚSQUEDA DE IMAGEN (Google/Pinterest): "universo futurista humano"
NOTA: "rojo y azul"
```

Reglas: las escenas se ordenan **por orden de aparición**, el texto clave es la
línea `VOZ EN OFF`, y `DURACIÓN ESTIMADA` / `BÚSQUEDA` / `NOTA` son auxiliares.

---

## Cancelación

- Un `threading.Event` (`cancel_event`) compartido entre la UI y el hilo de
  trabajo.
- *Cancelar* → `cancel_event.set()`. Se comprueba en: el bucle de copiado de
  imágenes, el bucle de construcción del timeline, y **antes** de escribir el
  `draft_content.json` final.
- Si se cancela tras clonar, la carpeta a medias se elimina
  (`shutil.rmtree(new_dir, ignore_errors=True)`) y se loguea *"Generación
  cancelada por el usuario."*. La plantilla original nunca se modifica.
- Nota: CrispASR no es cancelable a mitad de alineación; se comprueba la
  cancelación antes y después (y durante la descarga del binario/modelo, que
  borra los `.part` a medias).

---

## Estructura

```
capcut-auto/
├── src/
│   ├── main.py                     # arranca la UI
│   ├── ui/
│   │   └── main_window.py          # ventana CustomTkinter (3 secciones)
│   ├── core/
│   │   ├── config.py               # rutas (incl. bin/, models/) + URLs descarga
│   │   ├── auto_detect.py          # detección inteligente (nuevo)
│   │   ├── scene_parser.py         # .txt de escenas
│   │   ├── transcriber.py          # descarga CrispASR/modelo + align_audio_to_text
│   │   ├── timeline_builder.py     # timeline escena <-> cue del SRT + cancel_event
│   │   └── capcut_project.py       # clonado/edición + cancel_event
│   └── utils/
│       └── logger.py
├── cache/               # guion temporal + SRT de alineación
├── bin/                 # crispasr.exe (descargado en la 1ª ejecución)
├── models/              # modelo español GGUF (descargado en la 1ª ejecución)
├── logs/                # app.log + schema_plantilla.json
├── backups/             # copias de seguridad de la plantilla
├── config_user.json     # configuración persistida (se crea al usar la app)
├── build.spec           # empaquetado PyInstaller (onedir, sin models/)
├── tests/
│   ├── smoke.py                 # pipeline completo sin UI (plantilla sintética)
│   ├── auto_detect_check.py     # checks de detección + cancelación (sin UI)
│   ├── session_restore_check.py # restauración de config al reabrir la UI
│   ├── transcriber_import_check.py  # anti-typo CRISPASR + imports (sin red)
│   ├── fase2_e2e.py             # descarga real + alineación del guion (autorizado)
│   └── build_helpers.py         # plantilla/audio sintéticos
└── README.md
```

---

## Verificación

```powershell
# 1) Detección + cancelación (sin UI, usa sintéticos en temp)
& .venv\Scripts\python.exe -X utf8 tests\auto_detect_check.py

# 2) Pipeline completo (plantilla sintética)
& .venv\Scripts\python.exe -X utf8 tests\smoke.py

# 3) Arranque de la UI
& .venv\Scripts\python.exe -X utf8 tests\ui_boot.py

# 4) Restauración de config_user.json al reabrir la app
& .venv\Scripts\python.exe -X utf8 tests\session_restore_check.py

# 5) Import de transcriber + anti-typo CRISPASR (sin red ni descargas)
& .venv\Scripts\python.exe -X utf8 tests\transcriber_import_check.py

# 6) E2E real autorizado: descarga bin+modelo y alinea el guion (toca bin/models y CapCut)
& .venv\Scripts\python.exe -X utf8 tests\fase2_e2e.py
```

---

## Pendiente (fuera de alcance)

Transiciones entre clips… no implementadas todavía.

## Empaquetado (.exe)

```powershell
pip install pyinstaller
pyinstaller build.spec
```

Genera `dist\CapCutAuto\` (onedir). El binario de CrispASR y el modelo
**no** se incluyen: se descargan a `bin/` y `models/` junto al .exe en la
primera ejecución.