# Diagnóstico — Transiciones DYC no visibles en preview
Fecha: 2026-10-11 15:00
Commit actual: d458e0c

## 1. Código relevante

### 1.1. Bloque que construye transiciones de DYC
Archivo: `src/core/capcut_project.py` líneas 1502-1520 (bloque `elif hasattr(edit_profile, 'dyc_start_animations') and edit_profile.dyc_start_animations:`):
```python
mat = {
    "id": new_id(),
    "type": "transition",
    "name": name,
    "effect_id": effect_id,
    "resource_id": effect_id,
    "third_resource_id": "0",
    "source_platform": 1,
    "path": (cache / effect_id).as_posix(),  # ← PROBLEMA: falta hash_dir
    "duration": duration_us,
    "is_overlap": is_overlap,
    "platform": "all",
    "category_id": "123456",
    "category_name": "Transiciones",
    "request_id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
    "is_ai_transition": False,
    "video_path": "",
    "task_id": "",
}
```

### 1.2. Bloque que construye transiciones de Nexus
Archivo: `src/core/capcut_project.py` líneas 897-926 (función `_build_transition_material`):
```python
def _build_transition_material(self, entry: tuple) -> dict:
    effect_id, name, hash_dir, duration_us, is_overlap, third_id = entry
    cache = Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache" / "effect"
    return {
        "id": new_id(),
        "type": "transition",
        "name": name,
        "effect_id": effect_id,
        "resource_id": effect_id,
        "third_resource_id": third_id,
        "source_platform": 1,
        "path": (cache / effect_id / hash_dir).as_posix(),  # ← CORRECTO: incluye hash_dir
        "duration": duration_us,
        "is_overlap": is_overlap,
        "platform": "all",
        "category_id": "123456",
        "category_name": "Transiciones",
        "request_id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "is_ai_transition": False,
        "video_path": "",
        "task_id": "",
    }
```

### 1.3. Definición de las constantes

**TRANSITIONS (Nexus)** - Archivo: `src/core/capcut_project.py` líneas 110-143:
```python
TRANSITIONS = (
    ("7620344224734629138", "Estiramiento a la izquierda",
     "11a4f53df0e49e1ce7a5736a7ccac0c2", 1333333, True, "0"),
    ("6724227330190873100", "Abajo",
     "a61ca47476e8bdcde0a2cfc229b264cd", 466666, False, "6724227330190873100"),
    # ... más entradas con 6 campos: (effect_id, name, hash_dir, duration_us, is_overlap, third_id)
)
```

**_DYC_TRANSITIONS (DYC)** - Archivo: `src/core/capcut_project.py` líneas 152-179:
```python
_DYC_TRANSITIONS = (
    ("7563293278083403013", "Parpadeo espeluznante",           2000000, True),
    ("7549111468348673341", "Parpadeo invertido",              2000000, True),
    # ... más entradas con 4 campos: (effect_id, name, duration_us, is_overlap)
    # FALTA: hash_dir y third_id
)
```

## 2. Tabla comparativa

| Aspecto | Nexus (TRANSITIONS) | DYC (_DYC_TRANSITIONS) |
|---------|---------------------|------------------------|
| Nº campos de la tupla | 6 | 4 |
| Campos de la tupla | effect_id, name, hash_dir, duration_us, is_overlap, third_id | effect_id, name, duration_us, is_overlap |
| Path del material (en draft) | `cache/effect/<effect_id>/<hash_dir>` | `cache/effect/<effect_id>` |
| resource_id | effect_id | effect_id |
| third_resource_id | third_id (variable) | "0" (hardcodeado) |
| is_overlap | variable (según entrada) | siempre True (según constante) |
| source_platform | 1 (hardcodeado) | 1 (hardcodeado) |
| category_id / category_name | "123456" / "Transiciones" | "123456" / "Transiciones" |

## 3. Caché de CapCut

Verificado en: `C:\Users\diago_dev\AppData\Local\CapCut\User Data\Cache\effect`

### IDs de _DYC_TRANSITIONS probados:
1. **7563293278083403013** → subdirectorio: `6022207b553e453ee29e1198230a88d2`  
   Contiene: `AmazingFeature/`, `config.json`, `extra.json`, `sticker.info`, `6022207b553e453ee29e1198230a88d2_tmp`

2. **7569892679333530898** → subdirectorio: `1c8bd85d14d78e30b501dcb7e086d521`  
   Contiene: `AmazingFeature/`, `config.json`, `extra.json`, `sticker.info`, `1c8bd85d14d78e30b501dcb7e086d521_tmp`

3. **7656729516693310741** → subdirectorio: `9672a4902b0cd82c286b6e3fbee5ac3d`  
   Contiene: `AmazingFeature/`, `config.json`, `extra.json`, `sticker.info`, `9672a4902b0cd82c286b6e3fbee5ac3d_tmp`

### IDs de TRANSITIONS probados:
1. **7620344224734629138** → subdirectorio: `11a4f53df0e49e1ce7a5736a7ccac0c2`  
   Contiene: `AmazingFeature/`, `config.json`, `extra.json`, `sticker.info`, `11a4f53df0e49e1ce7a5736a7ccac0c2_tmp`

2. **6724227330190873100** → subdirectorio: `a61ca47476e8bdcde0a2cfc229b264cd`  
   Contiene: `AmazingFeature/`, `config.json`, `extra.json`, `sticker.info`, `a61ca47476e8bdcde0a2cfc229b264cd_tmp`

3. **6724846004274729480** → subdirectorio: `986161b2af25f7aa752278aa8b39c7b7`  
   Contiene: `AmazingFeature/`, `config.json`, `extra.json`, `sticker.info`, `986161b2af25f7aa752278aa8b39c7b7_tmp`

**Conclusión**: La estructura de caché es IDÉNTICA para ambos tipos de transiciones. Cada efecto se almacena en `cache/effect/<effect_id>/<hash_dir>/` con los mismos archivos internos.

## 4. Comparación de drafts generados

### DYC (Datos Y Cafe video #6)
Primer material de transición:
```json
{
  "name": "Cortes de señal",
  "effect_id": "7651580719034125589",
  "resource_id": "7651580719034125589",
  "path": "C:/Users/diago_dev/AppData/Local/CapCut/User Data/Cache/effect/7651580719034125589",
  "duration": 1000000,
  "is_overlap": true,
  "third_resource_id": "0",
  "video_path": "",
  "source_platform": 1,
  "category_id": "123456",
  "category_name": "Transiciones",
  "is_ai_transition": false,
  "task_id": "",
  "platform": "all"
}
```

### Nexus (Nexus Paradoja video 08090978)
Primer material de transición:
```json
{
  "name": "Cross Dissolve (Dissolve)",
  "effect_id": "6724846004274729480",
  "resource_id": "6724846004274729480",
  "path": "C:/Users/diago_dev/AppData/Local/CapCut/User Data/Cache/effect/6724846004274729480/986161b2af25f7aa752278aa8b39c7b7",
  "duration": 466666,
  "is_overlap": false,
  "third_resource_id": "0",
  "video_path": "",
  "source_platform": 1,
  "category_id": "123456",
  "category_name": "Transiciones",
  "is_ai_transition": false,
  "task_id": "",
  "platform": "all"
}
```

### Análisis de `extra_material_refs`:
- **DYC**: 18 refs en segmento de video, primera referencia: `43657541`
- **Nexus**: 13 refs en segmento de video, primera referencia: `E699B042`

## 5. Hipótesis

### 5.1. ¿Por qué Nexus sí renderiza en preview y DYC no?
La diferencia crítica está en el campo `path` del material de transición:
- **Nexus**: `"path": "cache/effect/<effect_id>/<hash_dir>/"` (apunta al subdirectorio correcto donde están los archivos del efecto)
- **DYC**: `"path": "cache/effect/<effect_id>/"` (apunta al directorio padre, que solo contiene subdirectorios, no los archivos del efecto real)

CapCut busca los archivos del efecto (como `config.json`, `extra.json`, `sticker.info`, y el directorio `AmazingFeature/`) en la ruta especificada por `path`. En el caso de DYC, esa ruta no contiene esos archivos directamente, sino que los contiene dentro de un subdirectorio hash. Por lo tanto, CapCut no puede cargar el efecto y la transición no se visualiza en preview (aunque sí aparece en la línea de tiempo porque el segmento existe con la duración correcta).

### 5.2. ¿Cuál es el fix MÍNIMO que igualaría DYC a Nexus SIN tocar Nexus?
Modificar el bloque de construcción de transiciones DYC en `src/core/capcut_project.py` línea 1510 para que calcule dinámicamente el `hash_dir` listando el contenido del directorio de caché:

```python
# Línea actual:
"path": (cache / effect_id).as_posix(),

# Fix propuesto:
hash_dir = next((d.name for d in (cache / effect_id).iterdir() 
                if d.is_dir() and not d.name.endswith('_tmp')), "")
"path": (cache / effect_id / hash_dir).as_posix() if hash_dir else (cache / effect_id).as_posix(),
```

### 5.3. ¿Hay algún riesgo de romper las transiciones actuales de Nexus si se aplica el fix?
**NO**. El fix solo afecta al bloque DYC (líneas 1502-1520 dentro del `elif hasattr(edit_profile, 'dyc_start_animations') and edit_profile.dyc_start_animations:`). El Nexus usa una ruta completamente diferente (la función `_build_transition_material` en líneas 897-926) que permanece sin cambios. Además, el fix incluye un fallback a la ruta original si no se encuentra un subdirectorio hash válido.

## 6. Fix propuesto (sin aplicarlo)

En `src/core/capcut_project.py`, línea 1510, reemplazar:
```python
"path": (cache / effect_id).as_posix(),
```
por:
```python
# Encuentra el subdirectorio hash (excluyendo los *_tmp)
hash_candidates = [d.name for d in (cache / effect_id).iterdir() 
                   if d.is_dir() and not d.name.endswith('_tmp')]
hash_dir = hash_candidates[0] if hash_candidates else ""
"path": (cache / effect_id / hash_dir).as_posix() if hash_dir else (cache / effect_id).as_posix(),
```

## 7. Riesgos
- **Riesgo bajo**: Solo afecta a la lógica DYC. Si no se encuentra un subdirectorio hash, cae a la ruta original (manteniendo comportamiento actual, aunque incorrecto).
- **Posible edge case**: Si el directorio de caché tiene múltiples subdirectories no-_tmp, se toma el primero. En la práctica, cada efecto tiene exactamente un subdirectorio hash (además del *_tmp), así que esto es seguro.
- **No afecta a Nexus, transcriber.py, scene_parser.py, sync o chunking** (conformidad con guardrails).

Diagnóstico completado.
Archivo: planes/reportes/2026-10-11_1500_diagnostico_transiciones_dyc.md
¿Confirmas que aplique el fix?
Esperando confirmación.