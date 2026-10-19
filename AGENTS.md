# Audioteca · notas para quien contribuya (personas o agentes)

- Lee primero `README.md` (uso) y `docs/FORMATO.md` (la interfaz entre piezas: nadie más que el narrador
  escribe `audio/`, nadie más que el extractor/traductor escribe `texto/`, la app solo lee y escribe `pedidos.json`).
- Configuración: siempre por `.env` (`app/server/config.mjs` y `pipeline/config.py` leen lo mismo). Nada de rutas
  absolutas, correos, dominios ni llaves en el código: `tests/python/test_marca_blanca.py` lo vigila.
- Escrituras atómicas (tmp → rename) y `libro.json` con candado (`.libro.lock`). Sin borrados recursivos.
- Antes de entregar: `./audioteca check` (Node unit + Python + e2e WebKit). Si cambias `app/public/sw.js` en sí,
  sube su `VERSION`; el resto del shell se sella solo con hash de contenido.
- Íconos y splash: `node app/scripts/iconos.mjs` (la paleta vive en `:root` de `app/public/app.css`).
