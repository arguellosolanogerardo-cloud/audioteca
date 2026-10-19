// Sesión de la Audioteca: cookie HttpOnly firmada (HMAC-SHA256) que dura ~1 año, para que el teléfono no
// vuelva a pedir la contraseña. La contraseña es opcional (AUDIOTECA_CONTRASENA en .env): sin ella la app
// queda abierta para quien esté en tu red local. La cookie lleva una huella de la contraseña: si la cambias,
// todas las sesiones anteriores dejan de valer.
import { createHash, createHmac, randomBytes, timingSafeEqual } from 'node:crypto'
import { readFileSync, writeFileSync, existsSync, mkdirSync, chmodSync } from 'node:fs'
import { dirname } from 'node:path'

export const COOKIE = 'audioteca_s'
const DURACION_S = 400 * 24 * 3600

export function cargarSecreto(ruta) {
  if (existsSync(ruta)) return readFileSync(ruta, 'utf8').trim()
  mkdirSync(dirname(ruta), { recursive: true })
  const s = randomBytes(32).toString('base64url')
  writeFileSync(ruta, s + '\n', { mode: 0o600 })
  chmodSync(ruta, 0o600)
  return s
}

const b64 = (s) => Buffer.from(s).toString('base64url')
const firmar = (secreto, datos) => createHmac('sha256', secreto).update(datos).digest('base64url')

/** Huella corta de la contraseña (va dentro de la cookie; no permite recuperarla). */
export const huella = (secreto, contraseña) => firmar(secreto, `contraseña:${contraseña || ''}`).slice(0, 12)

export function emitir(secreto, h, ahora = Date.now()) {
  const datos = b64(JSON.stringify({ h, iat: Math.floor(ahora / 1000), exp: Math.floor(ahora / 1000) + DURACION_S }))
  return `${datos}.${firmar(secreto, datos)}`
}

export function verificar(secreto, valor, h, ahora = Date.now()) {
  if (!valor || typeof valor !== 'string') return null
  const [datos, firma] = valor.split('.')
  if (!datos || !firma) return null
  const esperada = Buffer.from(firmar(secreto, datos))
  const recibida = Buffer.from(firma)
  if (esperada.length !== recibida.length || !timingSafeEqual(esperada, recibida)) return null
  try {
    const p = JSON.parse(Buffer.from(datos, 'base64url').toString())
    if (!p.exp || p.exp * 1000 < ahora) return null
    if (p.h !== h) return null
    return { exp: p.exp }
  } catch {
    return null
  }
}

export function leerCookies(req) {
  const out = {}
  for (const parte of (req.headers.cookie || '').split(';')) {
    const i = parte.indexOf('=')
    if (i > 0) out[parte.slice(0, i).trim()] = decodeURIComponent(parte.slice(i + 1).trim())
  }
  return out
}

export function cookieSesion(valor, ruta, borrar = false) {
  return [
    `${COOKIE}=${borrar ? '' : valor}`,
    `Path=${ruta}`,
    'HttpOnly',
    'Secure',
    'SameSite=Lax',
    `Max-Age=${borrar ? 0 : DURACION_S}`,
  ].join('; ')
}

/** Límite de intentos de login por IP (ventana deslizante): frena fuerza bruta. */
export function limitador({ max = 6, ventanaMs = 15 * 60 * 1000 } = {}) {
  const intentos = new Map()
  return {
    permitido(ip, ahora = Date.now()) {
      const lista = (intentos.get(ip) || []).filter((t) => ahora - t < ventanaMs)
      intentos.set(ip, lista)
      return lista.length < max
    },
    fallo(ip, ahora = Date.now()) {
      intentos.set(ip, [...(intentos.get(ip) || []), ahora])
    },
    limpiar(ip) { intentos.delete(ip) },
  }
}

/** Compara la contraseña recibida con la de .env en tiempo constante (se comparan sus SHA-256). */
export function contraseñaCorrecta(esperada, recibida) {
  if (!esperada) return false
  const a = createHash('sha256').update(String(esperada)).digest()
  const b = createHash('sha256').update(String(recibida ?? '')).digest()
  return timingSafeEqual(a, b)
}
