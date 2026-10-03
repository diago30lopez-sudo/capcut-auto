# 🎬 CapCut Auto — Nexus Paradoja

**Versión actual:** v1.7.0
**Última actualización:** 2026-10-03

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
| **v1.7.0** | Edición AVANZADA de "Datos Y Cafe" (zoom, paneos, shake, fade in, 20 transiciones, color grading, HSL selectivo, viñeta, glow, overlays, SFX, BGM+ducking) | ✅ En desarrollo |
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

## 🛠️ FEATURE v1.7.0 — Edición AVANZADA de "Datos Y Cafe" (2026-10-02)

| Bloque | Feature | Archivo(s) | Descripción |
|---|---|---|---|
| **1** | Botón carpeta assets | `src/ui/main_window.py`, `src/core/config.py` | Botón "Seleccionar carpeta de assets..." visible SOLO en DYC. Persiste en `config_user.json` → `dyc_assets_dir`. Aborta si falta la carpeta. |
| **2** | Animación inicio (1 de 3) | `src/core/capcut_project.py` | Aleatoria entre: TV retro (7575...), Rompecabezas (7372...), Celular 3D (7522...). Se aplica a la PRIMERA imagen con sticker_animation type="in". |
| **3** | Animación final (agujero negro) | `src/core/capcut_project.py` | resource_id 7294461821170225666, type="out", duration=0.8s (800000 µs, FIX 3). Se aplica a la ÚLTIMA IMAGEN (no pantalla final) con start=dur_segmento-800000. resource_id y path sin tocar. |
| **4** | Pantalla final | `src/core/capcut_project.py` | Video "Pantalla final.mp4" en el TRACK PRINCIPAL (bloque 6), arranca en el FIN REAL DEL AUDIO (FIX 5 bloque 5 / FIX 3 bloque 6) con transición GLITCH desde la última imagen y color grading. Sin chroma. |
| **5** | Suscríbete corto (CTA INTERMEDIO) | `src/core/timeline_builder.py`, `src/core/capcut_project.py` | Overlay video en el TRACK CTA (flag=2, visible=true) al 37% del video, alineado a frame (33333 µs). Chroma key negro intensity=0.3. |
| **6** | Suscríbete largo / CTA FINAL | `src/core/timeline_builder.py`, `src/core/capcut_project.py` | Detecta "suscríbete" en SRT (normalizado sin tildes). Position = start del cue. Fallback: 90%. Chroma intensity=0.3, volume=1.0. |
| **7** | Audio inicio + final | `src/core/capcut_project.py` | Desde caché CapCut por effect_id: inicio 7200479771514374146 (2.57s), final 6974428544046729218 (1s). Si no existe en caché, log y omite. |
| **8** | 27 transiciones con IDs | `src/core/capcut_project.py`, `src/core/timeline_builder.py` | Pool de 27 transiciones con effect_id reales ("Elige otro" EXCLUIDA siempre, FIX 1). Orden aleatorio, sin repetir consecutivas. is_overlap=true. Referencia en segmento ANTERIOR. Subconjunto GLITCH aparte para el corte final. |
| **9** | Color grading + HSL exactos | `src/core/capcut_project.py` | 7 materiales en materials.effects (contrast/saturation/sharpen/highlight/shadow/light_sensation/vignetting). 2 materiales HSL (Rojo type=1, Amarillo type=3). Shared por segmento. enable_adjust=true, enable_hsl=true. |
| **10** | Zoom 100→110 | `src/core/edit_types.py` | DYC: zoom_end_min=1.00, zoom_end_max=1.10. Keyframes KFTypeScaleX/Y RELATIVOS a cover_scale. |
| — | Aislamiento | `src/core/edit_types.py` | Nexus Paradoja SIN cambios (regresión verificada). Cada tipo usa su propio perfil aislado. |

**PENDIENTES (TODO):**
- Watermark no carga en preview: bug de CapCut/caché, diagnóstico independiente.
- Recurso de transicion no descargado en la caché local: CapCut lo baja por resource_id al abrir el proyecto (aviso en log, no rompe el JSON).

Hotfix 3: duración de .mp4 medida con parser MP4 en Python puro; ffprobe pasa a ser fallback opcional.

v1.7.0 Ajustes finales DYC (bloque 2):
- CTA INTERMEDIO desplazado al 37% (punto medio 35-40%).
- CTA FINAL: búsqueda accent-insensitive en SRT + soporte multi-CTA con delay 1 min.
- Subtítulos DYC: fuente configurada Bungee-Rg (fallback temporal Frick0.3-Rg, ya retirado en el bloque 5).
- Audios inicio/final: búsqueda robusta en caché de CapCut (ruta directa con/sin extensión, glob, efecto).

v1.7.0 Ajustes finales DYC (bloque 3):
- Animación de entrada aleatoria (1 de 3) desde pool DYC_INTRO_ANIMATIONS con rutas completas.
- Sync: bloque 5 corrigió este punto: la narración NUNCA se recorta (ver bloque 5).
- Limpieza de tracks fantasma (segmentos duplicados) + reorden garantizado: video → overlays CTA → text → watermark → audio.

v1.7.0 Ajustes finales DYC (bloque 5) — 2026-10-03:
- FIX 1: "Elige otro" eliminada del pool; el filtro y el selector comparten la misma lista (27 entradas).
- FIX 2: corte GLITCH aleatorio (1 de 7) entre la última imagen y "Pantalla final.mp4", mismo patrón de referencia (segmento anterior + is_overlap=true).
- FIX 3: agujero negro a 0.8s (800000 µs); termina exactamente al final de la última imagen.
- FIX 4: audio final "Switch on / off" arranca en el agujero negro, volumen -10dB (10 ** (-10/20)); duración real de narración intacta.
- FIX 5: la narración NUNCA se recorta por SRT. Fin real del audio = 777760000 µs; última imagen y pantalla final terminan ahí. Se eliminó la suma acumulativa de duraciones (error de 720000 µs) y se usa `last.start_us`.
- FIX 6: patrón de transiciones verificado contra el draft de referencia (segmentos contiguos, sin overlap artificial, `resource_id == effect_id`, referencia en el segmento ANTERIOR).
- FIX 7: CTA en un ÚNICO track `visible=true`, situado tras el video principal, con `render_index=11000` (mayor que las imágenes) y materiales de CTA registrados en `materials.videos`.
- FIX 8: CTA intermedio + todos los CTA finales + pantalla final en el mismo track. Orden final: video → CTA → subtítulos → watermark → audio narración → audios extra. Tracks fantasma eliminados.
- FIX 9: subtítulos DYC con Bungee-Rg real (resource_id 7533527101870214401) en `font_path`, `font_resource_id`, `materials.texts[].fonts[]` y `content.styles[].font.{id,path}`. Retirado el fallback Frick0.3-Rg.

v1.7.0 Ajustes finales DYC (bloque 6) — 2026-10-03:
- FIX 1: "Pantalla final.mp4" va en el MISMO track principal de video, justo después de la última imagen (`start = start_última_img + dur_última_img`, duración real del archivo medida con el parser MP4). Ya no existe ningún track de video exclusivo para ella.
- FIX 2: la transición GLITCH (1 de 7, subconjunto `DYC_GLITCH_TRANSITIONS`) se aplica REALMENTE entre la última imagen y la pantalla final: ambos clips están en el mismo track, el material va en `materials.transitions[]` y se referencia en `extra_material_refs` del segmento ANTERIOR (la última imagen), con `is_overlap=true` y sin solapar `target_timerange`.
- FIX 3: la última imagen termina EXACTAMENTE en el fin real del audio (`sync_last_item_to_audio_end` en `timeline_builder.py`); solo se ajusta esa imagen, nunca las anteriores. Pantalla final empieza en ese mismo instante. Sin hueco entre imagen y audio.
- FIX 4: chroma key SOLO en CTA INTERMEDIO y CTA FINAL, con `intensity_value=0.25` (`DYC_CHROMA_INTENSITY`); la pantalla final va sin chroma.

Verificación (solo DYC, Nexus intacto):
```
python -m py_compile src/core/edit_types.py src/core/timeline_builder.py src/core/capcut_project.py src/core/subtitles.py
python tests/edit_types_check.py
python tests/subs_check.py
python tests/dyc_advanced_check.py
python tests/features_check.py
python tests/smoke.py
python tests/cancel_check.py
python tests/watermark_check.py
python tests/json_scales_check.py
python tests/color_grading_check.py
```
- End-to-end VIDEO 4 (192 imágenes): 75/75 checks OK, 192 transiciones, agujero negro en 776960000 µs, última imagen + audio en 777760000 µs, CTA `['CTA INTERMEDIO', 'CTA FINAL_cta1']`.
- Aislamiento Nexus: 18/18 checks OK (ningún artefacto DYC en el proyecto Nexus, pool de 11 intacto, 1 solo track de video).