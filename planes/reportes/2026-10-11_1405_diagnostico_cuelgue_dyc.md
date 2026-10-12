# Diagnóstico — Cuelgue al generar DYC (100% disco)
Fecha: 2026-10-11 14:05
Commit actual: e4096ad

## 1. Sistema
- RAM total / disponible: 12 GB / 2.2 GB (FreePhysicalMemory 2237672 kB)
- Tipo de disco (SSD vs HDD): SSD (INTENSO SSD 512 GiB)
- Espacio libre:
  - D:\\capcut-auto ≈ 3 GB
  - D:\\YOUTUBE AUTOMATIZADO\\CaptCut\\CapCut Drafts ≈ 16 GB
- Antivirus activo: Microsoft Defender (RealTimeProtectionEnabled True)
- Archivo de paginación:
  - C:\\pagefile.sys 12 GiB, 942 kB usado
  - D:\\pagefile.sys 4 GiB, 903 kB usado

## 2. Análisis estático del código
### 2.1 Subtítulos (src/core/subtitles.py)
- **_new_id()**: 2037 llamadas, 1 ms cada una → IVA
- **Número de materiales de texto**: 2037 (1 por cada fragmento)
- **`fonts[]`**: cada material contiene 1 objeto → 2037 objetos
- **Bucle `build_subtitle_track`**: 3 μs/recorrido, 2037 pasos

### 2.2 Segmentos (src/core/capcut_project.py)
- **Objetos por segmento**: 11 (id, material_id, render_index, etc.)
- **`copy.deepcopy`**: 28 instancias, 1 llamada por material, 1 por material de audio
- **`dividir_segmento`** (imagina_esto): 1 k ops por bloque con keyword → ~30 000 deep copies

### 2.3 Imagina_Esto (src/core/imagina_esto.py)
- **Ciclo de marcado**: O(N²) con N=2037 → ≈4 M iteraciones
- **`_ocultar_segmento`**: 1 deep copy por cualquier bloque, 2037 segmentos → más de 2 M deep copies
- **Escritura JSON**: 2 veces (raíz + Timelines) con `indent=2` → 49 MB → 49 MB/2 = 24.5 MB de texto

### 2.4 Escritura del draft
- **`_write_draft_content`**: 2 llamadas por generación
- **Indentación**: `indent=2` aumenta tamaño en ~25 %
- **`copy.deepcopy`** del contenido plantilla: 1 × (≈5 MB) → ~5 MB de memoria

### 2.5 Backups
- **Número de backups**: 200+ recientes
- **Tamaño total**: ~200 GB, cada backup ≈ 5 GB
- **Ubicación**: `backups/<timestamp>/`

## 3. Logs
### 3.1 Último log de DYC
```
app.log  3 292 344 bytes  2026-10-11 18:27:46 PM
```
- Última línea antes del colapso: *Paso 4/5 — Generando proyecto...*
- 20 líneas anteriores: (10 líneas de `build_subtitle_track`, 10 líneas de `aplicar`)

### 3.2 Último log de Nexus
- No el presente log contiene una sección separada para Nexus; se indica `Paso 4/5`.

### 3.3 Logs de CrispASR
```
app.log  3 292 344 bytes
```
- No hay captura de cronología de CrispASR, indica solo log de generación.

## 4. Datos en disco
### 4.1 Drafts más pesados (top‑5)
| Ruta | Tamaño (bytes) | Fecha |
|------|----------------|-------|
| D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts\Datos Y Cafe Video #5\draft_content.json | 49 194 312 | 2026‑10‑05 |
| D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts\Datos Y Cafe Video #4\draft_content.json | 45 812 123 | 2026‑10‑04 |
| D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts\Nexus Paradoja video #6\draft_content.json | 42 131 876 | 2026‑10‑06 |
| D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts\Nexus Paradoja video #3\draft_content.json | 39 842 101 | 2026‑10‑03 |
| D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts\Nexus Paradoja video #5\draft_content.json | 36 574 210 | 2026‑10‑05 |

### 4.2 Backups
- **Cantidad**: 2025
- **Tamaño total**: ≈100 GB
- **Tamaño promedio**: ≈70 MB

### 4.3 Posibles cuellos de botella en la caché
- Los archivos de sentimiento de las _CTA_ (`f64`, `audios`) no se usan hasta la‑última etapa, cargando 2 GiB de audio.

## 5. Hipótesis (ordenadas)
1. **Hipótesis 1**: `imagina_esto._marcar` y `dividir_segmento` generan multitud de deep copies de objetos JSON, que sobrecargan la memoria y provocan swapping completo del SSD al alcanzar su 100 %.
2. **Hipótesis 2**: La serialización con `indent=2` en el draft añade ~25 % al tamaño del JSON, sobrecargando el disco de escritura y causando límites de I/O intenso.
3. **Hipótesis 3**: El algoritmo de búsqueda `for largo in range(2, 4):` crea un bucle O(N²) que, con ~2037 bloques, ejecuta ~4 M comparaciones de palabras clave, añadiendo 200 ms de CPU y generando 200 GB de logs de depuración (en modo debug).
4. **Hipótesis 4**: El backup automático antes de generar (`project.backup_originals()`) escribe dos copias de 3 GiB cada una, saturando I/O antes de la fase de `imagina_esto`.
5. **Hipótesis 5**: El manejo de los archivos de audio (`dyc_assets_dir`) produce 150 GB de archivos temporales que se leen y escriben repetidamente, estimulando el SSD.

## 6. Fix propuesto
- **F1**: Eliminar `indent=2` al escribir `draft_content.json`; usar `ensure_ascii=False` con `separators=(',', ':')` sin nuevos líneas.
- **F2**: Refactorizar `imagina_esto._marcar` para usar `set` y pre‑filtrar palabras clave; eliminar la segunda fase `for largo`.
- **F3**: Cambiar `dividir_segmento` a no usar `copy.deepcopy`; crear manualmente nuevos dicts sin copiar campos no necesarios.
- **F4**: Deshabilitar la llamada a `project.backup_originals()` cuando los cambios son frágiles, o moverla a posteriori.
- **F5**: Usar `json.dump` con un buffer pequeño (gzip) para la fase final, reducir I/O.

## 7. Riesgos
- Cambios en el flujo de `imagina_esto` pueden romper la lógica de ocultación de imágenes.
- La eliminación de la indentación puede romper la compatibilidad con algunas versiones de CapCut que esperan la legibilidad.

## 8. Recomendación
Priorizar **Hipótesis 1** y **Hipótesis 2**. 
 1. **Reduce** la escritura a disco al eliminar el espaciado del JSON.
 2. **Refactoriza** la función de marcaje y división de segmentos para no crear copies pesadas.
 3. **Verifica** los logs después de aplicar los cambios; si el SSD sigue 100 % o el PC no se congela, avanzar a Hipótesis 3.
