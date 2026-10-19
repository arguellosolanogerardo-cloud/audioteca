// Configuración de la Audioteca: variables de entorno y, si existe, el archivo `.env` de la raíz del repo
// (mismo formato que `.env.example`). El entorno gana sobre `.env`. Las rutas relativas son relativas a la
// raíz del repo, así el mismo `.env` sirve al servidor (Node), al narrador y al traductor (Python).
import { readFileSync } from 'node:fs'
import { join, dirname, resolve, isAbsolute } from 'node:path'
import { fileURLToPath } from 'node:url'
import { homedir } from 'node:os'

export const RAIZ_REPO = resolve(dirname(fileURLToPath(import.meta.url)), '../..')

/** Lee un .env sencillo: CLAVE=valor, comillas opcionales, # comentarios. */
export function leerEnv(ruta) {
  const out = {}
  let txt = ''
  try { txt = readFileSync(ruta, 'utf8') } catch { return out }
  for (const linea of txt.split('\n')) {
    const m = /^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*?)\s*$/.exec(linea)
    if (!m || linea.trim().startsWith('#')) continue
    let v = m[2]
    if (/^(["']).*\1$/.test(v)) v = v.slice(1, -1)
    else v = v.replace(/\s+#.*$/, '')
    out[m[1]] = v
  }
  return out
}

export function entorno(env = process.env, raiz = RAIZ_REPO) {
  const archivo = env.AUDIOTECA_ENV || join(raiz, '.env')
  return { ...leerEnv(archivo), ...env }
}

/** Ruta de una variable: `~` = carpeta personal; relativa = desde la raíz del repo. */
export function ruta(valor, defecto, raiz = RAIZ_REPO) {
  let v = valor || defecto
  if (v.startsWith('~/')) v = join(homedir(), v.slice(2))
  return isAbsolute(v) ? v : join(raiz, v)
}
