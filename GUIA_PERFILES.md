# GUIA_PERFILES.md — Manual técnico para crear perfiles JSON en CapCut Auto v3.0.0

Este documento describe TODOS los campos soportados por `profiles/*.json`. Cualquier IA (ChatGPT, Claude, Gemini, etc.) puede usarlo para generar un perfil completo sin leer el código Python.

---

## Principio rector

**Nada está hardcodeado en Python.** Todo comportamiento visual se controla desde el JSON del perfil. El código Python es un motor ciego que lee campos del `EditProfile` y los aplica. Para cambiar un aspecto visual, modifica el JSON — nunca el código Python.

---

## Estructura base

```json
{
  "schema_version": "3.0.0",
  "meta": { ... },
  "project_name_suffix": "...",
  "watermark": { ... },
  "subtitulos": { ... },
  "zoom": { ... },
  "transiciones": { ... },
  "animaciones": { ... },
  "color_grading": { ... },
  "hsl": { ... },
  "paneos": { ... },
  "shake": { ... },
  "fade_in": { ... },
  "imagina_esto": { ... },
  "glow": { ... },
  "overlays": { ... },
  "audio": { ... },
  "pipeline": { ... },
  "cta": { ... },
  "assets": { ... },
  "chroma": { ... },
  "dyc": { ... },
  "transition_rules": { ... },
  "extra_assets": [ ... ],
  "layout_rules": { ... }
}
```

---

## Bloque `meta`

Obligatorio. Define la identidad del perfil.

```json
"meta": {
  "id": "mi_canal",               // Identificador único (snake_case)
  "name": "Mi Canal",             // Nombre legible
  "requires_assets": false,       // true si necesita carpeta de assets
  "requires_srt": false,          // true si requiere subtítulos SRT
  "default_project_name": "Mi video"
}
```

---

## Bloque `watermark`

Marca de agua permanente sobre todo el video.

```json
"watermark": {
  "enabled": true,
  "text": "MI CANAL",
  "font_size": 8.0,
  "font_path": "",                         // Ruta local a .ttf (opcional)
  "font_resource_id": "",                  // ID de fuente CapCut cloud (prioriza sobre font_path)
  "opacity": 0.15,                         // global_alpha: 0.0 = invisible, 1.0 = completo
  "position_x": -0.571875,                 // Coordenada JSON = UI_x / 1920
  "position_y": 0.8296296,                 // Coordenada JSON = UI_y / 1080
  "letter_spacing": 0.10,                  // JSON = UI * 0.05 (UI 2 = 0.10)
  "bold": true,
  "italic": false,
  "font_name": "Impact"
}
```

**Notas:**
- `position_x/y`: positivo = arriba/derecha, negativo = abajo/izquierda (en unidades del canvas completo).
- `opacity`: 0.10 → 10% visibilidad.

---

## Bloque `subtitulos`

Generación de subtítulos sobre el video.

```json
"subtitulos": {
  "enabled": true,
  "font_path": "",
  "font_resource_id": "7533527101870214401",
  "font_size": 12.0,
  "keyword_color": [1.0, 0.8431373, 0.0],   // RGB [0-1] para palabras clave
  "stroke_width": 0.06,                      // JSON = UI / 500 (UI 30 = 0.06)
  "position_y": -0.8333333,                  // JSON = UI_Y / 1080 (UI -900 = -0.833)
  "keywords": ["ataque","golpe","peligro"],  // Palabras que se resaltan en keyword_color
  "popup": true,                             // Efecto pop-in en cada subtítulo
  "uppercase": true,                         // Convierte todo a mayúsculas
  "max_words_per_line": 5,
  "font_name": "Impact"
}
```

---

## Bloque `zoom`

Animación de zoom lento sobre cada imagen (Ken Burns-style scale).

```json
"zoom": {
  "initial": 1.0,     // Escala base (siempre 1.0)
  "final_min": 1.10,  // Zoom mínimo al final de cada imagen
  "final_max": 1.15,  // Zoom máximo al final de cada imagen
  "mode": "random"    // "random" = valor aleatorio entre final_min y final_max
}
```

**Nota:** Si `cover_scale > 1.2` (imagen muy diferente del lienzo), el zoom se desactiva automáticamente para evitar deformaciones.

---

## Bloque `transiciones`

Pool de nombres de transiciones (cuando no se usa `transition_rules`).

```json
"transiciones": {
  "pool": ["Abajo", "Fade to Black"],  // Nombres a elegir aleatoriamente
  "ratio": 0.98,                       // Porcentaje de bordes con transición
  "min_duration_us": 100000,
  "frame_grid": 33333
}
```

---

## Bloque `transition_rules` — v3.0.0 (NUEVO)

Motor de reglas para decidir DÓNDE se colocan las transiciones. **Reemplaza el comportamiento anterior basado en `ratio` fijo.**

### Tipos soportados

#### `random` (por defecto)
```json
"transition_rules": {
  "type": "random",
  "ratio": 0.98
}
```
Elige aleatoriamente qué bordes reciben transición (98% de los bordes). Comportamiento heredado de v2.x.

#### `every_n`
```json
"transition_rules": {
  "type": "every_n",
  "n": 3
}
```
Coloca transición en cada **n**-ésimo corte. Con `n=3`: transición en los cortes 3, 6, 9, 12, …

#### `specific_cuts`
```json
"transition_rules": {
  "type": "specific_cuts",
  "indices": [1, 5, 10]
}
```
Coloca transición SOLO en los bordes indicados (índices 0-based: borde 1 = entre segmento 1 y 2).

#### `keyword`
```json
"transition_rules": {
  "type": "keyword",
  "keywords": ["peligro", "muerte", "explosión"]
}
```
Coloca transición en el borde posterior a cada escena que contenga cualquiera de las keywords (búsqueda case-insensitive en el texto de la escena siguiente).

---

## Bloque `layout_rules` — v3.0.0 (NUEVO)

Controla la duración base de cada imagen antes de la redistribución.

```json
"layout_rules": {
  "mode": "audio_sync",
  "min_duration_us": 33333
}
```

### Campos

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `mode` | string | `"audio_sync"` | Modo de layout (ver abajo) |
| `min_duration_us` | int | `33333` | Duración mínima por escena en microsegundos. Por defecto es 1 frame (~30 fps). Valores mayores estiran escenas cortas; usar `33333` para sincronización perfecta. |

### Modos

#### `audio_sync` (por defecto)
La duración de cada imagen viene del SRT (cuanto dura cada frase de voz). Sin modificación.

#### `fixed_gap`
Añade un gap fijo a cada imagen: `duracion = frase + gap_seconds`.

```json
"layout_rules": {
  "mode": "fixed_gap",
  "gap_seconds": 2.0
}
```

#### `fixed_duration`
Fija una duración idéntica para todas las imágenes.

```json
"layout_rules": {
  "mode": "fixed_duration",
  "duration_seconds": 3.0
}
```

---

## Bloque `extra_assets` — v3.0.0 (NUEVO)

Inyección universal de audios/videos/imágenes adicionales. Cada entrada define un asset, su tipo, cuándo/placear, y parámetros.

```json
"extra_assets": [
  {
    "file": "mi_audio.mp3",
    "type": "audio",
    "trigger": "start",
    "time_us": 0,
    "duration_us": 0,
    "volume_db": 0.0,
    "chroma_enabled": false,
    "chroma_color": "#000000"
  }
]
```

### Campos

| Campo | Obligatorio | Descripción |
|---|---|---|
| `file` | ✅ | Nombre exacto del archivo (se busca en `assets.folder`) |
| `type` | ✅ | `"audio"` \| `"video"` \| `"image"` |
| `trigger` | ✅ | Cuándo colocar el asset (ver tabla abajo) |
| `time_us` | ⚠️ | Solo para trigger=`time_us`: posición en microsegundos |
| `duration_us` | ❌ | Duración deseada. Si 0, se mide del archivo |
| `volume_db` | ❌ | Ajuste de volumen en dB. 0 = sin cambio. `+10` = más fuerte |
| `chroma_enabled` | ❌ | Solo para video/imagen: aplicar chroma key |
| `chroma_color` | ❌ | Color de fondo a eliminar (hex, ej: `#000000`) |

### Triggers

| Trigger | Comportamiento |
|---|---|
| `"start"` | Colocar al inicio del video (t = 0) |
| `"end"` | Colocar al final del video (t = duración_total - asset_dur) |
| `"black_hole_start"` | Colocar donde empieza la animación de salida (agujero negro) |
| `"time_us"` | Colocar en la posición exacta indicada por `time_us` |

### Ejemplo: Intro + Outro

```json
"extra_assets": [
  {
    "file": "intro_sound.mp3",
    "type": "audio",
    "trigger": "start",
    "volume_db": 6.0
  },
  {
    "file": "outro_sound.mp3",
    "type": "audio",
    "trigger": "end",
    "volume_db": -6.0
  },
  {
    "file": "swoosh.mp3",
    "type": "audio",
    "trigger": "black_hole_start",
    "volume_db": 10.0
  }
]
```

---

## Bloque `dyc` (solo para DYC)

Específico del canal "Datos Y Café". Otros perfiles pueden omitirlo completamente.

```json
"dyc": {
  "subtitle_font": "Bungee-Rg",
  "subtitle_font_resource_id": "7533527101870214401",
  "start_animations": [ ... ],
  "end_animation": { ... },
  "color_effects": [ ... ],
  "hsl_channels": [ ... ],
  "glitch_transitions": [ ... ],
  "excluded_transition_names": ["Elige otro"],
  "chroma_intensity": 0.25
}
```

### `start_animations`

Lista de animaciones de entrada (tipo sticker_animation, `type: "in"`). Una se elige aleatoriamente al inicio del video.

```json
"start_animations": [
  {
    "resource_id": "7575810888108756277",
    "name": "TV retro",
    "duration_us": 2000000,
    "hash": "b3efebc966906cd02d0ad134ba81a47b",
    "path": "{USER_HOME}/AppData/Local/CapCut/User Data/Cache/effect/7575810888108756277/b3efebc966906cd02d0ad134ba81a47b"
  }
]
```

**Importante:** El placeholder `{USER_HOME}` se resuelve automáticamente en runtime.

### `end_animation`

Animación de salida (tipo `sticker_animation`, `type: "out"`). Se aplica a la última imagen.

```json
"end_animation": {
  "resource_id": "7294461821170225666",
  "name": "Agujero negro",
  "duration_us": 1000000,
  "hash": "18f0daae1bf0b7bb2fbdec2d4a3dbdcd",
  "path": "{USER_HOME}/AppData/Local/CapCut/User Data/Cache/effect/7294461821170225666/18f0daae1bf0b7bb2fbdec2d4a3dbdcd"
}
```

**Nota v3.0.0:** La duración se lee directamente del campo `duration_us`. Si la duración excede el último segmento, se trunca automáticamente al tamaño del segmento.

### `color_effects`

Efectos de color grading tipo "Adjust" de CapCut (valores normalizados -1.0 a 1.0).

```json
"color_effects": [
  { "type": "contrast",    "value": 0.2,    "version": "v3" },
  { "type": "saturation",  "value": 0.19,   "version": "v1" },
  { "type": "sharpen",     "value": 0.40,   "version": "v1" },
  { "type": "highlight",   "value": 0.0,    "version": "v3" },
  { "type": "shadow",      "value": -0.30,  "version": "v3" },
  { "type": "light_sensation", "value": 0.0, "version": "" },
  { "type": "vignetting",  "value": 0.30,   "version": "v1" }
]
```

### `hsl_channels`

Canales HSL selectivos (mismo mecanismo que en Nexus).

```json
"hsl_channels": [
  { "hsl_color_type": 1, "hue": 0.0, "saturation": 15.0, "lightness": 10.0, "custom_color": "#FFE64444" },
  { "hsl_color_type": 3, "hue": 0.0, "saturation": 15.0, "lightness": 10.0, "custom_color": "#FFF2F224" }
]
```

`hsl_color_type`: 1=Rojo, 2=Naranja, 3=Amarillo, 4=Verde, 5=Cian, 6=Azul, 7=Púrpura, 8=Magenta.

### `glitch_transitions`

Transiciones de glitch para el corte entre última imagen y pantalla final.

```json
"glitch_transitions": [
  ["7595248214505164037", "Error distópico", 1466666, true],
  ["6724239785205961228", "Error de color", 466666, true]
]
```
Formato: `[effect_id, nombre, duracion_us, is_overlap]`

---

## Bloque `paneos`

Paneos Ken Burns (movimiento de cámara lento sobre la imagen).

```json
"paneos": {
  "ratio": 0.6,              // Probabilidad de que una imagen tenga paneo (0.0 = ninguno, 1.0 = todas)
  "amplitude": [0.04, 0.08]  // Rango de deriva en eje X (el eje Y es la mitad)
}
```

**Valores:** Deriva de -0.08 a +0.08 en X, -0.04 a +0.04 en Y (coordenadas normalizadas del lienzo).

---

## Bloque `shake`

Camera shake (temblor) en escenas con palabras de acción.

```json
"shake": {
  "ratio": 1.0,              // Probabilidad de temblor (sobre escenas con keywords de acción)
  "amplitude": [0.010, 0.020], // Magnitud del temblor
  "zoom_boost": 1.06         // Overscan inicial para evitar destapar bordes
}
```

---

## Bloque `fade_in`

Fade in inicial de la primera imagen.

```json
"fade_in": {
  "duration_us": 200000   // 0.2 segundos
}
```

---

## Bloque `color_grading`

Color grading por imagen. Si todos los valores son `null`, se activa modo aleatorio (valores dentro de rangos predefinidos). Si se fijan valores, se usan esos.

```json
"color_grading": {
  "contrast": null,        // null = aleatorio; float = fijo (-1.0 a 1.0)
  "saturation": null,
  "sharpen": null,
  "highlight": null,
  "shadow": null,
  "light_sensation": null,
  "vignetting": 0.215,     // Fijo
  "random": true           // v3.0.0: true = valores aleatorios por imagen (usado por Nexus)
}
```

---

## Bloque `hsl`

Canales HSL genéricos (para Nexus, no DYC).

```json
"hsl": {
  "entries": [
    {"hsl_color_type": 2, "saturation": 0.15, "lightness": 0.05, "custom_color": "#FFA227"},
    {"hsl_color_type": 5, "saturation": -0.15, "lightness": -0.1, "custom_color": "#00E5FF"},
    {"hsl_color_type": 6, "saturation": -0.15, "lightness": -0.1, "custom_color": "#2D6BFF"}
  ]
}
```

---

## Bloque `imagina_esto`

Post-proceso que centra y oculta subtítulos cuando aparece una keyword especial.

```json
"imagina_esto": {
  "enabled": true,
  "keywords": ["imagina esto", "supongamos que", "cierra los ojos e imagina"]
}
```

---

## Bloque `glow`

Efecto glow en keywords de acción.

```json
"glow": {
  "enabled": false
}
```

---

## Bloque `overlays`

Overlay de cuadrícula y textos neón sobre escenas que contienen keywords.

```json
"overlays": {
  "grid_enabled": false,
  "grid_keywords": ["matrix", "código"],
  "neon_enabled": false
}
```

---

## Bloque `audio`

Configuración de audio de fondo (BGM) y ducking.

```json
"audio": {
  "gain_db": 6.0,           // Volumen de la voz (lineal = 10^(dB/20))
  "bgm_volume_db": -20.0,   // Volumen de música de fondo
  "ducking_depth_db": -8.0, // Cuánto baja el BGM cuando habla la voz
  "ducking_active": true    // true = activar ducking
}
```

---

## Bloque `cta`

Configuración de Call-To-Action (pantallas "Suscríbete").

```json
"cta": {
  "enabled": true,
  "patterns": ["suscribete", "suscribirse", "dale like"],
  "avoid_overlap_with_end": true,
  "intermedio": {
    "position_pct": 0.37
  },
  "final": {
    "fallback_ratio": 0.9,
    "patterns": ["suscribete", "suscribirse", "suscribete al canal"]
  }
}
```

### Campos CTA

| Campo | Tipo | Descripción |
|---|---|---|
| `enabled` | bool | Activa/desactiva todo el sistema CTA |
| `patterns` | string[] | Keywords que activan la detección de CTA en el SRT |
| `avoid_overlap_with_end` | bool | v3.0.0: Si true, los CTAs que colisionan con el agujero negro o pantalla final se recortan o eliminan |
| `intermedio.position_pct` | float | Posición relativa (0.0–1.0) del CTA intermedio |
| `final.fallback_ratio` | float | Posición de fallback cuando no se encuentra keyword en el SRT |

---

## Bloque `assets`

Ruta a la carpeta de assets (audios, videos, imágenes adicionales).

```json
"assets": {
  "folder": "D:/YOUTUBE AUTOMATIZADO/0.sticman/assets/",
  "files": {}
}
```

Los archivos en `extra_assets` se buscan dentro de esta carpeta.

---

## Bloque `chroma`

Configuración del chroma key para overlays (CTA, extra_assets video).

```json
"chroma": {
  "enabled": true,
  "color": "#000000",
  "intensity": 0.25,
  "shadow": 0.0,
  "edge_smooth": 0.0,
  "spill": 0.0
}
```

---

## Placeholder `_USER_HOME_`

En los campos `path` de animaciones y fuentes, puedes usar `{USER_HOME}` para referirte al home del usuario. Se resuelve automáticamente en runtime:

```json
"path": "{USER_HOME}/AppData/Local/CapCut/User Data/Cache/effect/7575810888108756277/hash"
```

También están disponibles `{REPO_ROOT}` y `{DYC_ASSETS}`.

---

## Ejemplo completo: Perfil Nexus-like

```json
{
  "schema_version": "3.0.0",
  "meta": {
    "id": "mi_canal_cine",
    "name": "Mi Canal Cinematográfico",
    "requires_assets": false,
    "requires_srt": true,
    "default_project_name": "Mi video cinematográfico"
  },
  "project_name_suffix": "Mi Video Cine #",
  "watermark": {
    "enabled": true,
    "text": "MI CANAL",
    "font_size": 8.0,
    "font_path": "C:/Windows/Fonts/impact.ttf",
    "opacity": 0.15,
    "position_x": -0.57,
    "position_y": 0.83,
    "letter_spacing": 0.10,
    "bold": true,
    "italic": true,
    "font_name": "Impact"
  },
  "subtitulos": {
    "enabled": true,
    "font_size": 12.0,
    "keyword_color": [1.0, 0.843, 0.0],
    "stroke_width": 0.06,
    "position_y": -0.833,
    "keywords": ["peligro", "muerte", "poder"],
    "popup": true,
    "uppercase": true,
    "max_words_per_line": 5
  },
  "zoom": {
    "final_min": 1.10,
    "final_max": 1.15
  },
  "transition_rules": {
    "type": "random",
    "ratio": 0.98
  },
  "layout_rules": {
    "mode": "audio_sync"
  },
  "paneos": {
    "ratio": 0.6,
    "amplitude": [0.04, 0.08]
  },
  "shake": {
    "ratio": 1.0,
    "amplitude": [0.010, 0.020],
    "zoom_boost": 1.06
  },
  "fade_in": {
    "duration_us": 0
  },
  "imagina_esto": {
    "enabled": true,
    "keywords": ["imagina esto", "supongamos que"]
  },
  "color_grading": {
    "contrast": null,
    "saturation": null,
    "vignetting": 0.215,
    "random": true
  },
  "hsl": {
    "entries": [
      {"hsl_color_type": 2, "saturation": 0.15, "lightness": 0.05, "custom_color": "#FFA227"},
      {"hsl_color_type": 6, "saturation": -0.15, "lightness": -0.1, "custom_color": "#2D6BFF"}
    ]
  },
  "audio": {
    "gain_db": 6.0,
    "bgm_volume_db": -20.0,
    "ducking_depth_db": -8.0,
    "ducking_active": false
  },
  "pipeline": {
    "chunking": {
      "chunk_seconds": 60,
      "strategy": "proportional"
    }
  },
  "cta": {
    "enabled": false
  },
  "chroma": {
    "enabled": false
  }
}
```

---

## Ejemplo completo: Perfil DYC-like

```json
{
  "schema_version": "3.0.0",
  "meta": {
    "id": "datos_y_cafe_clone",
    "name": "Datos Y Cafe Clone",
    "requires_assets": true,
    "requires_srt": true,
    "default_project_name": "DYC Clone video"
  },
  "project_name_suffix": "DYC Clone Video #",
  "watermark": {
    "enabled": true,
    "text": "DATOS Y CAFE CLONE",
    "font_size": 15.0,
    "font_resource_id": "7533526205761326353",
    "opacity": 0.1,
    "position_x": 0.0,
    "position_y": 0.0,
    "letter_spacing": 0.1,
    "bold": true,
    "italic": false,
    "font_name": "Staatliches-Rg"
  },
  "subtitulos": {
    "enabled": true,
    "font_resource_id": "7533527101870214401",
    "font_size": 10.0,
    "keyword_color": [1.0, 0.831, 0.0],
    "stroke_width": 0.06,
    "position_y": -0.787,
    "keywords": ["ataque", "golpe", "peligro"],
    "popup": true,
    "uppercase": true,
    "max_words_per_line": 5,
    "font_name": "Bungee-Rg"
  },
  "zoom": {
    "final_min": 1.0,
    "final_max": 1.1
  },
  "transition_rules": {
    "type": "every_n",
    "n": 3
  },
  "layout_rules": {
    "mode": "audio_sync"
  },
  "paneos": {
    "ratio": 0.5,
    "amplitude": [0.02, 0.04]
  },
  "shake": {
    "ratio": 0.1,
    "amplitude": [0.05, 0.1],
    "zoom_boost": 1.03
  },
  "fade_in": {
    "duration_us": 200000
  },
  "imagina_esto": {
    "enabled": false
  },
  "color_grading": {
    "contrast": null,
    "shadow": null,
    "vignetting": 0.0,
    "random": false
  },
  "audio": {
    "gain_db": 6.0,
    "bgm_volume_db": -12.0,
    "ducking_depth_db": -5.0,
    "ducking_active": true
  },
  "cta": {
    "enabled": true,
    "patterns": ["suscribete", "suscribirse", "dale like"],
    "avoid_overlap_with_end": true,
    "intermedio": { "position_pct": 0.37 },
    "final": {
      "fallback_ratio": 0.9,
      "patterns": ["suscribete", "suscribirse", "suscribete al canal"]
    }
  },
  "assets": {
    "folder": "D:/mis_assets/",
    "files": {}
  },
  "chroma": {
    "enabled": true,
    "color": "#000000",
    "intensity": 0.25
  },
  "dyc": {
    "subtitle_font": "Bungee-Rg",
    "subtitle_font_resource_id": "7533527101870214401",
    "start_animations": [
      {
        "resource_id": "7575810888108756277",
        "name": "TV retro",
        "duration_us": 2000000,
        "hash": "b3efebc966906cd02d0ad134ba81a47b",
        "path": "{USER_HOME}/AppData/Local/CapCut/User Data/Cache/effect/7575810888108756277/b3efebc966906cd02d0ad134ba81a47b"
      }
    ],
    "end_animation": {
      "resource_id": "7294461821170225666",
      "name": "Agujero negro",
      "duration_us": 1000000,
      "hash": "18f0daae1bf0b7bb2fbdec2d4a3dbdcd",
      "path": "{USER_HOME}/AppData/Local/CapCut/User Data/Cache/effect/7294461821170225666/18f0daae1bf0b7bb2fbdec2d4a3dbdcd"
    },
    "color_effects": [
      { "type": "contrast", "value": 0.2, "version": "v3" },
      { "type": "vignetting", "value": 0.30, "version": "v1" }
    ],
    "hsl_channels": [
      { "hsl_color_type": 1, "saturation": 15.0, "lightness": 10.0, "custom_color": "#FFE64444" },
      { "hsl_color_type": 3, "saturation": 15.0, "lightness": 10.0, "custom_color": "#FFF2F224" }
    ],
    "glitch_transitions": [
      ["7595248214505164037", "Error distópico", 1466666, true]
    ]
  },
  "extra_assets": [
    {
      "file": "Toast wiht a glass.MP3",
      "type": "audio",
      "trigger": "start",
      "volume_db": 10.0
    },
    {
      "file": "SWOOSH.MP3",
      "type": "audio",
      "trigger": "black_hole_start",
      "volume_db": 10.0
    }
  ]
}
```

---

## Resumen de cambios v3.0.0 respecto a v2.x

| Campo v2.x | Reemplazo v3.0.0 |
|---|---|
| `transiciones.ratio` fijo | `transition_rules.type` + `transition_rules.n`/`indices`/`keywords` |
| Ningún campo de layout | `layout_rules.mode` + `layout_rules.gap_seconds` |
| Ningún campo de assets extra | `extra_assets[]` con triggers y chroma |
| Hardcode de animación final (800ms) | `dyc.end_animation.duration_us` leído del JSON |
| Hardcode de paneos/shake/zoom defaults | Todos leídos estrictamente del JSON |
| `if is_nexus()` / `if is_dyc()` | Eliminados; solo `if profile.field:` |
