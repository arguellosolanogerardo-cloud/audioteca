# Formato de un libro

Es la interfaz entre las piezas: el extractor y el traductor escriben el texto, el narrador escribe el audio
y la app solo lee. Si respetas este formato puedes generar libros con tus propias herramientas.

```
biblioteca/<slug>/
  libro.json          ficha del libro (abajo)
  texto/NN.md         capítulo NN (dos dígitos, desde 01): «# Título», luego párrafos separados por línea en blanco.
                      Sin números de página, cabeceras repetidas, pies de imprenta ni publicidad.
  audio/<voz>/NN.mp3  narración del capítulo en esa voz (mono, 80 kbps)
  audio/<voz>/NN.json {"duracion_s": 812.4, "voz": "<voz>",
                       "segmentos": [{"i": 0, "texto": "…", "inicio": 0.30, "fin": 4.21}, …]}
                      un segmento por oración (o varias cortas juntas); tiempos en segundos sobre ESE mp3.
                      Sirve para resaltar la oración que suena y para cambiar de voz sin perder el lugar.
  glosario.md         (opcional, libros traducidos) término original → decisión en español
  calidad-traduccion.md  (libros traducidos) reporte del control de calidad
  portada.jpg         (opcional) si no hay, la app dibuja una
```

`libro.json`:

```json
{
  "slug": "mi-libro",
  "titulo": "Título en español",
  "autor": "Autor",
  "idioma_original": "en",
  "traducido": true,
  "voz": "qwen-clon",
  "estado": "texto-listo",
  "portada": "portada.jpg",
  "glosario": "glosario.md",
  "capitulos": [
    {"n": 1, "titulo": "Capítulo 1", "archivo_texto": "texto/01.md", "archivo_audio": "audio/qwen-clon/01.mp3", "duracion_s": 812.4}
  ]
}
```

- `estado`: `texto-listo` (el narrador lo toma) → `narrando` → `completo` (todos los capítulos en la voz
  principal). `revision-traduccion` = el control de calidad pidió revisarlo; el narrador no lo toca hasta que
  lo apruebes con `./audioteca traducir … --forzar-listo`.
- `voz`: voz principal del libro. `archivo_audio`/`duracion_s` y `completo` se refieren a esa voz.
- **Varias voces**: un libro puede tener una carpeta por voz (`audio/macos/`, `audio/qwen-clon/`,
  `audio/mi-voz-clon/`). Todas narran el mismo `texto/NN.md`, así que la app cambia de voz en la misma oración.
  Desde la ficha del libro puedes pedir otra voz: la app escribe `.trabajo/narrador/pedidos.json` y el
  narrador hace primero el capítulo 1 como muestra.
- Las escrituras son atómicas (archivo temporal → rename) y `libro.json` se edita con candado (`.libro.lock`),
  así la app nunca lee un archivo a medias.

## Voces

| id | motor | de dónde sale |
|---|---|---|
| `macos` | `say` del sistema | siempre disponible (AUDIOTECA_VOZ_MACOS elige cuál) |
| `<nombre>-clon` | Qwen3-TTS 0.6B Base (MLX) | `voces/<nombre>.wav` + `voces/<nombre>.txt` |

## Cola del narrador (`.trabajo/narrador/cola.json`, opcional)

```json
{
  "orden": ["libro-urgente", {"slug": "otro-libro", "voces": ["qwen-clon", "mi-voz-clon"]}],
  "excluidos": ["libro-que-no-quiero-narrar"],
  "pausas": [{"desde": "2026-11-02T09:00", "hasta": "2026-11-02T18:00", "por": "necesito el Mac libre"}]
}
```

Sin `cola.json` narra todos los libros listos, del más antiguo al más nuevo. Se relee en cada vuelta: editarlo
no requiere reiniciar nada.

## Glosario (`glosario.md`)

Dos formatos, mezclables:

```markdown
- **growth mindset** → «mentalidad de crecimiento» (*growth mindset*); **deep work** → «trabajo profundo»

| Término | Decisión | Nota |
|---|---|---|
| deliberate practice | práctica deliberada (*deliberate practice*) | concepto central |
```

Si la decisión lleva `(*original*)`, la primera vez que aparece en el libro se escribe «decisión (*original*)».
El traductor verifica que cada decisión esté en la traducción (acepta plural y género) y reporta lo que falte.
