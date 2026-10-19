// El shell de la PWA sin paso de build: el servidor sella cada archivo con el hash de su contenido
// (`app.css?h=…`, `js/app.js?h=…`, también dentro de los `import` de cada módulo), así el teléfono guarda
// esas URLs para siempre (immutable) y solo revalida index.html. index.html además declara todos los
// módulos con `modulepreload` para que lleguen en una sola tanda (sin cascada de imports por la red).
// Todo vive en memoria ya comprimido (brotli y gzip); se recalcula solo cuando cambia algún archivo.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, extname, posix } from 'node:path'
import { createHash } from 'node:crypto'
import { brotliCompressSync, gzipSync, constants as zc } from 'node:zlib'

export const TIPOS = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8', '.json': 'application/json', '.webmanifest': 'application/manifest+json',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon', '.mp3': 'audio/mpeg', '.md': 'text/markdown; charset=utf-8', '.woff2': 'font/woff2',
}
const COMPRIMIBLE = new Set(['.html', '.css', '.js', '.mjs', '.json', '.webmanifest', '.svg', '.md', '.ico'])
const SELLABLE = /\.(css|js|png|svg|ico)$/ // lo que index.html y los módulos referencian con ?h=
const hash = (buf) => createHash('sha256').update(buf).digest('base64url').slice(0, 12)

export function comprimir(buf, aceptadas = '', calidad = 5) {
  if (/\bbr\b/.test(aceptadas)) return { cuerpo: brotliCompressSync(buf, { params: { [zc.BROTLI_PARAM_QUALITY]: calidad } }), codificacion: 'br' }
  if (/\bgzip\b/.test(aceptadas)) return { cuerpo: gzipSync(buf, { level: 6 }), codificacion: 'gzip' }
  return { cuerpo: buf, codificacion: null }
}

export function crearEstaticos(publico) {
  let firma = ''
  let revisado = 0
  let archivos = new Map() // '/js/app.js' → { cuerpo, hash, tipo, br?, gzip? }

  function listar(dir = publico, rel = '') {
    const out = []
    for (const d of readdirSync(dir, { withFileTypes: true })) {
      if (d.name.startsWith('.')) continue
      if (d.isDirectory()) out.push(...listar(join(dir, d.name), `${rel}/${d.name}`))
      else out.push(`${rel}/${d.name}`)
    }
    return out
  }

  function construir(rutas) {
    const crudo = new Map(rutas.map((r) => [r, readFileSync(join(publico, r))]))
    const listos = new Map()
    const enCurso = new Set()
    // Un módulo se sella con el hash de su contenido YA reescrito, que incluye el hash de lo que importa:
    // si cambia util.js, cambian también los hashes de quienes lo importan.
    const sellar = (r) => {
      if (listos.has(r)) return listos.get(r)
      if (enCurso.has(r)) throw new Error(`import circular en ${r}`)
      enCurso.add(r)
      let buf = crudo.get(r)
      const ext = extname(r).toLowerCase()
      if (ext === '.js') {
        const base = posix.dirname(r)
        buf = Buffer.from(buf.toString('utf8').replace(/(\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)(['"])(\.{1,2}\/[^'"?]+\.js)\2/g, (m, pre, q, esp) => {
          const destino = posix.normalize(posix.join(base, esp))
          return crudo.has(destino) ? `${pre}${q}${esp}?h=${sellar(destino).hash}${q}` : m
        }))
      }
      const e = { cuerpo: buf, hash: hash(buf), tipo: TIPOS[ext] || 'application/octet-stream', ext }
      listos.set(r, e)
      enCurso.delete(r)
      return e
    }
    for (const r of rutas) if (r !== '/index.html') sellar(r)
    // index.html: sella sus referencias y precarga todos los módulos.
    if (crudo.has('/index.html')) {
      let html = crudo.get('/index.html').toString('utf8').replace(/(href|src)="([^"#?:]+)"/g, (m, attr, ref) => {
        const r = posix.normalize(`/${ref}`)
        return SELLABLE.test(r) && listos.has(r) ? `${attr}="${ref}?h=${listos.get(r).hash}"` : m
      })
      const modulos = [...listos.keys()].filter((r) => r.startsWith('/js/') && r.endsWith('.js')).sort()
      const precargas = modulos.map((r) => `  <link rel="modulepreload" href="${r.slice(1)}?h=${listos.get(r).hash}">`).join('\n')
      html = html.replace(/(\s*<script type="module")/, `\n${precargas}$1`)
      const buf = Buffer.from(html)
      listos.set('/index.html', { cuerpo: buf, hash: hash(buf), tipo: TIPOS['.html'], ext: '.html' })
    }
    for (const e of listos.values()) {
      if (!COMPRIMIBLE.has(e.ext) || e.cuerpo.length < 512) continue
      e.br = comprimir(e.cuerpo, 'br', 11).cuerpo
      e.gzip = comprimir(e.cuerpo, 'gzip').cuerpo
    }
    return listos
  }

  /** Recalcula si algún archivo de public/ cambió (se revisa como mucho una vez por segundo). */
  function vigentes() {
    const ahora = Date.now()
    if (ahora - revisado < 1000 && archivos.size) return archivos
    revisado = ahora
    const rutas = listar()
    const nueva = rutas.map((r) => { const st = statSync(join(publico, r)); return `${r}:${st.size}:${st.mtimeMs}` }).join('|')
    if (nueva !== firma) {
      archivos = construir(rutas)
      firma = nueva
    }
    return archivos
  }

  return {
    /** { cuerpo, hash, tipo, br, gzip } o null. */
    obtener(ruta) { return vigentes().get(ruta) || null },
  }
}
