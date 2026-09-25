# 🎬 CapCut Auto — Nexus Paradoja

**Versión actual:** v1.2.1 (última taggeada) · v1.3.0 en desarrollo
**Última actualización:** 2026-09-24

> ⚠️ **IMPORTANTE:** Las versiones v1.3.0, v1.4.0, v1.5.0, v1.5.1 que aparecían en versiones anteriores de este README **eran inventadas y no existen como tags reales**. El historial real de tags es el que se muestra a continuación. v1.3.0 está actualmente en desarrollo.

> ⚠️ **IMPORTANTE:** CapCut debe estar **CERRADO** durante la generación.

---

## 📌 Estado del proyecto

| Fase | Descripción | Estado |
|---|---|---|
| **v1.0.0** | Alineación CrispASR + sincronización escenas | ✅ Taggeada |
| **v1.1.0** | UI 2 paneles, subtítulos, modal verde | ✅ Taggeada |
| **v1.2.0** | Camera shake, HSL, paneos, SFX | ✅ Taggeada |
| **v1.2.1** | Limpieza de tracking (backups/cache/logs/models fuera) | ✅ Taggeada |
| **v1.3.0** | Watermark, auto-descarga, fixes de escalas, color grading, subtítulos | ⏳ En desarrollo |

---

## 📐 Escalas JSON ↔ CapCut UI

Aplica a canvas **1920×1080** (half_w = 960, half_h = 540).

| Propiedad UI | Campo JSON | Fórmula (UI → JSON) | Ejemplo |
|---|---|---|---|
| Grosor trazo | `strokes[0].width` | `UI / 500` | 30 → `0.06` |
| Opacidad (%) | `global_alpha` | `UI / 100` | 15 → `0.15` |
| Letter spacing | `letter_spacing` | `UI × 0.05` | 0 → `0.0` |
| Posición X | `transform.x` | `UI_X / 1920` | -1098 → `-0.571875` |
| Posición Y | `transform.y` | `UI_Y / 1080` | -900 → `-0.8333333` |

### Valores vigentes (v1.3.0 en desarrollo)

| Elemento | UI | JSON |
|---|---|---|
| Trazo subtítulos | 30 | `0.06` |
| Opacidad watermark | 15% | `0.15` |
| Letter spacing watermark | 2 | `0.10` |
| Letter spacing subtítulos | **0** | **`0.0`** |
| Posición X watermark | -1098 | `-0.571875` |
| Posición Y watermark | 896 | `0.8296` |
| Posición Y subtítulos | **-900** | **`-0.8333333`** |
| Mayúsculas subtítulos | Sí | ver `docs` |

---

## 🚀 Instalación

```powershell
python -m venv .venv
& .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python src\main.py
```

o directamente `run.bat`.

---

## 🖥️ La nueva interfaz

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
     inteligente** y se muestran 3 resúmenes con ✓/✗:

     ```
     ✓ Audio   : guion.wav
     ✓ Escenas : escenas.txt (144 escenas)
     ✓ Imágenes: .\escenas 2 (144 archivos)
     ```

   - Si algo no se detecta, su etiqueta sale en **rojo** con `✗ No se
     encontró …` y el botón *Generar proyecto* se deshabilita.

3. **Nombre del nuevo proyecto** — campo de texto.

Los botones *Generar* (verde) y *Cancelar* (rojo) están deshabilitados salvo
que correspondan; debajo está la **barra de progreso (indeterminada)** y el
área de logs (read-only con scroll).

### 💾 Configuración persistida (`config_user.json`)

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

## 🔍 Detección inteligente (`src/core/auto_detect.py`)

Función `detect_video_inputs(root) -> DetectionResult`, 100 % sin UI: recibe
una ruta y devuelve un dataclass con `audio_path`, `scene_txt_path`,
`images_dir`, `image_paths`, `scene_count` y `warnings`. Toda decisión queda
registrada en `warnings`.

- **Audio**: usa recursividad sobre extensiones `.wav/.mp3/.m4a/.aac/.flac/.ogg`
  excluyendo nombres con *musica/music/bgm/background*. Puntúa:
  `+3` si el nombre sugiere guion/voz (*guion|voz|voice|narration|locucion|narra*)
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

## 📝 Formato del archivo de escenas

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

## 🛑 Cancelación

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

## 📁 Estructura del proyecto

```
capcut-auto/
├── src/
│   ├── main.py                     # arranca la UI
│   ├── ui/
│   │   └── main_window.py          # ventana CustomTkinter (3 secciones)
│   ├── core/
│   │   ├── config.py               # rutas (incl. bin/, models/) + URLs descarga
│   │   ├── auto_detect.py          # detección inteligente
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
│   ├── subtitle_layout_check.py # subtítulos: layout interno (texto centrado en su caja)
│   ├── watermark_check.py       # marca de agua "NEXUS PARADOJA" (toggles, UI/JSON)
│   ├── color_grading_check.py   # color grading HSL por canal
│   ├── json_scales_check.py     # valores JSON EXACTOS de las escalas UI
│   ├── fase2_e2e.py             # descarga real + alineación del guion (autorizado)
│   └── build_helpers.py         # plantilla/audio sintéticos
├── docs/
│   └── capcut_json_scales.md    # escalas JSON ↔ CapCut UI (oficial)
└── README.md
```

---

## ✅ Verificación

```powershell
# 1) Detección + cancelación (sin UI, usa sintéticos en temp)
& .venv\Scripts\python.exe -X utf8 tests\auto_detect_check.py

# 2) Pipeline completo (plantilla sintética)
& .venv\Scripts\python.exe -X utf8 tests\smoke.py

# 3) Arranque de la UI
& .venv\Scripts\python.exe -X utf8 tests\ui_boot.py

# 4) Restauración de config_user.json al reabrir la UI
& .venv\Scripts\python.exe -X utf8 tests\session_restore_check.py

# 5) Import de transcriber + anti-typo CRISPASR (sin red ni descargas)
& .venv\Scripts\python.exe -X utf8 tests\transcriber_import_check.py

# 6) Subtítulos: fragmentación 2-5 palabras, estilo, trazo, pop-up, MAYÚSCULAS, spacing 0
& .venv\Scripts\python.exe -X utf8 tests\subs_check.py

# 7) Marca de agua "NEXUS PARADOJA": UI/JSON, toggle ON/OFF (draft temporal)
& .venv\Scripts\python.exe -X utf8 tests\watermark_check.py

# 8) Valores JSON EXACTOS de las escalas JSON<->CapCut UI
& .venv\Scripts\python.exe -X utf8 tests\json_scales_check.py

# 9) E2E real autorizado: descarga bin+modelo y alinea el guion
& .venv\Scripts\python.exe -X utf8 tests\fase2_e2e.py

# 10) Subtítulos: layout interno (Fix 1-5 + cobertura contigua de estilos)
& .venv\Scripts\python.exe -X utf8 tests\subtitle_layout_check.py
```

---

## 🐞 Texto de los subtítulos pegado abajo dentro de su caja

**Síntoma.** Los subtítulos están bien posicionados en el eje Y, pero DENTRO de
su propia caja el texto se ve pegado al borde inferior, con un hueco vacío
grande arriba. La caja es más alta que los glifos. No es
`clip.transform.y` (la posición del objeto): es la composición del texto dentro
de su caja.

**Causa raíz (verificada, no supuesta).** Los `range` de `content.styles[]` no
cubrían el texto entero. El código saltaba el espacio entre palabras
(`cursor = end + 1` en `build_text_content`), así que **los espacios se
quedaban sin estilo** y CapCut los componía con su estilo **por defecto**: la
caja se calculaba con una altura mayor que la de los glifos y el texto se
dibujaba pegado abajo.

Contraste con el **draft real de referencia** (el proyecto del usuario
`Nexus Paradoja video 10100`, 740 materiales de texto, que en CapCut se ve
bien): los **740/740 tienen cobertura CONTIGUA de `[0, len)`**, con un estilo
por cada palabra **y otro por cada grupo de espacios** (1120 runs son solo
espacios). Ese formato es el que CapCut escribe, y es el que se genera ahora.

**Los 5 fixes aplicados** (`src/core/subtitles.py`):

| # | Fix | Qué se hizo |
|---|---|---|
| 1 | `font_size` material ↔ content sincronizados | `build_text_material` resuelve `font_size = float(FONT_SIZE)` **una sola vez** y la usa tanto en `material.font_size` como en `content.styles[].size`. Si se desincronizan, CapCut mide la caja con un tamaño y dibuja los glifos con el otro. **OJO: en el `content` la clave se llama `size`, no `font_size`** — es el nombre que usa CapCut (`font_size` no existe en su esquema; ver `watermark_check.py`, que ya leía `size`). |
| 2 | Alineación explícita | `content.styles[]` lleva `align_type: 1` (centro horizontal) y `vertical_align: 1` (centro vertical dentro del cuadro); el material lleva `alignment: 1`, `line_feed: 1`, `typesetting: 0`. |
| 3 | `line_spacing` a cero | `line_spacing: 0.0` en **todos** los `content.styles[]` y en el `material`. |
| 4 | Texto limpio de invisibles | `clean_srt_text` es ahora la única puerta: quita tags/entidades HTML, elimina los caracteres **invisibles** (zero-width `\u200b\u200c\u200d`, `\u2060`, BOM `\ufeff`, soft hyphen `\u00ad` — que Python **no** considera whitespace y sobrevivían a `split()`), convierte cualquier espacio Unicode (`\u00A0`, `\u2003`, `\u2009`, `\u202F`, `\u3000`, `\t`, `\n`, `\r`) en **un** espacio ASCII y aplica `.strip()`. `build_text_content` pasa por él, así que el texto sale limpio aunque se llame directamente. |
| 5 | Campos de caja del material | `fixed_height: -1.0`, `fixed_width: -1.0`, `inner_padding: -1.0` (**float**, como los escribe CapCut), `typesetting: 0`, `line_feed: 1`, `alignment: 1`, `preset_has_set_alignment: false`. La caja queda en automático: sin alto fijo ni padding, ceñida al texto. |
| **Raíz** | **Cobertura contigua de estilos** | **`text_runs()` divide el texto en runs máximos palabra/espacio y cubre `[0, len_utf16)` SIN huecos.** Los espacios heredan el color del run anterior, igual que en el draft real. Los offsets se calculan con `_utf16_at()` (offsets UTF-16 exactos con tildes). |

**Lo que NO se ha tocado:** `clip.transform.y` (`config.SUBTITLE_POS_Y_JSON` =
`-0.8333333` = UI −900, idéntico al del draft real de referencia), sincronización,
transiciones, color grading, HSL, paneos, camera shake, SFX, marca de agua ni UI.

**Verificado por `tests/subtitle_layout_check.py`** (3 subtítulos, incluidos los
que tienen espacios Unicode y zero-width): Fix 1 (mismo float en material y
content), Fix 2, Fix 3, Fix 4, Fix 5, **cobertura contigua sin huecos**,
sincronización intacta y posición Y intacta. El test **falla** si alguien
vuelve a dejar un espacio sin estilo (regresión comprobada).

---

## 📏 Reglas de desarrollo

Reglas estrictas para tocar este repo (las verifican los tests):

1. **Un solo espacio ASCII entre palabras de subtítulos.** `clean_srt_text`
   normaliza el texto y devuelve `" ".join(text.split())`: entre palabras hay
   EXACTAMENTE un U+0020. Prohibido `\u2003`, `\u00A0`, `\u202F`, `\u3000`,
   `\t`, `\n` o múltiples espacios (producen huecos enormes en CapCut).
   Verificado por `subs_check.py` y `subtitle_layout_check.py`.

1b. **`content.styles[]` cubre el texto INTEGRO y sin huecos.** Los `range`
   (offsets UTF-16) son contiguos de `[0, len_utf16(text))`: un estilo por
   palabra **y otro por cada grupo de espacios**. Un carácter sin estilo
   (p. ej. un espacio) lo compone CapCut con su estilo por defecto, la caja
   crece y **el texto se ve pegado abajo con un hueco arriba**. Se genera con
   `subtitles.text_runs()`. Verificado por `subtitle_layout_check.py`
   (contraste: los 740 materiales del draft real de CapCut son 740/740
   contiguos).

1c. **Ningún carácter invisible en el texto de subtítulos.** `clean_srt_text`
   borra los `Cf` de Unicode que Python NO ve como whitespace: `\u200b`,
   `\u200c`, `\u200d`, `\u2060`, `\ufeff` (BOM) y `\u00ad`.

1d. **Un único tamaño de fuente.** `material.font_size` y
   `content.styles[].size` son el MISMO float, resuelto una sola vez en
   `build_text_material` desde `subtitles.FONT_SIZE`. En el `content` la clave
   es `size` (así la llama CapCut), no `font_size`.
   Verificado por `subs_check.py` y `subtitle_layout_check.py`.

1e. **`line_spacing = 0.0` y caja automática.** `line_spacing: 0.0` en el
   `content` y en el material; `fixed_height`/`fixed_width`/`inner_padding` =
   `-1.0` (float), `typesetting: 0`, `line_feed: 1`, `alignment: 1`,
   `preset_has_set_alignment: false`.
   Verificado por `subtitle_layout_check.py`.

2. **Posición vertical de subtítulos constante.** Todos los subtítulos usan la
   misma `config.SUBTITLE_POS_Y_JSON = -0.8333333` (= UI "-900", escala
   UI_Y/1080 = -900/1080), aplicada SIN cálculo dinámico en
   `subtitles.SUBTITLE_Y`. Nada de Y calculada por contenido.

3. **Trazo de subtítulos = 30 en la UI.** `config.SUBTITLE_STROKE_WIDTH_JSON =
   0.06` (JSON) = "30" en CapCut (escala UI/500). Trazo ACTIVADO (en el
   `content`: `strokes[0].enable = true`, `border_mode 1`), color negro puro.
   Verificado por `subs_check.py`.

4. **Letter spacing subtítulos = 0.** `config.LETTER_SPACING = 0.0` (JSON) = "0"
   en CapCut. Verificado por `subs_check.py`.

5. **Subtítulos en MAYÚSCULAS.** `build_text_content` aplica `.upper()` al
   texto final. Verificado por `subs_check.py`.

6. **Marca de agua propia, pista independiente.** "NEXUS PARADOJA",
   `transform.x = -0.571875` (UI X=-1098), `transform.y = 0.8296` (UI Y=896),
   `global_alpha = 0.15` (15%), `text_alpha = 1.0` fijo, `fill.alpha = 1.0`
   en content, `letter_spacing = 0.10` (espaciado 2), tamaño 8,
   negrita+cursiva, misma fuente que subtítulos, cubre todo el video,
   en su propia pista text. Verificado por `watermark_check.py` y
   `json_scales_check.py`. Fórmula opacidad: UI% = global_alpha × 100
   (draft real: global_alpha=0.1005 → ~10%).

7. **Color grading HSL por canal.** 3 materiales HSL (Naranja, Cian, Azul) con
   `hue=0, saturation=0, lightness=0` base; keyframes `KFTypeHue`,
   `KFTypeSaturation`, `KFTypeLightSensatione` en segmentos de video.
   Materiales referenciados via `extra_material_refs` + `enable_hsl=true`.

7. **Nunca tocar código no relacionado.** Un cambio toca solo su bug/feature.

8. **README siempre al día.** Cada cambio funcional actualiza esta sección.

---

## 🎨 Color Grading HSL (detalle técnico)

- 3 materiales HSL en `materials.hsl[]`: Naranja (tipo 2), Cian (tipo 5), Azul (tipo 6).
- Base: `hue=0, saturation=0, lightness=0` → animación 100% por keyframes.
- Keyframes en segmentos: `KFTypeHue`, `KFTypeSaturation`, `KFTypeLightSensatione`.
- Referencia: `extra_material_refs` en segmento + `enable_hsl=true`.
- `lumi_hub_path` = `path` (no `path/lumi_hub_path`).
- Verificado por `color_grading_check.py`.

---

## 📜 Historial de versiones (solo tags reales)

| Versión | Fecha | Descripción |
|---|---|---|
| **v1.2.1** | 2026-09-23 | Chore: limpieza de tracking (backups, cache, logs, models fuera del repo). |
| **v1.2.0** | 2026-09-23 | Fase 3: camera shake, HSL, paneos, SFX. |
| **v1.1.0** | 2026-09-22 | Fase 2: UI 2 paneles, subtítulos, modal verde. |
| **v1.0.0** | 2026-09-22 | Fase 1: alineación CrispASR + sincronización. |

> **Nota:** Las versiones v1.3.0, v1.4.0, v1.5.0, v1.5.1 que aparecían en versiones anteriores de este README **eran inventadas y no existen como tags reales**. v1.3.0 está en desarrollo.

---

## 📦 Pendiente (fuera de alcance)

Transiciones entre clips… no implementadas todavía.

## 📦 Empaquetado (.exe)

```powershell
pip install pyinstaller
pyinstaller build.spec
```

Genera `dist\CapCutAuto\` (onedir). El binario de CrispASR y el modelo
**no** se incluyen: se descargan a `bin/` y `models/` junto al .exe en la
primera ejecución.

---

🏁 **Fin del README** — CapCut Auto está listo para usar.