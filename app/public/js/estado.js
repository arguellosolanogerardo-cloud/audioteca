// Estado local del teléfono: progreso por libro, velocidad por libro y preferencias.
// localStorage es la fuente en el teléfono (sobrevive offline); el servidor guarda copia para sincronizar.
import { api } from './api.js'

const LLAVE_PROGRESO = 'audioteca.progreso'
const LLAVE_PREFS = 'audioteca.prefs'
const LLAVE_PENDIENTES = 'audioteca.progreso.pendientes'

const leer = (k, def) => { try { return JSON.parse(localStorage.getItem(k)) ?? def } catch { return def } }
const escribir = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* cuota llena: se pierde solo el último guardado */ } }

export const VELOCIDADES = [0.75, 1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 2.75, 3]
export const VEL_MIN = 0.75
export const VEL_MAX = 3
export const VEL_DEFAULT = 1.75

export function prefs() {
  return { letra: 20, ultimaVel: VEL_DEFAULT, ...leer(LLAVE_PREFS, {}) }
}
export function guardarPref(k, v) { escribir(LLAVE_PREFS, { ...prefs(), [k]: v }) }

export function progresos() { return leer(LLAVE_PROGRESO, {}) }
export function progreso(slug) { return progresos()[slug] || null }

/** Velocidad de un libro: la suya si ya la tiene, si no la última que usaste (1.75× la primera vez). */
export function velocidadDe(slug) {
  const p = progreso(slug)
  const v = Number(p?.vel)
  return v >= VEL_MIN && v <= VEL_MAX ? v : prefs().ultimaVel
}

/** Voz que elegiste para ese libro (null = la voz del libro). Viaja con el progreso al servidor. */
export const vozDe = (slug) => progreso(slug)?.voz || null

export function guardarProgreso(slug, datos, { sincronizar = false } = {}) {
  const todos = progresos()
  const p = { ...(todos[slug] || {}), ...datos, ts: Date.now() }
  todos[slug] = p
  escribir(LLAVE_PROGRESO, todos)
  const pend = leer(LLAVE_PENDIENTES, [])
  if (!pend.includes(slug)) escribir(LLAVE_PENDIENTES, [...pend, slug])
  if (sincronizar) sincronizarPendientes()
  return p
}

let sincronizando = false
/** Sube al servidor los progresos que cambiaron; si no hay red, quedan en cola para la próxima. */
export async function sincronizarPendientes() {
  if (sincronizando || !navigator.onLine) return
  sincronizando = true
  try {
    const pend = leer(LLAVE_PENDIENTES, [])
    const todos = progresos()
    for (const slug of pend) {
      const p = todos[slug]
      if (!p) continue
      const r = await api.ponerProgreso(slug, p).catch(() => null)
      if (!r) return
      escribir(LLAVE_PENDIENTES, leer(LLAVE_PENDIENTES, []).filter((x) => x !== slug))
    }
  } finally {
    sincronizando = false
  }
}

/** Trae el progreso del servidor y se queda con el más reciente de cada libro (otro dispositivo pudo avanzar). */
export async function fusionarProgresoRemoto() {
  const remoto = await api.progreso().catch(() => null)
  if (!remoto) return false
  const local = progresos()
  let cambio = false
  for (const [slug, p] of Object.entries(remoto)) {
    if (!local[slug] || (p.ts || 0) > (local[slug].ts || 0)) { local[slug] = p; cambio = true }
  }
  if (cambio) escribir(LLAVE_PROGRESO, local)
  return cambio
}

/** El libro que escuchaste más recientemente (para «Continuar»). */
export function ultimoLibro() {
  const todos = Object.entries(progresos()).filter(([, p]) => !p.fin)
  todos.sort((a, b) => (b[1].ts || 0) - (a[1].ts || 0))
  return todos[0]?.[0] || null
}
