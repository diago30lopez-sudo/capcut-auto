# Escalas JSON ↔ CapCut UI (oficial)

Mapa de conversión entre el `draft_content.json` generado y los valores que
muestra el panel de CapCut (propiedades de texto). Confirmadas **empíricamente**
contra el draft real del usuario (`#1 Nexus Paradoja`) y mediciones directas en
CapCut en **v1.5.1** (documenta el bug de la v1.4.0: escalas de posición
duplicadas y trazo/opacidad mal escalados). Son la fuente de verdad del
proyecto: las constantes viven en `src/core/config.py` (pares `*_UI` y
`*_JSON`).

## Tabla de escalas (CONFIRMADAS empiricamente, v1.5.1)

| Propiedad CapCut UI      | Campo en `draft_content.json`        | Fórmula (UI → JSON)    |
|--------------------------|--------------------------------------|------------------------|
| Grosor trazo             | `strokes[0].width` (y `border_width`)| UI / 500               |
| Opacidad (%)             | `global_alpha` (material)            | UI / 100               |
| Letter spacing           | `letter_spacing`                     | UI × 0.05              |
| Posición X               | `transform.x`                        | UI_X / 1920            |
| Posición Y               | `transform.y`                        | UI_Y / 1080            |

> **Cambio crítico (v1.4.0):** CapCut multiplica `transform.*` por el canvas
> **COMPLETO** (1920×1080), NO por su mitad (960×540). El valor de la v1.3.0
> `JSON = UI/960` se mostró DUPLICADO en CapCut (UI X=-1098 → mostraba -2196).
>
> **Opacidad (v1.5.0):** CapCut usa `global_alpha` (material) como control principal,
> NO `text_alpha`. Draft real: `global_alpha=0.1005` → ~10%. El builder
> escribe `global_alpha = UI/100` (15% → 0.15), `text_alpha = 1.0` fijo,
> y `styles[].fill.alpha = 1.0`. Fórmula: UI% = global_alpha × 100.
>
> **Trazo:** `border_width/strokes.width` usa escala **UI/500** (0.30 de la
> v1.3.0 se mostraba como **150**). Para UI 30 → JSON `0.06`.

## Canvas del proyecto

El proyecto del usuario es **horizontal 1920×1080**.

```
CANVAS_WIDTH  = 1920
CANVAS_HEIGHT = 1080
```

## Valores calculados para este proyecto

| Propiedad            | UI deseada | Valor JSON                          |
|----------------------|------------|-------------------------------------|
| Grosor trazo subtítulos | 30        | `0.06`   (= 30 / 500)               |
| Opacidad watermark   | 15%        | `0.15`   (= 15 / 100, `global_alpha`)     |
| Letter spacing watermark | 2       | `0.10`   (= 2 × 0.05)               |
| Watermark posición X | -1098      | `-0.571875` (= -1098 / 1920)        |
| Watermark posición Y | 896        | `0.8296` (= 896 / 1080, ≈0.8296)     |
| Subtítulos posición Y| -650       | `-0.6018519` (= -650 / 1080)        |

> Convenio de signo de Y verificado: **positivo = arriba**, **negativo = abajo**
> del centro del lienzo. X negativo = izquierda (watermark al extremo
> superior-izquierdo, subtítulos centrados abajo en X=0).

## Ejemplos de materiales de texto

### Subtítulo (fragmento con los valores calibrados)

```json
{
  "material": {
    "border_width": 0.06,
    "border_mode": 1,
    "border_color": "#000000",
    "letter_spacing": 0.05
  },
  "content.styles[0].strokes[0]": {
    "content": { "render_type": "solid", "solid": { "color": [0.0, 0.0, 0.0] } },
    "width": 0.06,
    "mode": 0,
    "enable": true
  },
  "clip.transform": { "x": 0.0, "y": -0.6018519 }
}
```

- `strokes[0].width = 0.06` → UI **30** (trazo activado con `enable: true`).
- `letter_spacing = 0.05` → UI **1** (espaciado de subtítulos).
- `transform.y = -0.6018519` → UI **Y = -650** (constante, todos los subtítulos
  a la misma altura).
- Entre palabras del `content.text` hay SIEMPRE exactamente 1 espacio ASCII
  (`U+0020`). Prohibidos `\u2003`, `\u00A0`, `\t`, `\n` y múltiples espacios
  (producen huecos enormes en CapCut).

### Watermark "NEXUS PARADOJA"

```json
{
  "content": {
    "text": "NEXUS PARADOJA",
    "styles": [ { "size": 8.0, "bold": true, "italic": true,
                  "fill": { "content": { "solid": { "color": [1.0, 1.0, 1.0] } },
                            "alpha": 1.0 },
                  "range": [0, 14] } ]
  },
  "material": { "global_alpha": 0.15, "text_alpha": 1.0, "letter_spacing": 0.10, "font_size": 8.0 },
  "clip.transform": { "x": -0.571875, "y": 0.8296 },
  "target_timerange": { "start": 0, "duration": 1234567 }
}
```

- `transform.x = -0.571875` → UI **X = -1098** (izquierda).
- `transform.y = 0.8296` → UI **Y = 896** (arriba).
- `global_alpha = 0.15`, `text_alpha = 1.0`, `fill.alpha = 1.0` → opacidad **15%**.
- `letter_spacing = 0.10` → espaciado **2**.
- `size = 8.0`, `bold` + `italic`; misma fuente (`font.path`) que los subtítulos.
- `target_timerange.start = 0`, `duration = duración del audio` → cubre todo el
  video en su **propia pista text**.

## Cómo recalibrar si CapCut cambia de versión

Si al abrir el proyecto en CapCut algún valor **no** coincide con la columna
"UI deseada":

1. Ajusta únicamente las constantes `*_JSON` (o `*_UI`) de `src/core/config.py`
   (`SUBTITLE_POS_Y_JSON`, `SUBTITLE_STROKE_WIDTH_JSON`,
   `WATERMARK_POS_X_JSON`, `WATERMARK_POS_Y_JSON`,
   `WATERMARK_ALPHA_JSON`, `WATERMARK_LETTER_SPACING_JSON`).
2. Regenera un proyecto y comprueba en el panel de CapCut.
3. La escala es **lineal sobre el lienzo completo**: si UI muestra el doble del
   valor esperado (p. ej. X=-2196 en lugar de -1098) es porque el JSON está
   calibrado a la mitad del lienzo y debe dividirse por 2 (o al revés). Ajusta
   el JSON proporcionalmente hasta que coincida.
4. Actualiza esta tabla, el README y `tests/json_scales_check.py`, y documenta
   la corrección en el historial de versiones.

> Regla del repo: **NO se crean tags** si el bug no quedó verificado. La
> verificación empírica (abrir el proyecto en CapCut y comparar valores) es el
> paso final obligatorio antes de versionar como resuelto.