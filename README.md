# CapCut Auto - Nexus Paradoja

**Versión actual:** v1.3.0
**Última actualización:** 2026-09-24

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

## Escalas JSON ↔ CapCut UI (oficial)

Mapa de conversión entre el JSON del `draft_content.json` y los valores del
panel de CapCut (confirmado por investigación; con ejemplos y recálculo en
[`docs/capcut_json_scales.md`](docs/capcut_json_scales.md)). Aplica
únicamente a este proyecto **1920×1080** (half width = 960, half height = 540).

| Propiedad CapCut UI      | Campo en `draft_content.json`        | Fórmula (UI → JSON) |
|--------------------------|--------------------------------------|---------------------|
| Grosor trazo             | `strokes[0].width` (y `border_width`)| UI / 500            |
| Opacidad (%)             | `text_alpha` (+ `fill.alpha` 1.0)    | UI / 100            |
| Letter spacing           | `letter_spacing`                     | UI × 0.05           |
| Posición X               | `transform.x`                        | UI_X / 1920         |
| Posición Y               | `transform.y`                        | UI_Y / 1080         |

Valores calculados para este proyecto:

| Propiedad            | UI deseada | Valor JSON                                    |
|----------------------|------------|-----------------------------------------------|
| Grosor trazo subtítulos | 30       | `0.06`    (= 30 / 500)                        |
| Opacidad watermark   | 40%        | `0.40`    (= 40 / 100) + `fill.alpha 1.0`     |
| Letter spacing watermark | 2       | `0.10`    (= 2 × 0.05)                        |
| Watermark posición X | -1098      | `-0.571875` (= -1098 / 1920)                  |
| Watermark posición Y | 896        | `0.8296`    (= 896 / 1080, ≈0.8296)           |
| Subtítulos posición Y| -660       | `-0.6111111`  (= -660 / 1080)                 |

> ⚠️ **Verificar empíricamente:** abre el proyecto generado en CapCut. Si los
> valores mostrados NO son exactamente los de la columna "UI deseada", ajusta
> el JSON proporcionalmente (constantes `*_JSON` en `src/core/config.py`) hasta
> que coincidan y documenta la corrección aquí y en
> `docs/capcut_json_scales.md`.

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
│   │   ├── bootstrap.py            # ensure_dependencies(): descarga bin+modelo (1er uso)
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
│   ├── bootstrap_check.py       # descarga bin/modelo simulada (sin red)
│   ├── subs_check.py            # subtítulos: fragmentación, estilo, trazo, pop-up
│   ├── watermark_check.py       # marca de agua "NEXUS PARADOJA" (toggles, UI/JSON)
│   ├── json_scales_check.py     # valores JSON EXACTOS de las escalas UI (v1.3.0)
│   ├── fase2_e2e.py             # descarga real + alineación del guion (autorizado)
│   └── build_helpers.py         # plantilla/audio sintéticos
├── docs/
│   └── capcut_json_scales.md    # escalas JSON ↔ CapCut UI (oficial)
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

# 6) Subtítulos: fragmentación 2-5 palabras, estilo, espaciado U+0020, trazo UI 30
& .venv\Scripts\python.exe -X utf8 tests\subs_check.py

# 7) Marca de agua "NEXUS PARADOJA": UI/JSON, toggle ON/OFF (draft temporal)
& .venv\Scripts\python.exe -X utf8 tests\watermark_check.py

# 8) Valores JSON EXACTOS de las escalas JSON<->CapCut UI (trazo, opacidad,
#    spacing, posiciones de subtítulos y watermark)
& .venv\Scripts\python.exe -X utf8 tests\json_scales_check.py

# 9) E2E real autorizado: descarga bin+modelo y alinea el guion (toca bin/models y CapCut)
& .venv\Scripts\python.exe -X utf8 tests\fase2_e2e.py
```

---

## Reglas de desarrollo

Reglas estrictas para tocar este repo (las verifican los tests):

1. **Un solo espacio ASCII entre palabras de subtítulos.** `build_text_content`
   normaliza el texto con `" ".join(text.split())`: entre palabras hay
   EXACTAMENTE un U+0020. Prohibido `\u2003`, `\u00A0`, `\t`, `\n` o múltiples
   espacios (producen huecos enormes en CapCut). Verificado por `subs_check.py`.
2. **Posición vertical de subtítulos constante.** Todos los subtítulos usan la
   misma `config.SUBTITLE_POS_Y_JSON = -0.6111111` (= UI "-660", escala
   UI_Y/1080 = -660/1080), aplicada SIN cálculo dinámico en
   `subtitles.SUBTITLE_Y`. Nada de Y calculada por contenido.
3. **Trazo de subtítulos = 30 en la UI.** `config.SUBTITLE_STROKE_WIDTH_JSON =
   0.06` (JSON) = "30" en CapCut (escala UI/500). Trazo ACTIVADO (en el
   `content`: `strokes[0].enable = true`, `border_mode 1`), color negro puro.
   Verificado por `subs_check.py`.
4. **Marca de agua propia, pista independiente.** "NEXUS PARADOJA",
   `transform.x = -0.571875` (UI X=-1098), `transform.y = 0.8296` (UI Y=896),
   `text_alpha = 0.40` + `fill.alpha 1.0` (40%), `letter_spacing = 0.10`
   (espaciado 2), tamaño 8, negrita+cursiva, misma fuente que subtítulos,
   cubre todo el video, en su propia pista text. Verificado por
   `watermark_check.py` y `json_scales_check.py`.
5. **Nunca tocar código no relacionado.** Un cambio toca solo su bug/feature.
6. **README siempre al día.** Cada cambio funcional actualiza esta sección.

### Escalas JSON ↔ UI de CapCut (confirmadas; ver docs/capcut_json_scales.md)

Use las constantes de `src/core/config.py` (versionadas como `*_UI` y `*_JSON`):

| Concepto | Escala (UI → JSON) | Ejemplo verificado |
|---|---|---|
| `strokes[0].width` / `border_width` (trazo) | UI / 500 | UI 30 → `0.06` |
| `text_alpha` (opacidad) | UI / 100 (+ `fill.alpha 1.0`) | 40% → `0.40` |
| `letter_spacing` | UI × 0.05 | UI 2 → `0.10` · UI 1 → `0.05` |
| `transform.x` | UI_X / 1920 | -1098/1920 → `-0.571875` |
| `transform.y` | UI_Y / 1080 | 896/1080 → `0.8296` · -660/1080 → `-0.6111111` |

---

## Historial de versiones

### v1.4.0 (2026-09-24)

- Corrected JSON ↔ CapCut UI scales based on empirical testing against the
  user's real draft (`#1 Nexus Paradoja`) and direct CapCut measurements.
- Positions: CapCut multiplies `transform.*` by the FULL canvas (1920×1080),
  not half; watermark X/Y JSON now `-0.571875` / `0.8296` (UI -1098/896),
  subtitles Y `-0.6111111` (UI -660). v1.3.0 values showed as double.
- Text stroke: scale is UI/500 (JSON `0.06` = UI 30). v1.3.0 `0.30` showed 150.
- Watermark opacity: `text_alpha 0.40` + explicit `styles[].fill.alpha = 1.0`
  (40%); missing fill.alpha made it render 30%.
- Fix de huecos entre palabras (exactamente 1 espacio ASCII).

### v1.3.0 (2026-09-24)

- Watermark "NEXUS PARADOJA" con opacidad 40%.
- Fix del contorno de subtítulos (trazo UI 30) y posición vertical constante.
- Fix de huecos entre palabras (exactamente 1 espacio ASCII).
- Nuevo `tests/json_scales_check.py` y documentación oficial
  `docs/capcut_json_scales.md`.

### v1.2.0 (fecha)

- Fase 3: camera shake, HSL, paneos, SFX.

### v1.1.0 (fecha)

- Fase 2: UI 2 paneles, subtítulos, modal verde.

### v1.0.0 (fecha)

- Fase 1: alineación CrispASR + sincronización.

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