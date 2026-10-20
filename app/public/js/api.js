// Cliente de la API del servidor de tu Mac. Rutas relativas: la app puede vivir en / o bajo un prefijo
// (AUDIOTECA_PREFIJO) detrás de un proxy. Latencia: cada viaje cuesta la red del teléfono, así que
//  · las peticiones iguales en vuelo se comparten y las fichas/capítulos recientes se reusan de memoria;
//  · la biblioteca y las fichas se guardan en localStorage para pintar al instante y refrescar después.
import { nn } from './util.js'

export class SinSesion extends Error {}

async function pedir(ruta, opts = {}) {
  const r = await fetch(ruta, { credentials: 'same-origin', ...opts })
  if (r.status === 401) throw new SinSesion()
  if (!r.ok) {
    const j = await r.json().catch(() => ({}))
    throw Object.assign(new Error(j.error || `Error ${r.status}`), { estado: r.status })
  }
  return r.json()
}

const json = (cuerpo, metodo = 'POST') => ({ method: metodo, headers: { 'content-type': 'application/json' }, body: JSON.stringify(cuerpo) })
const e = encodeURIComponent

export const rutas = {
  audio: (slug, n, v, voz) => `api/libros/${e(slug)}/audio/${voz ? `${e(voz)}/` : ''}${nn(n)}.mp3${v ? `?v=${v}` : ''}`,
  capitulo: (slug, n, voz) => `api/libros/${e(slug)}/capitulos/${nn(n)}${voz ? `?voz=${e(voz)}` : ''}`,
  libro: (slug) => `api/libros/${e(slug)}`,
  portada: (libro) => (libro.portada ? `api/libros/${e(libro.slug)}/${libro.portada}` : null),
  glosario: (slug) => `api/libros/${e(slug)}/glosario`,
  voz: (slug, voz) => `api/libros/${e(slug)}/voces/${e(voz)}`,
}

// ── Memoria corta: una petición en vuelo se comparte; un resultado reciente se reusa ──
const memoria = new Map() // clave → { t, promesa }
function recordar(clave, vigenciaMs, fn) {
  const m = memoria.get(clave)
  if (m && Date.now() - m.t < vigenciaMs) return m.promesa
  const promesa = fn()
  memoria.set(clave, { t: Date.now(), promesa })
  promesa.catch(() => { if (memoria.get(clave)?.promesa === promesa) memoria.delete(clave) })
  if (memoria.size > 40) memoria.delete(memoria.keys().next().value)
  return promesa
}
export const olvidar = (prefijo) => { for (const k of memoria.keys()) if (k.startsWith(prefijo)) memoria.delete(k) }

// ── Copia en localStorage para la primera pintura (se reemplaza en cuanto llega la red) ──
const LLAVE = 'audioteca.guardado.'
const guardar = (ruta, datos) => { try { localStorage.setItem(LLAVE + ruta, JSON.stringify(datos)) } catch { /* cuota: no pasa nada */ } return datos }
export function guardado(ruta) { try { return JSON.parse(localStorage.getItem(LLAVE + ruta)) } catch { return null } }

const FICHA_MS = 15000

export const api = {
  sesion: () => pedir('api/sesion'),
  entrar: (contraseña) => pedir('api/login', json({ contraseña })),
  salir: () => pedir('api/salir', json({})),
  libros: () => recordar('libros', 2000, () => pedir('api/libros').then((d) => guardar('libros', d))),
  /** Ficha del libro; `fresca` salta la memoria (refresco periódico). */
  libro: (slug, { fresca = false } = {}) => {
    if (fresca) olvidar(`libro:${slug}`)
    return recordar(`libro:${slug}`, FICHA_MS, () => pedir(rutas.libro(slug)).then((d) => guardar(rutas.libro(slug), d)))
  },
  libroGuardado: (slug) => guardado(rutas.libro(slug)),
  librosGuardados: () => guardado('libros'),
  /** Texto alineado con una voz. `v` (versión del audio) entra en la clave: si el narrador rehace, se pide de nuevo. */
  capitulo: (slug, n, voz = null, v = '') => recordar(`cap:${slug}/${nn(n)}/${voz}/${v}`, 10 * 60000, () => pedir(rutas.capitulo(slug, n, voz))),
  progreso: () => pedir('api/progreso'),
  ponerProgreso: (slug, p) => pedir(`api/progreso/${e(slug)}`, { ...json(p, 'PUT'), keepalive: true }),
  pedirVoz: (slug, voz) => pedir(rutas.voz(slug, voz), json({})).then((d) => { olvidar(`libro:${slug}`); return guardar(rutas.libro(slug), d) }),
  cancelarVoz: (slug, voz) => pedir(rutas.voz(slug, voz), json({}, 'DELETE')).then((d) => { olvidar(`libro:${slug}`); return guardar(rutas.libro(slug), d) }),
  glosario: async (slug) => {
    const r = await fetch(rutas.glosario(slug), { credentials: 'same-origin' })
    if (r.status === 401) throw new SinSesion()
    return r.ok ? r.text() : null
  },
  vocesDisponibles: () => pedir('api/voces-disponibles'),
  tarea: (id) => pedir('api/tareas/' + e(id)),
  subirPdf: (archivo, { titulo, autor, voz, slug } = {}, onProgreso = null) => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', 'api/libros/subir')
      xhr.setRequestHeader('content-type', 'application/pdf')
      if (titulo) xhr.setRequestHeader('x-titulo', encodeURIComponent(titulo))
      if (autor) xhr.setRequestHeader('x-autor', encodeURIComponent(autor))
      if (voz) xhr.setRequestHeader('x-voz', voz)
      if (slug) xhr.setRequestHeader('x-slug', slug)

      if (onProgreso && xhr.upload) {
        xhr.upload.onprogress = (ev) => {
          if (ev.lengthComputable) {
            const pct = Math.round((ev.loaded / ev.total) * 100)
            onProgreso(pct)
          }
        }
      }

      xhr.onload = () => {
        if (xhr.status === 401) return reject(new SinSesion())
        try {
          const res = JSON.parse(xhr.responseText)
          if (xhr.status >= 200 && xhr.status < 300) resolve(res)
          else reject(new Error(res.error || `Error ${xhr.status}`))
        } catch {
          reject(new Error('Respuesta del servidor no válida'))
        }
      }
      xhr.onerror = () => reject(new Error('Error de conexión al subir el archivo'))
      xhr.send(archivo)
    })
  },
  eliminarLibro: (slug) => pedir(rutas.libro(slug), { method: 'DELETE' }).then((res) => {
    olvidar('libros')
    olvidar(`libro:${slug}`)
    try {
      localStorage.removeItem('audioteca.guardado.' + rutas.libro(slug))
      localStorage.removeItem('audioteca.guardado.libros')
    } catch {}
    return res
  }),
}
