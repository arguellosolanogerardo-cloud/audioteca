// Voces de la Audioteca: cuáles existen (`macos`, la voz del sistema, siempre; y cada referencia
// `voces/<nombre>.wav|txt` → voz `<nombre>-clon` de Qwen3-TTS, la misma regla que usa el narrador), qué
// narraciones tiene cada libro, cuáles van en la cola del narrador y cuál está sonando ahora. La app solo
// escribe `pedidos.json` (las voces que pides desde el teléfono); `cola.json` y `estado.json` son del narrador.
export const VOZ_SISTEMA = 'macos'
import { readdirSync, existsSync, writeFileSync, renameSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { leerJson, VOZ } from './libros.mjs'

const NARRABLES = new Set(['texto-listo', 'narrando', 'completo'])
const MAX_PEDIDOS = 40

let etiquetas = {}
try { etiquetas = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'etiquetas-voces.json'), 'utf8')) } catch { /* opcional */ }

/** «mi-voz-clon» → «Mi Voz» (etiquetas-voces.json solo pone acentos o apodos; la lista sale de la carpeta). */
export function nombreDeVoz(id) {
  const base = id.replace(/-clon$/, '')
  return etiquetas[base] || base.split('-').map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(' ')
}

function vivo(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false
  try { process.kill(pid, 0); return true } catch (e) { return e.code === 'EPERM' }
}

export function crearVoces({ voces: dirVoces, narrador: dirNarrador }) {
  const rutaPedidos = join(dirNarrador, 'pedidos.json')

  function disponibles() {
    let archivos = []
    try { archivos = readdirSync(dirVoces) } catch { archivos = [] }
    return archivos
      .map((f) => /^([a-z0-9][a-z0-9-]{0,50})\.wav$/.exec(f)?.[1])
      .filter((n) => n && existsSync(join(dirVoces, `${n}.txt`)))
      .map((n) => `${n}-clon`)
      .filter((id) => VOZ.test(id))
      .sort()
      .concat(VOZ_SISTEMA)
  }

  const cola = () => leerJson(join(dirNarrador, 'cola.json')) || {}
  const pedidos = () => (leerJson(rutaPedidos)?.pedidos || []).filter((p) => p && typeof p.slug === 'string' && typeof p.voz === 'string')

  /** Voces de ese libro que el narrador tiene en cola (cola.json + pedidos.json). */
  function enCola(slug, vozLibro) {
    const out = new Set()
    for (const item of cola().orden || []) {
      if (item === slug) out.add(vozLibro)
      else if (item && typeof item === 'object' && item.slug === slug) {
        for (const v of Array.isArray(item.voces) ? item.voces : [vozLibro]) out.add(String(v))
      }
    }
    for (const p of pedidos()) if (p.slug === slug) out.add(p.voz)
    return out
  }

  /** Qué está narrando ahora cada trabajador vivo: [{ libro, voz, capitulo, pct }]. */
  function narrandoAhora() {
    const est = leerJson(join(dirNarrador, 'estado.json')) || {}
    return Object.entries(est)
      .filter(([k, t]) => k.startsWith('trabajador-') && t?.estado === 'narrando' && vivo(Number(t.pid)))
      .map(([, t]) => ({
        libro: String(t.libro || ''),
        voz: typeof t.voz === 'string' ? t.voz : null,
        capitulo: Number(t.capitulo) || null,
        pct: Array.isArray(t.segmentos) && t.segmentos[1] ? Math.round((100 * t.segmentos[0]) / t.segmentos[1]) : null,
      }))
  }

  /** Por qué no se puede pedir otra voz para ese libro (o null si se puede). */
  function motivoNoPedible(ficha) {
    if ((cola().excluidos || []).includes(ficha.slug)) return 'Fuera de la cola de narración'
    if (!NARRABLES.has(ficha.estado)) return 'El texto aún no está listo'
    if (!ficha.capitulos.some((c) => c.texto)) return 'El texto aún no está listo'
    return null
  }

  /** Sección «Voces» de la ficha: todas las voces que existen y lo que ese libro tiene de cada una. */
  function deLibro(ficha) {
    const hay = disponibles()
    const ids = new Set(hay)
    for (const c of ficha.capitulos) for (const v of Object.keys(c.narraciones || {})) ids.add(v)
    const total = ficha.capitulos.filter((c) => c.texto).length || ficha.capitulos.length
    const encolada = enCola(ficha.slug, ficha.voz)
    const ahora = narrandoAhora().filter((t) => t.libro === ficha.slug)
    const noPedible = motivoNoPedible(ficha)
    const lista = [...ids].map((id) => {
      const caps = ficha.capitulos.filter((c) => c.narraciones?.[id])
      const narrando = ahora.filter((t) => (t.voz || ficha.voz) === id).map((t) => ({ capitulo: t.capitulo, pct: t.pct }))
      const completa = total > 0 && caps.length >= total
      return {
        id,
        nombre: nombreDeVoz(id),
        principal: id === ficha.voz,
        narrados: caps.length,
        total,
        duracion: Math.round(caps.reduce((a, c) => a + c.narraciones[id].d, 0)),
        completa,
        enCola: !completa && encolada.has(id),
        pedida: pedidos().some((p) => p.slug === ficha.slug && p.voz === id),
        narrando,
        disponible: hay.includes(id),
        pedible: !noPedible && hay.includes(id) && !completa && !encolada.has(id),
      }
    })
    const peso = (v) => (v.principal ? 0 : v.narrados ? 1 : v.enCola || v.narrando.length ? 2 : 3)
    lista.sort((a, b) => peso(a) - peso(b) || b.narrados - a.narrados || a.nombre.localeCompare(b.nombre))
    return { voces: lista, motivo: noPedible }
  }

  function guardarPedidos(lista) {
    const tmp = `${rutaPedidos}.${process.pid}.tmp`
    writeFileSync(tmp, JSON.stringify({
      nota: 'Lo escribe la Audioteca cuando pides otra voz desde el teléfono. El narrador hace primero el capítulo 1 como muestra y el resto del libro al final de la cola. Ver cola.json.',
      pedidos: lista,
    }, null, 2) + '\n')
    renameSync(tmp, rutaPedidos)
  }

  /** Agrega (slug, voz) a la cola. Devuelve null si quedó pedida, o el motivo si no se puede. */
  function pedir(ficha, voz) {
    const motivo = motivoNoPedible(ficha)
    if (motivo) return motivo
    if (!disponibles().includes(voz)) return 'Esa voz no existe en tu Mac'
    const actual = pedidos()
    if (actual.some((p) => p.slug === ficha.slug && p.voz === voz)) return null
    if (enCola(ficha.slug, ficha.voz).has(voz)) return null
    if (actual.length >= MAX_PEDIDOS) return 'Hay demasiadas voces pedidas en cola'
    guardarPedidos([...actual, { slug: ficha.slug, voz, ts: new Date().toISOString(), origen: 'audioteca' }])
    return null
  }

  function cancelar(slug, voz) {
    const actual = pedidos()
    const resto = actual.filter((p) => !(p.slug === slug && p.voz === voz))
    if (resto.length !== actual.length) guardarPedidos(resto)
    return resto.length !== actual.length
  }

  return { disponibles, deLibro, pedir, cancelar, narrandoAhora }
}
