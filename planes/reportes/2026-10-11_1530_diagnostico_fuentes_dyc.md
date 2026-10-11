# Diagnóstico — Fuentes DYC no visibles en preview
Fecha: 2026-10-11 15:30
Commit actual: 611facd

## 1. Código relevante

### 1.1. Función que construye material de texto para subtítulos
Archivo: `src/core/subtitles.py` líneas 216-239 (`resolve_subtitle_font`):
- Prioriza `profile.subtitle_font_path` (línea 227) si existe.
- Luego `profile.subtitle_font_resource_id` (línea 229).
- Para DYC (línea 232-239): si es perfil DYC y tiene `dyc_start_animations`, llama a `_dyc_subtitle_font_info(p)`.
- `resolve_subtitle_font` devuelve un dict con claves: `path`, `name`, `title`, `resource_id`.

### 1.2. Función que costruye material de watermark
Archivo: `src/core/subtitles.py` líneas 720-789 (`build_watermark_material_and_track`):
- Línea 738: Si `profile.watermark_font_path` existe, usa esa ruta.
- Línea 743: Si `profile.watermark_font_resource_id` existe, usa `font_id` y deja `font_path=""`.
- Línea 749: Para DYC, llama a `_dyc_watermark_font_path()` que construye:
  `f"C:/<user>/AppData/Local/CapCut/User Data/Cache/effect/{_DYC_WATERMARK_FONT_RESOURCE_ID}/{_DYC_WATERMARK_FONT_HASH}/font.ttf"`
- Línea 750: `font_id = _DYC_WATERMARK_FONT_RESOURCE_ID` (hardcodeado: "7533526205761326353")
- Línea 751: `font_name = _DYC_WATERMARK_FONT_NAME` (hardcodeado: "Staatliches-Rg")
- Línea 788: Si `font_id` existe, llama a `_build_font_entry(font_id, font_path)` para crear la entrada `fonts[]`.

### 1.3. JSON literal que se escribe para el campo "font" dentro del material de texto

#### DYC (generado por la app - sin fuentes visibles):
Los materiales de texto DYC no se generan correctamente porque el perfil `dyc.json` tiene todos los campos de fuente en `None`. El flujo de código llega al bloque DYC (línea 232) pero como `profile.dyc_subtitle_font` y `profile.dyc_subtitle_font_resource_id` son `None`, se usa el fallback hardcodeado `_DYC_SUBTITLE_FONT_FALLBACK = "Bungee-Rg"` y `_DYC_SUBTITLE_FONT_RESOURCE_ID_FALLBACK = "7533527101870214401"`. Sin embargo, el `font_path` devuelto por `_dyc_subtitle_font_info` es `_DYC_SUBTITLE_FONT_PATH_FALLBACK = ""` (cadena vacía).

#### Nexus (que SÍ funciona):
Las fuentes Nexus vienen configuradas directamente en el perfil (`profile.subtitle_font_path`, `profile.subtitle_font_resource_id`, etc.) y se usan directamente sin necesidad de lógica DYC especial.

### 1.4. Comparativa lado a lado

| Campo                    | DYC (generado por app)                              | Nexus (generado por perfil)                          |
|--------------------------|------------------------------------------------------|------------------------------------------------------|
| `font_path`              | `""` (vacío, fallback)                               | `C:/Windows/Fonts/impact.ttf` (o ruta local)         |
| `font_name`              | `"Bungee-Rg"` (fallback) o `""`                    | `"impact"`                                           |
| `font_resource_id`       | `"7533527101870214401"` (fallback) o `""`          | `""`                                                 |
| Estructura `styles[].font` | `{"id": "", "path": ""}`                            | `{"id": "", "path": "C:/Windows/Fonts/impact.ttf"}` |

## 2. Caché de CapCut para fuentes

### 2.1. `C:\Users\diago_dev\AppData\Local\CapCut\User Data\Cache\font`
- **No existe** esta carpeta en el sistema.

### 2.2. Recursos de fuente DYC en `Cache\effect\`
Ambos resource_ids existen y tienen la estructura completa:

| resource_id | hash_dir | Contenido |
|-------------|----------|-----------|
| `7533527101870214401` (Bungee-Rg subtítulos) | `ba7ae66db1b86e6a3696c6831e3fe07e` | `config.json` (109 bytes), `font.ttf` (125116 bytes) |
| `7533526205761326353` (Staatliches-Rg watermark) | `39f15441a523e1befaac4b8b9ca709dc` | `config.json` (109 bytes), `font.ttf` (61400 bytes) |

### 2.3. Fuente local de Nexus: `C:\Windows\Fonts\impact.ttf`
- **Existe** y es la fuente por defecto que usa CapCut cuando no encuentra la de caché.

## 3. Comparación de drafts generados

### 3.1. Draft DYC generado por la app (Datos Y Cafe video #6)
- **0 text materials** encontrados en `draft_content.json`. No hay materiales de subtítulo ni watermark con tipo "text".

### 3.2. Draft Nexus generado por la app (Nexus Paradoja video 08090978)
- También presenta text materials, pero usan fuentes locales (`impact.ttf`) con ruta completa.

### 3.3. Draft nativo de CapCut (PRUEBA EDICION DATOS Y CAFE)
Este es el resultado cuando el usuario crea el draft directamente en CapCut:
- **Subtitle material**: 
  - `font_resource_id: "7548725304580214032"` (Bungee-Rg)
  - `font_path: "C:/Users/diago_dev/AppData/Local/CapCut/User Data/Cache/effect/7548725304580214032/3e754c7c961e6bfac37b8ef39034bfaa/font.ttf"` (ruta completa al archivo .ttf)
  - `style font: {"path": "C:/Users/diago_dev/AppData/Local/CapCut/User Data/Cache/effect/7548725304580214032/3e754c7c961e6bfac37b8ef39034bfaa/font.ttf", "id": "7548725304580214032"}`
  
- **Watermark material**:
  - `font_resource_id: "7533526205761326353"` (Staatliches-Rg)
  - `font_path: "C:/Users/diago_dev/AppData/Local/CapCut/User Data/Cache/effect/7533526205761326353/39f15441a523e1befaac4b8b9ca709dc/font.ttf"` (ruta completa al archivo .ttf)
  - `style font: {"path": "C:/Users/diago_dev/AppData/Local/CapCut/User Data/Cache/effect/7533526205761326353/39f15441a523e1befaac4b8b9ca709dc/font.ttf", "id": "7533526205761326353"}`

**Diferencia crítica**: En el draft nativo, el campo `path` apunta directamente al archivo `.ttf` completo (`.../font.ttf`), mientras que nuestra app apunta a la carpeta de la caché sin el nombre del archivo, o deja `path` vacío.

## 4. Hipótesis

### 4.1. ¿Por qué Nexus sí se ve en preview y DYC no?
Nexus usa fuentes locales instaladas en Windows (`impact.ttf` en `C:\Windows\Fonts\`) que CapCut encuentra automáticamente. DYC, en cambio, depende de fuentes de la caché de CapCut (`Cache\effect\<id>\<hash>\font.ttf`).

La razón principal por la que DYC no muestra la fuente en preview es que el `font_path` se construye incorrectamente:
1. En `resolve_subtitle_font()` para DYC (línea 232-239), se devuelve `font_path` desde `_dyc_subtitle_font_info(p)`, que a su vez usa `_DYC_SUBTITLE_FONT_PATH_FALLBACK = ""` (vacío).
2. En `build_watermark_material_and_track()` para DYC (línea 749-753), se usa `_dyc_watermark_font_path()` que construye `f"C:/<user>/AppData/Local/CapCut/User Data/Cache/effect/{_DYC_WATERMARK_FONT_RESOURCE_ID}/{_DYC_WATERMARK_FONT_HASH}/font.ttf"` - **esta ruta incluye el nombre del archivo `font.ttf`**, que es correcto.

Sin embargo, el problema real es que el perfil `dyc.json` no tiene los campos de fuente poblados (`subtitle_font_path`, `subtitle_font_resource_id`, `dyc_subtitle_font`, `dyc_subtitle_font_resource_id`), por lo que siempre se cae a los valores fallback con `font_path=""`.

### 4.2. Fix mínimo para igualar DYC a Nexus SIN tocar Nexus
El fix debe asegurar que el `font_path` incluya el nombre del archivo `.ttf` y que se usen los resource_ids reales de la caché.

Dos opciones:

**Opción A - Cambiar el perfil (`profiles/dyc.json`):**
Poblar los campos del perfil con los values reales:
- `subtitle_font_path: "C:/Users/diago_dev/AppData/Local/CapCut/User Data/Cache/effect/7533527101870214401/ba7ae66db1b86e6a3696c6831e3fe07e/font.ttf"`
- `subtitle_font_resource_id: "7533527101870214401"`
- `watermark_font_path: "C:/Users/diago_dev/AppData/Local/CapCut/User Data/Cache/effect/7533526205761326353/39f15441a523e1befaac4b8b9ca709dc/font.ttf"`
- `watermark_font_resource_id: "7533526205761326353"`

2. **Opción B - Modificar el código (`subtitles.py`):**
Asegurar que al construir el `font_path` para DYC siempre incluya el nombre del archivo `.ttf`. Actualmente `_dyc_subtitle_font_info` devuelve `font_path=_DYC_SUBTITLE_FONT_PATH_FALLBACK=""` - esto debe cambiarse para que construya la ruta completa al archivo `.ttf`.

**Opción C - La más mínima y recomendada:**
Modificar `_dyc_subtitle_font_info` en `src/core/subtitles.py` (línea 188) para que construya la ruta completa al archivo `.ttf` usando el resource_id y el hash conocido:

```
font_path = f"C:/{user}/AppData/Local/CapCut/User Data/Cache/effect/{font_rid}/{_DYC_SUBTITLE_FONT_HASH}/font.ttf"
```

Donde `_DYC_SUBTITLE_FONT_HASH = "ba7ae66db1b86e6a3696c6831e3fe07e"` (constante ya definida en la línea 152).

### 4.3. Riesgos de romper el aislamiento Nexus/DYC
- **Riesgo bajo**: El fix solo afecta a la lógica DYC (bloques condicionados con `_is_dyc_profile(p)`).
- Nexus usa una ruta completamente diferente (`profile.subtitle_font_path` directos) y no se ve afectado.
- Si el perfil no es DYC, el código cae a los bloques normales que ya funcionan para Nexus.

## 7. Fix propuesto (descripción, sin aplicarlo)
Modificar `_dyc_subtitle_font_info()` en `src/core/subtitles.py` (línea 171-188) para que la ruta `font_path` incluya el nombre del archivo `font.ttf`:

```python
def _dyc_subtitle_font_info(profile: EditProfile) -> tuple[str, str, str]:
    """Devuelve (name, resource_id, path) para los subtítulos DYC."""
    global _dyc_font_warned
    font_name = profile.dyc_subtitle_font or _DYC_SUBTITLE_FONT_FALLBACK
    font_rid = profile.dyc_subtitle_font_resource_id
    if not font_rid:
        font_rid = _DYC_SUBTITLE_FONT_RESOURCE_ID_FALLBACK
        if not _dyc_font_warned:
            _dyc_font_warned = True
            log.warning(
                "%s sin resource_id en el perfil; usando el fallback %s.",
                font_name, font_rid,
            )
    # CONSTRUIR ruta completa al archivo .ttf en la caché de CapCut
    user = ... # obtener username
    font_path = f"C:/{user}/AppData/Local/CapCut/User Data/Cache/effect/{font_rid}/{_DYC_SUBTITLE_FONT_HASH}/font.ttf"
    return font_name, str(font_rid), font_path
```

Donde `_DYC_SUBTITLE_FONT_HASH = "ba7ae66db1b86e6a3696c6831e3fe07e"` ya está definido en la línea 152.

También es necesario poblar el perfil `profiles/dyc.json` con los campos de fuente, o asegurar que el código lea los `dyc_subtitle_font_*` del perfil correctamente.

## 8. Riesgos
- **Riesgo bajo**: El fix solo afecta la construcción de rutas de fuentes DYC.
- Si el hash o resource_id cambian en futuras actualizaciones de CapCut, el fix dejaría de funcionar, pero el perfil se puede actualizar fácilmente.
- No hay riesgo de romper Nexus, cuya lógica es independiente.

---
Diagnóstico completado.
Archivo: planes/reportes/2026-10-11_1530_diagnostico_fuentes_dyc.md
¿Confirmas que aplique el fix?
Esperando confirmación.