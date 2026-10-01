# 🎬 CapCut Auto — Nexus Paradoja

**Versión actual:** v1.6.0 · v1.7.0 en desarrollo
**Última actualización:** 2026-09-30

> ⚠️ **IMPORTANTE:** CapCut debe estar **CERRADO** durante la generación.

---

## 📌 Estado del proyecto

| Fase | Descripción | Estado |
|---|---|---|
| **v1.0.0** | Alineación CrispASR + sincronización escenas | ✅ Taggeada |
| **v1.1.0** | UI 2 paneles, subtítulos, modal verde | ✅ Taggeada |
| **v1.2.0** | Camera shake, HSL, paneos, SFX | ✅ Taggeada |
| **v1.2.1** | Limpieza de tracking (backups/cache/logs/models fuera) | ✅ Taggeada |
| **v1.3.0** | Watermark, auto-descarga, fixes de escalas, color grading, subtítulos, pop-up | ✅ Taggeada |
| **v1.4.0** | "Imagina esto" — centrado de subtítulos con keyword + ocultamiento de vídeo | ✅ Taggeada |
| **v1.5.0** | Selector de audios en UI — detección recursiva, dropdown guion, lista otros | ✅ Taggeada |
| **v1.5.1** | Hotfix: cancelación (modal + matar CrispASR) + fix audio guion (dropdown manda, nombre irrelevante) | ✅ Taggeada |
| **v1.6.0** | Tipo de edición "Datos Y Cafe" (watermark/subtítulos distintos, sin efectos avanzados) | ✅ Taggeada |
| **v1.7.0** | Exclusión de escaneo | ✅ Taggeada |
| **v2.0.0** | Nuevo tipo de edición (además de "Nexus Paradoja") — última antes del .exe | ⏳ Pendiente |
| **v2.1.0** | Empaquetado .exe + guardar app completa en la nube | ⏳ Pendiente |

> **Nota:** v1.9.0 (tv_control + flash + reset) queda **descartado**. Si se retoma, será dentro de otra versión.

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
| Saturación (UI) | `KFTypeSaturation.values` | `UI / 50` | -50 → `-1.0` |
| Brillo (UI) | `KFTypeBrightness.values` | `UI / 50` | -50 → `-1.0` |
| Contraste (UI) | `KFTypeContrast.values` | `UI / 50` | -50 → `-1.0` |
| Negros (UI) | `KFTypeBlack.values` | `UI / 50` | -50 → `-1.0` |

### Valores vigentes

| Elemento | UI | JSON |
|---|---|---|
| Trazo subtítulos | 30 | `0.06` |
| Opacidad watermark | 15% | `0.15` |
| Letter spacing watermark | 2 | `0.10` |
| Letter spacing subtítulos | 0 | `0.0` |
| Posición X watermark | -1098 | `-0.571875` |
| Posición Y watermark | 896 | `0.8296` |
| Posición Y subtítulos | -900 | `-0.8333333` |
| Mayúsculas subtítulos | Sí | ver `docs` |

---

## 🚀 Instalación

```powershell
python -m venv .venv
& .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python src\main.py
o directamente run.bat.

🖥️ La nueva interfaz
La ventana tiene 6 secciones + botones Generar proyecto y Cancelar:

Carpeta CapCut Drafts

Botón Seleccionar carpeta… (y un pequeño Cambiar… junto a la ruta).

Debajo, un desplegable con las plantillas detectadas: subcarpetas que
contienen a la vez draft_content.json y draft_meta_info.json.

Si solo hay una plantilla se autoselecciona; si hay varias, se conserva la
última elegida. Si la carpeta no tiene plantillas válidas se muestra un
error y no se guarda.

La ruta se guarda en config_user.json y se recupera al reabrir la app.

Carpeta del video

Botón Seleccionar carpeta…. Al elegirla se ejecuta el escaneo
inteligente y se muestran 3 resúmenes con ✓/✗:

text
✓ Audio   : guion.wav
✓ Escenas : escenas.txt (144 escenas)
✓ Imágenes: .\escenas 2 (144 archivos)
Si algo no se detecta, su etiqueta sale en rojo con ✗ No se encontró … y el botón Generar proyecto se deshabilita.

Subtítulos (.srt)

Botón Buscar .srt… que escanea la carpeta del video y el caché de
alineación.

Desplegable con todos los .srt encontrados; el último elegido se restaura
al reabrir la app.

Los subtítulos se dividen en fragmentos de 2-5 palabras con timing
proporcional durante la generación.

Audios del proyecto (v1.5.0 + v1.5.1)

Al seleccionar la carpeta del video, se escanean recursivamente todos
los archivos de audio (.wav, .mp3, .m4a, .aac, .flac, .ogg).

Audio guion (narración principal) — desplegable con todos los audios
encontrados. La clasificación es solo una sugerencia inicial:

Si existe un archivo con "guion" en el nombre (case-insensitive, sin
tildes) → se autoselecciona.

Si no existe → el primer .wav encontrado se propone como guion.

El audio que EL USUARIO seleccione en el dropdown es el ÚNICO que se usa
como guion (pista principal de audio en CapCut). El nombre no importa.
Los demás quedan como audios detectados (podrían usarse como SFX).

La elección se guarda en config_user.json como last_guion_name y se
restaura al reabrir. Comparación case-insensitive (fix v1.5.1).

Otros audios detectados — lista visual de los archivos restantes.

Si no hay audios, el dropdown aparece deshabilitado con el mensaje
"No se detectaron audios en la carpeta".

Nombre del nuevo proyecto — campo de texto.

Los botones Generar (verde) y Cancelar (rojo) están deshabilitados salvo
que correspondan; debajo está la barra de progreso (indeterminada) y el
área de logs (read-only con scroll).

💾 Configuración persistida (config_user.json)
Se crea en la raíz del proyecto (D:\capcut-auto\config_user.json) con:

json
{
"capcut_drafts_dir": "D:\\...\\CapCut Drafts",
  "last_template_name": "1.PLANTILLA",
  "last_video_dir": "D:\\...\\VIDEO_1",
  "last_srt_dir": "D:\\...\\VIDEO_1",
  "last_srt_name": "guion.srt",
  "last_guion_name": "guion.MP3"
}
Se guarda tras cada cambio de carpeta, plantilla o audio y se carga al
arrancar.

🔍 Detección inteligente (src/core/auto_detect.py)
Función detect_video_inputs(root) -> DetectionResult, 100 % sin UI: recibe
una ruta y devuelve un dataclass con audio_path, scene_txt_path,
images_dir, image_paths, scene_count y warnings. Toda decisión queda
registrada en warnings.

Audio: usa recursividad sobre extensiones .wav/.mp3/.m4a/.aac/.flac/.ogg
excluyendo nombres con musica/music/bgm/background. Puntúa:
+3 si el nombre sugiere guion/voz (guion|voz|voice|narration|locucion|narra)
y +1 por MB (cap a +10).

Importante (v1.5.1): el resultado de detect_video_inputs para el audio
es solo una sugerencia inicial para el dropdown. El pipeline NO usa
este valor. El audio del guion es SIEMPRE el que el usuario selecciona en el
dropdown (pasado explícitamente a project.generate()).

detect_audios(root) -> dict (v1.5.0) para el selector de UI.
Escanea recursivamente todos los audios y devuelve:

python
{"guion": Path | None, "otros": [Path, ...]}
Escenas (.txt): lista los .txt recursivos, valida las primeras 200
líneas (al menos 2 ESCENA # y 1 VOZ EN OFF:). Puntúa: +5 si el nombre
sugiere escena|scene|guion|script y +1 por cada 10 escenas.

Imágenes: extensiones .jpg/.jpeg/.png/.webp. Orden natural
(2.jpg < 10.jpg vía natural_sort_key).

Validación cruzada: si len(image_paths) != scene_count se añade un
warning; al generar, la UI pide decisión.

📝 Formato del archivo de escenas
Por bloque (cada escena empieza con ESCENA #<n>):

text
ESCENA #137
VOZ EN OFF: "Ahora es más rápido, más fuerte, pero también más humano que nunca."
DURACIÓN ESTIMADA: 4 segundos
BÚSQUEDA DE IMAGEN (Google/Pinterest): "universo futurista humano"
NOTA: "rojo y azul"
Reglas: las escenas se ordenan por orden de aparición, el texto clave es la
línea VOZ EN OFF, y DURACIÓN ESTIMADA / BÚSQUEDA / NOTA son auxiliares.

🛑 Cancelación
Un threading.Event (cancel_event) compartido entre la UI y el hilo de
trabajo.

Diálogo modal al pulsar Cancelar: "¿Seguro que quieres cancelar la
generación?" con botones Sí/No. Si Sí → cancel_event.set().

La app NO se cierra. El botón Generar vuelve a estar habilitado.

Se comprueba en: bucle de copiado de imágenes, bucle de construcción del
timeline, subtítulos, capcut_project, imagina_esto y antes de
escribir el draft_content.json final.

Fix v1.5.1: matar el subprocess de CrispASR (Popen.terminate() /
kill()) al cancelar durante la alineación.

Si se cancela tras clonar, la carpeta a medias se elimina
(shutil.rmtree(new_dir, ignore_errors=True)).

La plantilla original nunca se modifica.

📁 Estructura del proyecto
text
capcut-auto/
├── src/
│   ├── main.py                     # arranca la UI
│   ├── ui/
│   │   └── main_window.py          # ventana CustomTkinter (6 secciones)
│   ├── core/
│   │   ├── config.py               # rutas + URLs + constantes (chroma, roles)
│   │   ├── auto_detect.py          # detección inteligente
│   │   ├── scene_parser.py         # .txt de escenas
│   │   ├── transcriber.py          # descarga CrispASR/modelo + align
│   │   ├── bootstrap.py            # ensure_dependencies()
│   │   ├── timeline_builder.py     # timeline escena <-> cue del SRT
│   │   ├── capcut_project.py       # clonado/edición + overlays + chroma
│   │   ├── capcut_canonical.py     # helpers estructura CapCut
│   │   ├── imagina_esto.py         # post-proceso "IMAGINA ESTO"
│   │   └── subtitles.py            # motor de subtítulos
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
│   ├── smoke.py                 # pipeline completo sin UI
│   ├── auto_detect_check.py     # checks de detección + cancelación
│   ├── session_restore_check.py # restauración de config al reabrir la UI
│   ├── transcriber_import_check.py  # anti-typo CRISPASR + imports
│   ├── bootstrap_check.py       # descarga bin/modelo simulada
│   ├── subs_check.py            # subtítulos: fragmentación, estilo, trazo
│   ├── subtitle_layout_check.py # subtítulos: layout interno
│   ├── watermark_check.py       # marca de agua "NEXUS PARADOJA"
│   ├── color_grading_check.py   # color grading HSL por canal
│   ├── json_scales_check.py     # valores JSON EXACTOS
│   ├── imagina_esto_check.py    # post-proceso "IMAGINA ESTO"
│   ├── cancel_check.py          # cancelación con threading.Event
│   ├── fase2_e2e.py             # descarga real + alineación (autorizado)
│   ├── fase1_check.py           # checks base
│   ├── features_check.py        # features avanzadas
│   ├── ui_boot.py               # arranque UI
│   ├── ui_tarea1.py             # tarea UI 1
│   └── build_helpers.py         # plantilla/audio sintéticos
├── docs/
│   └── capcut_json_scales.md    # escalas JSON ↔ CapCut UI
└── README.md
✅ Verificación
powershell
& .venv\Scripts\python.exe -X utf8 tests\auto_detect_check.py
& .venv\Scripts\python.exe -X utf8 tests\smoke.py
& .venv\Scripts\python.exe -X utf8 tests\ui_boot.py
& .venv\Scripts\python.exe -X utf8 tests\session_restore_check.py
& .venv\Scripts\python.exe -X utf8 tests\transcriber_import_check.py
& .venv\Scripts\python.exe -X utf8 tests\subs_check.py
& .venv\Scripts\python.exe -X utf8 tests\watermark_check.py
& .venv\Scripts\python.exe -X utf8 tests\json_scales_check.py
& .venv\Scripts\python.exe -X utf8 tests\fase2_e2e.py
& .venv\Scripts\python.exe -X utf8 tests\subtitle_layout_check.py
& .venv\Scripts\python.exe -X utf8 tests\cancel_check.py
& .venv\Scripts\python.exe -X utf8 tests\imagina_esto_check.py
🔧 FIX v1.5.0 — Restauración "Imagina esto" + Audio seleccionado
Fix 1 — Restauración completa de "Imagina esto" (v1.4.0)
El post-proceso se había perdido en v1.5.0. Se restauró:

Módulo restaurado: src/core/imagina_esto.py.

Llamada restaurada en capcut_project.py tras _write_draft_content.

Config restaurada: IMAGINA_ESTO_KEYWORDS + IMAGINA_ESTO_CENTER_X/Y.

Log obligatorio [IMAGINA-ESTO] RESUMEN.

Fix 2 — Audio seleccionado en el pipeline
En main_window.py, al generar el proyecto se pasa self._audio_guion (el
del dropdown) al dict de project.generate().

El audio seleccionado se guarda en config_user.json como last_guion_name.

Lo que NO cambia: imágenes, transiciones, color grading, HSL, paneos,
camera shake, SFX, watermark, subtítulos, maintrack_adsorb=false.

🔥 HOTFIX v1.5.1 — Cancelación + fix audio guion
Bloque 1 — Cancelación (verificado ✅)
Diálogo modal de confirmación.

Bandera threading.Event (_cancel_event).

Checks en timeline_builder, subtitles, capcut_project, imagina_esto,
transcriber.

Matar subprocess de CrispASR al cancelar.

Cut limpio en bordes de "IMAGINA ESTO".

Bloque 2 — Fix audio guion (verificado ✅)
FIX A: _refresh_audio_menu usa comparación case-insensitive.
p.name.lower() == selected.lower(). Ahora el audio seleccionado en el
dropdown siempre se usa como pista principal.

FIX B: _on_audio_guion_changed también con comparación case-insensitive.
Ambos paths unificados.

Regla: el audio seleccionado en el dropdown manda. El nombre no importa.
Los demás quedan reservados. La auto-detección solo preselecciona el valor
inicial, no sobrescribe la elección del usuario.

Verificación obligatoria en CapCut
Generar con "IMAGINA ESTO" → fondo negro puro, subtítulo centrado.

Cambiar dropdown a otro audio → generar → audio en pista principal = el
seleccionado.

Cancelar durante alineación → crispasr.exe muere → reiniciar sin error
"Ya existe".

Bordes alrededor de "IMAGINA ESTO" → cortes limpios (sin transición).

Tests (todos verdes)
text
cancel_check.py:      8/8   OK
auto_detect_check.py: 37/37 OK
smoke.py:             OK
subs_check.py:        OK
watermark_check.py:   OK
json_scales_check.py: OK
color_grading_check:  OK
subtitle_layout:      OK
session_restore:      OK
bootstrap_check:      OK
transcriber_import:   OK
ui_boot:              OK
features_check:       OK
fase1_check:          OK
imagina_esto_check:   OK
scene_parser_check:   8/8   OK
🎨 v1.7.0 — Ducking dinámico + exclusión de escaneo

FIX BUG 1: Múltiples audios de fondo en pistas separadas
- Cada audio de fondo marcado ahora se coloca en SU PROPIA pista de audio.
- Antes, todos los audios iban a la misma pista y se pisaban entre sí.
- Ahora: pista video(0) + [text(1)] + audio guion(2) + BGM 1(3) + BGM 2(4) + BGM 3(5) + [sfx] + [watermark].

FIX BUG 2: Volumen dinámico basado en RMS (no lee del .txt)
- Se ignora el campo "Volumen: X dB a Y dB" del archivo de escenas.
- Se mide el RMS real de cada audio de fondo y de la narración (vía wave module).
- Ducking: la música baja al menos 8 dB por debajo del nivel de la voz durante los cues de narración.
- Idle: la música sube 4 dB por debajo de la voz en los silencios.
- Se usan keyframes KFTypeVolume dinámicos basados en los cues SRT (fade in 0.5s, fade out 0.5s, duck/idle según cues).
- Log obligatorio: [MUSICA-FONDO-VOL] audio.mp3 | rms_bg_dBFS=X | rms_voice_dBFS=Y | vol_duck_dB=Z | vol_idle_dB=W

FEATURE: Excluir archivos/carpetas del escaneo
- Nuevo bloque UI "Excluir del escaneo" en la sección 2 (Carpeta del video).
- Botón "Añadir exclusión... ▾" con dos opciones: archivo o carpeta.
- Cada exclusión se puede eliminar con el botón [✕].
- Los archivos/carpetas excluidos NO aparecen en:
  · Dropdown "Audio guion"
  · Lista "Otros audios detectados"
  · Detección de escenas .txt
  · Detección de imágenes
   · Detección de SRT
   · Cualquier escaneo recursivo
- Persistencia en config_user.json como clave "excluded_paths" (lista de rutas CSV).
- Al reabrir la app, se restauran las exclusiones.
- Si una exclusión ya no existe en disco, se ignora silenciosamente.
- Comparación de rutas normalizada con os.path.normcase + abspath.

---
Un solo espacio ASCII entre palabras de subtítulos.

content.styles[] cubre el texto INTEGRO y sin huecos.

Ningún carácter invisible en el texto de subtítulos.

Un único tamaño de fuente.

line_spacing = 0.0 y caja automática.

Posición vertical de subtítulos constante (-0.8333333).

Trazo de subtítulos = 30 en la UI (0.06 en JSON).

Letter spacing subtítulos = 0.

Subtítulos en MAYÚSCULAS.

Marca de agua propia, pista independiente.

Color grading HSL por canal.

Nunca tocar código no relacionado.

README siempre al día.

🎨 Color Grading HSL (detalle técnico)
3 materiales HSL en materials.hsl[]: Naranja (tipo 2), Cian (tipo 5), Azul
(tipo 6).

Base: hue=0, saturation=0, lightness=0 → animación 100% por keyframes.

Keyframes en segmentos: KFTypeHue, KFTypeSaturation, KFTypeLightSensatione.

Referencia: extra_material_refs en segmento + enable_hsl=true.

lumi_hub_path = path.

📜 Historial de versiones (solo tags reales)
Versión	Fecha	Descripción
v1.5.1	2026-09-26	Hotfix cancelación + fix audio guion (dropdown manda).
v1.5.0	2026-09-26	Selector de audios en UI.
v1.6.0	2026-09-30	Tipo de edición "Datos Y Cafe" (watermark/subtítulos distintos, sin efectos avanzados, soporte videos).
v1.7.0	2026-09-30	Exclusión de escaneo.
v1.4.0	2026-09-26	"Imagina esto" (post-proceso).
v1.3.0	2026-09-25	Watermark, auto-descarga, color grading, subtítulos, pop-up.
v1.2.1	2026-09-23	Chore: limpieza de tracking.
v1.2.0	2026-09-23	Fase 3: camera shake, HSL, paneos, SFX.
v1.1.0	2026-09-22	Fase 2: UI 2 paneles, subtítulos, modal verde.
v1.0.0	2026-09-22	Fase 1: alineación CrispASR + sincronización.
🗺️ Roadmap
Versión	Objetivo	Notas
v1.5.0	Selector de audios en UI	✅ Taggeada
v1.6.0	Tipo de edición "Datos Y Cafe"	✅ Taggeada
v1.7.0	Exclusión de escaneo	✅ Taggeada
v2.0.0	Nuevo tipo de edición (además de "Nexus Paradoja")	Última antes del .exe
v2.1.0	Empaquetado .exe + guardar app completa en la nube	Pendiente
v1.9.0 descartado.

📦 Empaquetado (.exe)
Se hará en v2.1.0. Planificación:

powershell
pip install pyinstaller
pyinstaller build.spec
Consideraciones:

Incluir bin/crispasr.exe y models/*.gguf en el .exe (vía build.spec).

Modificar el código para que, si se ejecuta como .exe (sys.frozen),
lea los recursos desde sys._MEIPASS en lugar de descargarlos.

Tamaño final esperado: >100 MB (por el modelo GGUF).

Distribución: .exe único o carpeta onedir.

Subida a la nube: decidir plataforma (pendiente).
📦 Pendiente (fuera de alcance)

Overlay de videos con chroma key en otros momentos (más allá de
Inicio/Suscríbete/Final).

Nuevos tipos de edición (v2.0.0).

---

## 🛠️ FIX v1.6.0 — Tipo de edición "Datos Y Cafe" (2026-09-30)

| Fix/Feature | Archivo(s) | Descripción |
|---|---|---|
| **FEATURE** Segundo tipo de edición | `src/core/edit_types.py` (nuevo), `src/ui/main_window.py`, `src/core/config.py`, `src/core/subtitles.py`, `src/core/capcut_project.py`, `src/core/auto_detect.py` | Dropdown "Tipo de edición" con 2 opciones: "Nexus Paradoja" (comportamiento actual) y "Datos Y Cafe" (nuevo). Perfiles definidos en `edit_types.py`. Nexus Paradoja conserva todas las features avanzadas (transiciones, color grading, HSL, paneos, shake, SFX, imagina). Datos Y Cafe: sin transiciones, sin color grading, sin HSL, sin paneos, sin shake, sin SFX, sin imagina. Watermark DATOS Y CAFE centrado (X=0, Y=0), opacidad 50%, tamaño 15, letter spacing 2. Subtítulos propios: fuente Anton/Bebas Neue/The Bold Font (gruesa), blanco #FFFFFF, contorno negro ~3.5px, posición Y=-775, keywords amarillas #FFD400, pop-up, MAYÚSCULAS, 2-5 palabras por fragmento. Soporte para videos mezclados con imágenes (cover scale + speed adjustment si video < frase). Medición de duración real del audio antes de construir el timeline para evitar huecos al final. Campo de nombre se actualiza en tiempo real al cambiar tipo (respeta escritura manual). Persistencia en `config_user.json` → `last_edit_type`. |

## 🛠️ FIX v1.7.0 — exclusión de escaneo (2026-09-30)

| Fix/Feature | Archivo(s) | Descripción |
|---|---|---|
| **FEATURE** Excluir del escaneo | `src/ui/main_window.py`, `src/core/auto_detect.py`, `src/core/config.py` | Bloque UI "Excluir del escaneo" en sección 2. Botón añadir archivo/carpeta, botón [✕] para eliminar. Persistencia en `config_user.json` → `excluded_paths`. Respetado en: `_detect_audio`, `_detect_scenes_txt`, `_detect_images`, `detect_audios`. Normalización con `os.path.normcase + abspath`. |

🏁 Fin del README — CapCut Auto v1.6.0 publicada.