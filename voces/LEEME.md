# Voces

Cada voz clonada son dos archivos aquí: `<nombre>.wav` (10-20 s de una sola persona, sin música ni ruido) y
`<nombre>.txt` (lo que se dice en la grabación, palabra por palabra). El narrador la llama `<nombre>-clon`.

- `./audioteca voz base` crea `qwen.wav` + `qwen.txt`: la voz genérica del modelo (`qwen-clon`).
- `./audioteca voz clonar mi-voz grabacion.m4a "transcripción exacta"` crea `mi-voz-clon`.

Esta carpeta no se sube a git (salvo este archivo): tus voces son tuyas. Clona solo tu voz o la de alguien
que te dio permiso explícito.
