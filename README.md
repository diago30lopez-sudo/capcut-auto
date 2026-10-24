# 🎬 CapCut Auto

Motor genérico de perfiles JSON para generar drafts de CapCut Desktop automáticamente.

**Versión actual:** v3.0.0  
**Última actualización:** 2026-10-22  
**Tag GitHub:** [v2.0.3](https://github.com/diago30lopez-sudo/capcut-auto/releases/tag/v2.0.3)

> ⚠️ **IMPORTANTE:** CapCut debe estar **CERRADO** durante la generación.

---

## Índice

- [Qué es](#qué-es)
- [Stack tecnológico](#stack-tecnológico)
- [Arquitectura](#arquitectura)
- [Instalación](#instalación)
- [Uso](#uso)
- [Perfiles JSON](#perfiles-json)
- [Guía de perfiles para IA](#guía-de-perfiles-para-ia)
- [Compilación y distribución](#compilación-y-distribución)
- [Historial de versiones](#historial-de-versiones)
- [Bugs conocidos y resueltos](#bugs-conocidos-y-resueltos)
- [Roadmap](#roadmap)
- [Método de trabajo](#método-de-trabajo)
- [Glosario](#glosario)
- [Preguntas abiertas](#preguntas-abiertas)

---

## Qué es

**CapCut Auto** genera borradores nativos de CapCut Desktop sin intervención manual. A partir de tres insumos —un audio de narración, un guion de escenas en texto (`escenas.txt`) y una carpeta de recursos visuales— produce un proyecto completamente editable en CapCut.

### ¿Qué hace?

1. **Alinea voz e imágenes** con precisión de microsegundo usando CrispASR (forced alignment).
2. **Genera subtítulos** con fuentes personalizadas, colores de resalte por palabra clave y trazos de contorno.
3. **Compon multicapa**: video base, transiciones nativas, pistas CTA con chroma key, pantallas finales y marcas de agua continuas.
4. **Mezcla audio dinámicamente**: música de fondo con ducking automático respecto a la voz.
5. **Aplica estilos editoriales** distintos según el perfil JSON seleccionado.

### Canales

El proyecto soporta dos canales con identidades visuales completamente aisladas:

- **Nexus Paradoja**: edición cinematográfica con transiciones, color grading HSL, paneos, camera shake, SFX, imagina-esto y watermark tenue.
- **Datos Y Café (DYC)**: edición de ritmo dinámico sin efectos cinematográficos, con fuentes gruesas, CTA con chroma, animaciones de entrada/salida y zoom automático.

### Filosofía v3.0.x

Desde v3.0.0, la app es un motor 100% ciego. **Ninguna decisión de edición vive en el código Python.** Transiciones (cada N cortes, índices exactos, keywords), assets extra con triggers y chroma, duración de imágenes, volumen de audios — todo viene dictado por el archivo de perfil JSON. Para cambiar el comportamiento visual, modifica el JSON; nunca el código Python.

Para crear perfiles desde cero, consulta [`GUIA_PERFILES.md`](./GUIA_PERFILES.md).

---

## Stack tecnológico

| Componente | Tecnología | Detalle |
|---|---|---|
| **Lenguaje** | Python 3.14 x64 | Compatible con 3.12+ |
| **UI** | CustomTkinter 6.0.0 + Tkinter | Temas oscuros, widgets modernos |
| **Imágenes** | Pillow >= 10.0.0 | Procesamiento de imágenes y videos |
| **ASR / Alineación** | CrispASR v0.8.35 | Binario C++ x86_64 CPU + OpenBLAS |
| **Modelo acústico** | FastConformer Hybrid CTC Large | GGUF Q4_K (~66 MB), español |
| **Coincidencia difusa** | RapidFuzz | Parsing flexible de escenas y subtítulos |
| **Parser multimedia** | Parser MP4 nativo Python + ffprobe | Duraciones precisas en µs |
| **Empaquetado** | PyInstaller 6.22.3 | onedir, sin consola |

### Descartado

| Tecnología | Motivo del descarte |
|---|---|
| **faster-whisper** | Requiere GPU; el flujo usa CrispASR que corre en CPU |
| **ffmpeg** | ffprobe solo como fallback; el parser MP4 nativo es suficiente |
| **Modelo small de CrispASR** | Insuficiente para español; se usa el modelo large Q4_K |
| **Música de fondo automática** | Descartado del roadmap — el usuario aporta sus propios audios |
| **Detección de inglés** | Fuera de alcance del proyecto actual |

---

## Arquitectura

### Árbol de carpetas

```
capcut-auto/
├── src/
│   ├── main.py                          # Punto de entrada: bootstrap + UI
│   ├── ui/
│   │   └── main_window.py               # Ventana CustomTkinter (6 secciones)
│   ├── core/
│   │   ├── config.py                    # Rutas EXE_DIR/BUNDLE_DIR + constantes
│   │   ├── auto_detect.py               # Detección heurística de inputs
│   │   ├── scene_parser.py              # Parsing de escenas.txt (NO TOCAR)
│   │   ├── transcriber.py               # CrispASR + alineación (NO TOCAR)
│   │   ├── bootstrap.py                 # ensure_dependencies()
│   │   ├── timeline_builder.py          # Escena ↔ cue SRT (NO TOCAR chunking)
│   │   ├── capcut_project.py            # Clonado, edición + overlays (NO TOCAR)
│   │   ├── capcut_canonical.py          # Helpers estructura CapCut
│   │   ├── imagina_esto.py              # Post-proceso "IMAGINA ESTO"
│   │   ├── subtitles.py                 # Motor de subtítulos (NO TOCAR)
│   │   ├── profile_schema.py            # Dataclasses + validación de perfiles
│   │   ├── profile_loader.py            # Carga dinámica de profiles/*.json
│   │   └── pipeline.py                  # Orquestación del pipeline
│   └── utils/
│       └── logger.py                    # Logging cola → UI + archivo
├── profiles/
│   ├── nexus.json                       # Perfil Nexus Paradoja
│   └── dyc.json                         # Perfil Datos Y Café
├── bin/                                 # crispasr.exe (descargado en 1ª ejecución)
├── models/                              # Modelo GGUF (descargado en 1ª ejecución)
├── logs/                                # app.log + schemas
├── cache/                               # Guiones temporales + SRT de alineación
├── backups/                             # Copias de seguridad de plantillas
├── config_user.json                     # Configuración persistida del usuario
├── build.spec                           # Especificación PyInstaller
├── requirements.txt                     # Dependencias de desarrollo
├── run.bat                              # Launcher rápido
├── tests/                               # Suite de pruebas
└── plans/reportes/                      # Reportes de diagnóstico y planificación
```

### Módulos NO TOCAR

Los siguientes módulos contienen lógica crítica que no debe modificarse fuera de su ámbito de trabajo:
- `src/core/transcriber.py` — manejo de subprocess CrispASR
- `src/core/scene_parser.py` — parsing de escenas.txt
- `src/core/subtitles.py` — motor de generación de subtítulos
- `src/core/timeline_builder.py` — construcción del timeline (chunking)
- `src/core/capcut_project.py` — ensamblado del draft (sync, transiciones, color grading, HSL)

### Pipeline de 5 pasos

1. **Bootstrap** → Verifica que `crispasr.exe` y el modelo GGUF existen; si no, los descarga.
2. **Detección** → Escanea la carpeta del video buscando audio, escenas e imágenes.
3. **Alineación** → Ejecuta CrispASR para obtener el SRT word-level.
4. **Construcción** → Genera el draft clonando la plantilla y aplicando el perfil seleccionado.
5. **Post-proceso** → Aplica reglas especiales (imagina-esto, CTA, chroma, etc.).

La alineación maneja tres casos de jerarquía:
- **SRT word-level** (CrispASR): preferido, máximo detalle temporal.
- **SRT sentence-level**: fallback si no hay word-level.
- **Sin SRT**: el sistema estima duraciones proporcionalmente.

---

## Instalación

```powershell
# Crear entorno virtual
python -m venv .venv314
& .venv314\Scripts\Activate.ps1
pip install -r requirements.txt

# Primera ejecución: descargará automáticamente CrispASR y el modelo GGUF
python src\main.py
# o directamente run.bat
```

### Requisitos previos

- Windows 10+ x64
- Python 3.12 o 3.14
- CapCut Desktop instalado (para abrir los drafts generados)

### Archivos generados en la primera ejecución

| Archivo | Ubicación | Contenido |
|---|---|---|
| `bin/crispasr.exe` | Junto al repo | Binario de alineación forzada |
| `models/stt-es-*.gguf` | Junto al repo | Modelo acústico español (~66 MB) |
| `config_user.json` | Junto al repo | Preferencias del usuario |

---

## Uso

### La interfaz tiene 6 secciones + 2 botones:

1. **Carpeta CapCut Drafts** — Botón seleccionar carpeta. Los drafts se generan aquí.
2. **Carpeta del video** — Al elegirla se ejecuta el escaneo inteligente y muestra:
   - ✓ Audio: `guion.wav`
   - ✓ Escenas: `escenas.txt` (N escenas)
   - ✓ Imágenes: `escenas 2/` (N archivos)
   - Si falta algo, aparece en rojo y el botón Generar se deshabilita.
3. **Subtítulos (.srt)** — Busca .srt en la carpeta del video y en el caché de alineación.
4. **Tipo de edición** — Dropdown: "Nexus Paradoja" o "Datos Y Café".
5. **Nombre del proyecto** — Campo de texto libre.
6. **Excluir del escaneo** — Añadir archivos o carpetas que no deben escanearse.

### Botones

- **Generar proyecto** (verde): ejecuta el pipeline completo. Barra de progreso indeterminada + logs en tiempo real.
- **Cancelar** (rojo): modal de confirmación → envía evento de cancelación → mata subprocess CrispASR → limpia carpeta a medias.

### Dónde queda el draft

En la carpeta CapCut Drafts seleccionada, dentro de una subcarpeta con el nombre del proyecto. Para abrirlo en CapCut: abrirla y dar doble clic en el draft.

---

## Perfiles JSON

### Estructura

Cada archivo en `profiles/*.json` define un canal completo: fuentes, animaciones, colores, transiciones, CTA, chroma, watermark, etc.

### Perfiles existentes

| Archivo | Canal | Características |
|---|---|---|
| `profiles/nexus.json` | Nexus Paradoja | Cinemático: transiciones, HSL, paneos, shake, SFX, imagina-esto, watermark tenue |
| `profiles/dyc.json` | Datos Y Café | Dinámico: sin efectos avanzados, CTA chroma, fuentes gruesas, zoom, animaciones |

### Guía para IAs

Para que cualquier modelo de IA pueda crear o modificar perfiles JSON de CapCut Auto de forma autónoma, consulta la [**GUIA_PERFILES.md**](./GUIA_PERFILES.md), que documenta exhaustivamente todos los campos del schema v3.0.0 con ejemplos JSON reales.

### Regla de aislamiento

Los perfiles son completamente independientes. Un cambio en `dyc.json` no afecta a `nexus.json` ni viceversa. El código Python nunca contiene valores específicos de ningún canal.

---

## Compilación y distribución

A partir de **v2.0.3**, CapCut Auto se distribuye como bundle portable generado con PyInstaller (`onedir`).

### Compilar

```powershell
cd D:\capcut-auto
.venv314\Scripts\python.exe -m PyInstaller --clean --noconfirm build.spec
```

Resultado: `dist\CapCutAuto\`

### Distribuir

```powershell
xcopy /E /I /Y dist\CapCutAuto C:\Ruta\Destino\CapCutAuto
```

El usuario puede ejecutar `CapCutAuto.exe` desde cualquier carpeta sin instalar Python ni dependencias.

### Portabilidad

- `config_user.json`, `logs/`, `cache/`, `backups/` se crean junto al `.exe` (`EXE_DIR`).
- Recursos empaquetados (`bin/`, `models/`, `profiles/`) viven en `_internal/` (`BUNDLE_DIR`).
- Al copiar la carpeta completa, la configuración viaja con ella.

### Tamaño

~132 MB (Python runtime ~49 MB + Pillow ~15 MB + modelo GGUF ~66 MB + bin/crispasr ~19 MB).

### Estructura del bundle

```
CapCutAuto/
├── CapCutAuto.exe              # Ejecutable principal (~3.5 MB)
├── _internal/                  # PyInstaller bootloader + Python + libs
│   ├── bin/                    # crispasr.exe, openblas.dll, LICENSE
│   ├── models/                 # stt-es-fastconformer-hybrid-ctc-large-q4_k.gguf
│   ├── profiles/               # nexus.json, dyc.json
│   ├── customtkinter/          # assets (fonts, themes, icons)
│   ├── PIL/                    # Pillow
│   ├── rapidfuzz/              # RapidFuzz
│   └── ...                     # Python runtime
├── config_user.json            # Se crea al primer uso
├── logs/                       # app.log
├── cache/                      # Alineaciones temporales
└── backups/                    # Copias de seguridad
```

---

## Historial de versiones

### v1.0.0 — 2026-09-23 — Alineación CrispASR y sincronización inicial

Primer release funcional. Reemplaza el montaje manual de escenas sincronizadas con voz.

**Cambios:**
- Integración de CrispASR con modelo FastConformer español para alineación forzada.
- Construcción del primer clonador de proyectos CapCut Desktop.
- Generación de `draft_content.json` con duraciones en microsegundos.

**Aprendizaje:** CapCut usa microsegundos enteros (1s = 1,000,000 µs); la suma de duraciones debe ser exacta para evitar desfases acumulados.

### v1.1.0 — 2026-09-23 — UI de dos paneles y primeros efectos

Primera interfaz gráfica que permite a usuarios no técnicos usar la herramienta.

**Cambios:**
- Creación de `MainWindow` en CustomTkinter con 6 secciones.
- Pista inicial de subtítulos automáticos.
- Efectos de cámara: camera shake y paneos básicos.

### v1.2.0 — 2026-09-23 — Watermark NEXUS PARADOJA

Protección de contenido con marca de agua permanente.

**Cambios:**
- Pista dedicada para watermark que abarca todo el metraje.
- Ajuste de contornos (stroke) en subtítulos.

### v1.2.1 — 2026-09-23 — Limpieza de tracking

**Cambios:**
- Retiro de `bin/` y `config_user.json` del tracking de git.
- `.gitignore` definitivo excluyendo cachés, logs y backups.

### v1.3.0 — 2026-09-25 — Calibración de escalas empíricas

Los textos aparecían desplazados y con escalas incorrectas en CapCut.

**Cambios:**
- Auditoría visual de fórmulas: posición Y = `UI_Y / 1080` (canvas completo, no mitad).
- Grosor de trazo: `UI / 500` (UI 30 = JSON 0.06).
- `bootstrap.py` para descarga automática de dependencias.
- Corrección de opacidad watermark: `global_alpha = 0.15` con `fill.alpha = 1.0`.

### v1.4.0 — 2026-09-26 — Motor cinemático "Imagina esto"

Para guiones con frases de inmersión o giros narrativos, se buscaba un impacto dramático.

**Cambios:**
- `src/core/imagina_esto.py`: detección de keywords (ej. *"imagina esto"*, *"supón que"*).
- En segmentos coincidentes: subtítulo centrado (X=0, Y=0) + video de fondo oculto.
- Corte limpio sin transiciones laterales.

### v1.5.0 — 2026-09-26 — Selector de audios en UI

En proyectos con múltiples audios, el sistema podía confundir la narración con pistas secundarias.

**Cambios:**
- Escaneo recursivo categorizando audios en UI.
- Dropdown para seleccionar explícitamente el audio del guion.
- Los demás audios quedan identificados para uso como SFX.

### v1.5.1 — 2026-09-26 — Hotfix: cancelación segura

El usuario no podía abortar procesos sin colgar la aplicación.

**Cambios:**
- `threading.Event` (`_cancel_event`) en todas las fases críticas del pipeline.
- Terminación forzada de `crispasr.exe` al cancelar (`proc.terminate()` / `kill()`).
- El audio seleccionado en el dropdown manda siempre (comparación case-insensitive).
- Limpieza de carpetas a medias tras cancelación.

### v1.6.0 — 2026-10-01 — Segundo estilo: Datos Y Café

Expansión para soportar un canal con identidad visual distinta: sin efectos cinematográficos agresivos, ritmo dinámico, soporte para clips de video intercalados.

**Cambios:**
- `src/core/edit_types.py`: perfiles diferenciados por código.
- Estilo DYC: sin transiciones complejas ni HSL; watermark centrado (50% opacidad); subtítulos con fuente gruesa, contorno negro y keywords amarillas (`#FFD400`).
- Soporte para clips de video (`.mp4`) escalados a pantalla completa.

### v1.7.0 — 2026-10-03 — Edición avanzada DYC y ducking de audio

Automatizaciones de producción completa para el estilo DYC.

**Cambios:**
- CTA intermedio (37% del video) y CTA final con chroma key (`intensity_value=0.25`).
- Animación final de salida (agujero negro, 0.8s) sincronizada con el último fotograma.
- Pantalla final en el track principal sin transiciones solapadas.
- Ducking dinámico basado en RMS: música baja 8 dB durante voz, sube 4 dB en silencios.
- Exclusión selectiva de archivos/carpetas del escaneo.
- 27 transiciones con `effect_id` reales de CapCut.

**Fixes posteriores (2026-10-03):**
- FIX 5: la narración NUNCA se recorta por SRT; fin real del audio = medida exacta.
- FIX 7: CTA en un ÚNICO track `visible=true`, `render_index=11000`.
- FIX 9: fuente Bungee-Rg real (resource_id 7533527101870214401) para subtítulos DYC.

### v2.0.0 — 2026-10-11 — Motor genérico de perfiles JSON

La coexistencia de Nexus y DYC mediante condicionales `if/else` hacía el código rígido e impedía añadir nuevos canales sin refactorizar.

**Decisión arquitectónica:** Extraer toda configuración a JSON declarativos en `profiles/`, validados por dataclasses en `profile_schema.py`.

**Cambios:**
- Eliminación de `edit_types.py`.
- Creación de `profile_loader.py` y `pipeline.py`.
- Fuentes y assets resolubles desde el JSON (ruta local o resource_id de CapCut cloud).
- Aislamiento total: modificar un perfil no afecta a los demás.

**Contexto del incidente:** Durante el desarrollo, el working tree se vio afectado por cambios no versionados. Se instauró disciplina estricta: commits atómicos, tags para cada versión, backups manuales antes de cambios grandes, y rollback con `git checkout`.

### v2.0.1 — 2026-10-11 — Fix: transiciones DYC no visibles en preview

**Causa raíz:** Inconsistencia en `render_index` y solapamiento de identificadores de recursos en `materials.transitions`.

**Fix:** Estandarización de referencias con `is_overlap=True` y vinculación explícita de `effect_id`.

### v2.0.2 — 2026-10-11 — Fix: fuentes DYC visibles en preview

**Causa raíz:** La fuente Bungee-Rg requería ruta exacta o `resource_id` correcto de la nube de CapCut.

**Fix:** Calibración de `font_path` en `profiles/dyc.json` + posición Y=-850, tamaño 10.

### v2.0.3 — 2026-10-11 — Eliminación de doble carga del JSON en RAM

**Síntoma:** Cuelgues intermitentes o congelamiento prolongado al generar proyectos largos (~300 escenas DYC) en equipos con recursos limitados (i5-6200U, 8 GB RAM, disco casi lleno).

**Diagnóstico inicial erróneo:** Se sospechó de millones de `deepcopy()` en el bucle principal.

**Análisis real:** El JSON del proyecto se cargaba DOS veces en RAM:
1. Una vez al escribir `draft_content.json` en `_write_draft_content()`.
2. Otra vez al leerlo desde disco en `imagina_esto.aplicar()` para el post-proceso.

Además, `_write_draft_content()` serializaba con `indent=2`, duplicando el tamaño en ~25%.

**Fix aplicado (5 cambios concretos):**
1. `capcut_project.py:_write_draft_content()` — Cambiar `indent=2` por `separators=(",",":")` en la primera serialización (JSON comprimido).
2. `capcut_project.py:_write_draft_content()` — Usar `shutil.copy2()` para la copia a `Timelines/<id>/` en lugar de serializar de nuevo.
3. `capcut_project.py:generate()` — Pasar el diccionario `content` ya cargado a `aplicar()` en lugar de dejar que lo relea desde disco.
4. `imagina_esto.py:aplicar()` — Añadir parámetro opcional `content` para recibir el dict directo.
5. `imagina_esto.py:aplicar()` — Si `content` se pasa, usarlo directamente sin relectura desde disco.

**Verificación visual:** RAM pico bajó de >95% a ~85%, disco del 100% al 89%, sin cuelgues. Proyecto de 300 escenas DYC generado exitosamente.

**Nueva feature:** Compilación portable con PyInstaller (bundle de 132 MB). README maestro con documentación completa.

### v3.0.0 — 2026-10-22 — Motor de Reglas (Rule Engine) y Autonomía Total

**Decisión arquitectónica:** La app pasa a ser un motor 100% ciego. NINGUNA decisión de edición debe estar en el código Python. TODO (transiciones, assets, layout, chroma, animaciones, audios) debe venir dictado por el archivo de perfil JSON.

**Cambios:**
- Eliminación total de condicionales `if is_nexus()/is_dyc()` y hardcodeos en el código.
- Nuevo sistema `transition_rules` (every_n, specific_cuts, keyword, random).
- Nuevo sistema `layout_rules` (audio_sync, fixed_gap, fixed_duration).
- Inyección universal de `extra_assets` (audios, videos, chroma key) con triggers (`start`, `end`, `black_hole_start`, `time_us`).
- Duración de animaciones leída directamente del JSON (`dyc.end_animation.duration_us`), con clamp automático al segmento.
- Creación de `GUIA_PERFILES.md` para generación de perfiles por IA.
- Lógica de CTA 100% JSON: patrones desde `cta.patterns`, solapamiento controlado por `avoid_overlap_with_end`.
- Eliminación de funciones `_is_nexus()`, `_is_dyc()`, `_is_dyc_profile()`, `_profile_id()` del ensamblado.

**Bug fix crítico:** Se eliminó la transición de glitch entre la última imagen y la pantalla final cuando ya existe una animación de salida (agujero negro), pues ambas competían por el mismo segmento y CapCut las rechazaba.

---

## Bugs conocidos y resueltos

| ID | Título | Versión aparición | Versión resolución | Causa raíz | Solución |
|---|---|---|---|---|---|
| **BUG-A** | Desfase vertical en subtítulos | v1.2.0 | v1.3.0 | Coords Y asumidas sobre half-canvas (540 px) | `JSON_Y = UI_Y / 1080` (canvas completo) |
| **BUG-B** | Watermark invisible en preview | v1.3.0 | v1.7.0 | Falta `global_alpha` explícito en material | Material con `global_alpha=0.15` + `fill.alpha=1.0` |
| **BUG-C** | Transiciones no descargadas | v1.6.0 | v1.7.0 | `resource_id` ≠ `effect_id` en catálogo CapCut | Pool de 27 transiciones con IDs reales verificados |
| **BUG-D** | CrispASR huérfano al cancelar | v1.5.0 | v1.5.1 | Cancelación no terminaba subprocess nativo C++ | `proc.terminate()` + `proc.kill()` en handler |
| **BUG-E** | Audio guion erróneo autoseleccionado | v1.5.0 | v1.5.1 | Auto-detección sobrescribía elección del dropdown | Dropdown manda siempre, comparación case-insensitive |
| **BUG-F** | Pistas de audio solapadas | v1.6.0 | v1.7.0 | Todos los audios en una sola pista | Pistas separadas: video(0), CTA(1), text(2), WM(3), voz(4), BGM(n) |
| **BUG-H** | Desfase al final de la narración | v1.6.0 | v1.7.0 | Suma de duraciones estimadas vs. duración real del audio | Parser de encabezados MP4 para duración exacta |
| **BUG-I** | Cuelgue por alto uso de RAM | v2.0.0 | v2.0.3 | Doble carga del JSON en RAM (write + re-read) | Pasar contenido directo, serializar una vez con separators |
| **BUG-J** | Rutas rotas en ejecutable congelado | v2.0.0 | v2.0.3 | `Path(__file__)` resolvía a `_MEIPASS` (temporal) | `EXE_DIR` (persistente) vs. `BUNDLE_DIR` (lectura) |
| **BUG-K** | Fuentes no visibles en bundle | v2.0.1 | v2.0.2 | Fallback a fuentes del sistema fallaba fuera del repo | `font_resource_id` correcto de CapCut cloud en perfil DYC |

### Detalles de bugs críticos

**BUG-I (RAM, v2.0.3):** El síntoma más crítico del proyecto. Con proyectos de 300+ escenas DYC, la RAM pico alcanzaba >95% y el disco se llenaba al 100%, congelando el equipo. El diagnóstico inicial apuntó a `deepcopy()` masivo, pero el análisis mostró que el problema real era la doble serialización/lectura del JSON completo (~50 MB) en la transición entre `capcut_project.generate()` e `imagina_esto.aplicar()`. La solución: evitar la relectura pasando el objeto ya construido, y usar serialización compacta (`separators=(",",":")`) que reduce el tamaño del JSON ~25%.

**BUG-J (rutas, v2.0.3):** Antes del fix, `ROOT_DIR = Path(__file__).parent.parent.parent` resolvía a `_MEIPASS` cuando se ejecutaba el .exe, que es un directorio temporal eliminado al cerrar la app. Esto hacía que `config_user.json`, `logs/`, `cache/` y `backups/` se perdieran entre ejecuciones. El fix separa `EXE_DIR` (junto al .exe, persistente) de `BUNDLE_DIR` (desde `_MEIPASS`, solo lectura).

---

## Roadmap

### Completado
- [x] v1.0.0 → v1.7.0: pipeline completo, estilos Nexus y DYC
- [x] v2.0.0: motor genérico de perfiles JSON
- [x] v2.0.1 → v2.0.3: fixes de transiciones, fuentes y RAM; bundle portable
- [x] v3.0.0: motor de reglas (transition_rules, extra_assets, layout_rules); aislamiento total; GUIA_PERFILES.md

### Pendientes
- [ ] BUG I residual: modal "(No responde)" durante generación en proyectos muy largos
- [ ] BUG B: clips perdidos (verificar en v2.0.x)
- [ ] BUG C definitivo: nombres ASCII para cache de CrispASR
- [ ] v2.1.0: perfil cinematográfico para formato vertical (9:16 — Shorts/Reels/TikTok)
- [ ] v2.2.0: detección automática de fuentes ausentes desde Google Fonts / CapCut Asset Cloud
- [ ] v2.3.0: instalador guiado Windows (Inno Setup) con actualización automática
- [ ] Releases numeradas en GitHub (adjuntar .zip del bundle)

### Descartados
- [x] Música de fondo automática → fuera de alcance
- [x] Detección de inglés → fuera de alcance
- [x] faster-whisper → descartado (usa CrispASR CPU)
- [x] ffmpeg → descartado (parser MP4 nativo es suficiente)
- [x] Modelo "small" de CrispASR → descartado (insuficiente para español)
- [x] v1.9.0 (tv_control + flash + reset) → descartado

---

## Método de trabajo

### Ciclo obligatorio

Toda modificación técnica sigue estas fases:

1. **ANÁLISIS:** Leer el código existente, identificar archivo:línea, entender el problema.
2. **PLAN:** Escribir `plans/reportes/YYYY-MM-DD_<slug>.md` con diffs literales, código propuesto y evaluación de riesgo.
3. **ESPERA:** No ejecutar nada hasta recibir aprobación explícita del usuario.
4. **EJECUCIÓN:** Aplicar cambios mínimos, `py_compile` en cada .py tocado, `git diff` para verificar.

### Reglas de oro

- **No tocar lo que no se pide:** transcriber, scene_parser, chunking, sync, transiciones, color grading, HSL, paneos, shake, SFX, watermark, UI, perfiles JSON.
- **Sin rutas hardcodeadas:** todo debe funcionar desde el repo y desde el bundle portable.
- **Portabilidad total:** el bundle debe correr desde cualquier carpeta sin depender de la ubicación original.
- **Reportes siempre en `plans/reportes/`** con timestamp en el nombre.
- **Nunca hacer git add/commit/push/tag** — lo lleva el usuario.

### Reglas de commit

- Una línea por commit, SemVer en tags.
- Tipos: `feat:`, `fix:`, `perf:`, `chore:`, `docs:`, `refactor:`.
- Backups manuales antes de cambios grandes (`cp archivo.py archivo.py.bak`).
- Rollback: `git checkout vX.Y.Z -- archivo.py`.

---

## Glosario

| Término | Definición |
|---|---|
| **DYC** | "Datos Y Café", segundo canal/estilo editorial del proyecto |
| **SRT word-level** | Formato de subtítulos con marcas de tiempo por palabra (producto de CrispASR) |
| **SRT sentence-level** | Formato de subtítulos con marcas por frase (fallback) |
| **draft_content.json** | Estructura canónica que CapCut lee para construir el proyecto |
| **draft_meta_info.json** | Metadatos del draft (nombre, fecha, ruta) |
| **extra_material_refs** | Referencias cruzadas entre segmentos y materiales en el JSON de CapCut |
| **hash_dir** | Subcarpeta en la caché de CapCut que identifica un recurso por su contenido |
| **resource_id** | Identificador único de un recurso en la nube de CapCut (fuentes, transiciones, efectos) |
| **effect_id** | ID del efecto; en transiciones debe coincidir con resource_id |
| **_MEIPASS** | Directorio temporal creado por PyInstaller al ejecutar un bundle onedir |
| **onedir** | Modo PyInstaller que genera una carpeta con estructura limpia (no un solo archivo) |
| **onefile** | Modo PyInstaller que empaqueta TODO en un solo .exe (lento al arrancar con modelos grandes) |
| **chunking** | División del audio/texto en segmentos para procesamiento incremental |
| **cue** | Marcador temporal en el SRT que indica cuándo empezar/dejar de mostrar algo |
| **ducking** | Atenuación dinámica del volumen de la música de fondo durante la voz |
| **chroma key** | Remoción de un color de fondo (negro) para superponer un overlay (CTA) |

---

## Preguntas abiertas

Los siguientes datos no tienen registro verificable en el repo y requieren confirmación del usuario:

| Ítem | Estado |
|---|---|
| Fechas exactas de v1.0.0 a v1.6.0 | Solo se conocen por el log de commits; los tags no incluyen descripciones detalladas |
| Detalles de versiones pre-v1.7.0 | Parcial — desde v1.3.0 hay suficiente info en el README anterior y mensajes de commit; antes de eso se requiere investigación manual |
| Nombre del primer commit del proyecto | `d0c349e` (2026-09-23): "Implementación de la versión base de CapCut Auto" |
| Fecha exacta de creación del repo | No registrada; primer commit: 2026-09-23 |

---

*Documento actualizado: 2026-10-22 | Versión: v3.0.0*
