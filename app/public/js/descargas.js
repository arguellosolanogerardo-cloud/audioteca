// Descargas para escuchar sin red: el mp3 completo y el texto alineado de cada capítulo van a Cache Storage
// (`audioteca-libros-v1`). El service worker los sirve sin red, con Range para que Safari pueda reproducir.
// Con varias voces se descarga la voz que elegiste para ese libro (cada capítulo en la voz que va a
// sonar); `libro` llega ya proyectado con conVoz().
import { rutas } from './api.js'
import { VOZ_V1 } from './voces.js'

export const CACHE_LIBROS = 'audioteca-libros-v1'
const abs = (rel) => new URL(rel, location.href).href
const hayCaches = () => typeof caches !== 'undefined'

/** { n: 'audio'|'viejo'|false } por capítulo: 'viejo' = descargado pero el narrador lo rehízo. */
export async function estadoDescargas(libro) {
  const out = {}
  if (!hayCaches()) return out
  const cache = await caches.open(CACHE_LIBROS)
  await Promise.all(libro.capitulos.filter((c) => c.audio).map(async (c) => {
    if (await cache.match(abs(rutas.audio(libro.slug, c.n, c.v, c.voz)))) out[c.n] = 'audio'
    else if (await cache.match(abs(rutas.audio(libro.slug, c.n, null, c.voz)), { ignoreSearch: true })) out[c.n] = 'viejo'
    else out[c.n] = false
  }))
  return out
}

/** Sin red: la voz de ese capítulo que sí está en el teléfono (la elegida si está; si no, otra descargada). */
export async function vozDescargada(slug, cap) {
  if (!hayCaches()) return null
  const cache = await caches.open(CACHE_LIBROS)
  for (const [voz, x] of [[cap.voz, cap.narraciones?.[cap.voz]], ...Object.entries(cap.narraciones || {})]) {
    if (voz && x && (await cache.match(abs(rutas.audio(slug, cap.n, x.v, voz))))) return voz
  }
  return null
}

/** Descargas hechas antes de las voces (v1: audio/NN.mp3, capitulos/NN): solo existía una voz. Se
 *  re-guardan con la ruta de su voz para que sigan sonando sin red; el contenido es el mismo archivo. */
export async function migrarDescargasV1() {
  if (!hayCaches() || localStorage.getItem('audioteca.descargas.v2')) return
  const cache = await caches.open(CACHE_LIBROS)
  for (const k of await cache.keys()) {
    const u = new URL(k.url)
    const audio = /^(.*\/api\/libros\/[^/]+\/audio\/)(\d{2,3}\.mp3)$/.exec(u.pathname)
    const cap = /\/api\/libros\/[^/]+\/capitulos\/\d{2,3}$/.test(u.pathname) && !u.search
    if (audio) {
      const nueva = new URL(`${audio[1]}${VOZ_V1}/${audio[2]}${u.search}`, u.origin).href
      const r = await cache.match(k)
      if (r && !(await cache.match(nueva))) await cache.put(nueva, r)
      await cache.delete(k)
    } else if (cap) {
      const r = await cache.match(k)
      const datos = r && (await r.clone().json().catch(() => null))
      if (datos?.audio) await cache.put(`${k.url}?voz=${VOZ_V1}`, r)
    }
  }
  localStorage.setItem('audioteca.descargas.v2', '1')
}

export function resumen(libro, estado) {
  const narrados = libro.capitulos.filter((c) => c.audio)
  const listos = narrados.filter((c) => estado[c.n] === 'audio')
  return {
    total: narrados.length,
    listos: listos.length,
    bytes: listos.reduce((a, c) => a + c.bytes, 0),
    completo: narrados.length > 0 && listos.length === narrados.length,
  }
}

const enCurso = new Map() // slug → { abortar, progreso }

export function descargaEnCurso(slug) { return enCurso.get(slug) || null }

async function guardar(cache, url) {
  const r = await fetch(url, { credentials: 'same-origin', cache: 'no-store' })
  if (!r.ok) throw new Error(`No se pudo bajar (${r.status})`)
  await cache.put(url, r)
}

/** Baja los capítulos narrados que falten. `alAvanzar(fraccion)` reporta por bytes reales. */
export async function descargarLibro(libro, { soloCapitulo = null, alAvanzar = () => {} } = {}) {
  // Safari solo da Cache Storage en contexto seguro: por http://<ip-local> se escucha en streaming, sin descargas.
  if (!hayCaches()) throw new Error(window.isSecureContext ? 'Este navegador no permite descargas offline' : 'Para descargar y escuchar sin red, abre la Audioteca por HTTPS (ver README: «Escuchar sin red»)')
  if (enCurso.has(libro.slug)) return enCurso.get(libro.slug).promesa
  const control = new AbortController()
  const estado = { abortar: () => control.abort(), progreso: 0 }
  enCurso.set(libro.slug, estado)
  estado.promesa = (async () => {
    try {
      navigator.storage?.persist?.().catch(() => {})
      const cache = await caches.open(CACHE_LIBROS)
      const actual = await estadoDescargas(libro)
      const pendientes = libro.capitulos.filter((c) => c.audio && actual[c.n] !== 'audio' && (!soloCapitulo || c.n === soloCapitulo))
      const total = pendientes.reduce((a, c) => a + c.bytes, 0) || 1
      let hecho = 0
      // Ficha y textos (también los capítulos aún sin audio) para leer sin red.
      await guardar(cache, abs(rutas.libro(libro.slug)))
      for (const c of libro.capitulos.filter((x) => x.texto && (!soloCapitulo || x.n === soloCapitulo))) {
        if (control.signal.aborted) throw new DOMException('cancelado', 'AbortError')
        await guardar(cache, abs(rutas.capitulo(libro.slug, c.n, c.audio ? c.voz : null)))
      }
      if (libro.portada) await guardar(cache, abs(rutas.portada(libro))).catch(() => {})
      for (const c of pendientes) {
        const url = abs(rutas.audio(libro.slug, c.n, c.v, c.voz))
        const r = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: control.signal })
        if (!r.ok || !r.body) throw new Error(`No se pudo bajar el capítulo ${c.n}`)
        // Se lee en trozos para reportar avance real, y se guarda entero (200, no 206: cache.put lo exige).
        const lector = r.body.getReader()
        const trozos = []
        for (;;) {
          const { done, value } = await lector.read()
          if (done) break
          trozos.push(value)
          hecho += value.byteLength
          estado.progreso = Math.min(0.999, hecho / total)
          alAvanzar(estado.progreso)
        }
        const cuerpo = new Blob(trozos, { type: 'audio/mpeg' })
        await cache.put(url, new Response(cuerpo, { headers: { 'content-type': 'audio/mpeg', 'content-length': String(cuerpo.size) } }))
        // Versiones viejas del mismo capítulo ya no sirven.
        for (const k of await cache.keys(abs(rutas.audio(libro.slug, c.n, null, c.voz)), { ignoreSearch: true })) if (k.url !== url) await cache.delete(k)
      }
      estado.progreso = 1
      alAvanzar(1)
    } finally {
      enCurso.delete(libro.slug)
    }
  })()
  return estado.promesa
}

export async function borrarLibro(slug) {
  if (!hayCaches()) return
  const cache = await caches.open(CACHE_LIBROS)
  const prefijo = abs(`api/libros/${encodeURIComponent(slug)}`)
  for (const k of await cache.keys()) if (k.url === prefijo || k.url.startsWith(prefijo + '/')) await cache.delete(k)
}

/** Libros con algo descargado y lo que ocupan (para Ajustes). */
export async function inventario() {
  if (!hayCaches()) return {}
  const cache = await caches.open(CACHE_LIBROS)
  const out = {}
  for (const k of await cache.keys()) {
    const m = /\/api\/libros\/([^/]+)\/audio\//.exec(new URL(k.url).pathname)
    if (!m) continue
    const r = await cache.match(k)
    const bytes = Number(r?.headers.get('content-length')) || 0
    const slug = decodeURIComponent(m[1])
    out[slug] = out[slug] || { capitulos: 0, bytes: 0 }
    out[slug].capitulos++
    out[slug].bytes += bytes
  }
  return out
}
