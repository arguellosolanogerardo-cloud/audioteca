// Carátulas: la de `portada.jpg` si el libro la trae; si no, una tipográfica de la casa (claroscuro con un
// tono propio por libro). Para la pantalla bloqueada se dibuja la misma en un canvas y se guarda en caché,
// así la Media Session tiene carátula también sin red.
import { rutas } from './api.js'
import { esc } from './util.js'

// Tonos de sombra (familia morada y sus vecinos fríos/cálidos) — nunca el oro, que es la luz.
const TONOS = ['#3f6fe0', '#2f5fa8', '#3d3a9e', '#2e6b5e', '#7a4a2e', '#2f4f8f', '#4a3f8f', '#6b2f3a', '#2e5a6b']

function hash(slug) {
  let h = 0
  for (const c of slug) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return h
}
export const tonoDe = (slug) => TONOS[hash(slug) % TONOS.length]
// Tres composiciones (título arriba, abajo, centrado con capitular) para que los lomos no se vean clonados.
const varianteDe = (slug) => (hash(slug) >>> 4) % 3

export function portadaHtml(libro) {
  const tono = tonoDe(libro.slug)
  const src = rutas.portada(libro)
  if (src) return `<div class="portada" style="--tono:${tono}"><img src="${esc(src)}" alt="" loading="lazy" decoding="async"></div>`
  return `<div class="portada" style="--tono:${tono}" aria-hidden="true"><div class="portada-gen pg-v${varianteDe(libro.slug)}">
    <div class="pg-autor">${esc(libro.autor)}</div><div class="pg-inicial">${esc((libro.titulo.match(/\p{L}/u) || [''])[0])}</div>
    <div class="pg-raya"></div><div class="pg-titulo">${esc(libro.titulo)}</div></div></div>`
}

function partirLineas(ctx, texto, ancho) {
  const palabras = texto.split(/\s+/)
  const lineas = []
  let linea = ''
  for (const p of palabras) {
    const prueba = linea ? `${linea} ${p}` : p
    if (ctx.measureText(prueba).width > ancho && linea) { lineas.push(linea); linea = p } else linea = prueba
  }
  if (linea) lineas.push(linea)
  return lineas
}

const URL_GENERADA = (slug) => new URL(`portada-generada/${encodeURIComponent(slug)}.png`, location.href).href

/** URL de carátula para la Media Session (cuadrada, ≥512 px). */
export async function arteParaPantallaBloqueada(libro) {
  if (libro.portada) return [{ src: new URL(rutas.portada(libro), location.href).href, sizes: '512x768', type: 'image/jpeg' }]
  const url = URL_GENERADA(libro.slug)
  try {
    if (typeof caches === 'undefined') throw new Error('sin caches')
    const cache = await caches.open('audioteca-datos-v1')
    if (!(await cache.match(url))) {
      const lado = 768
      const c = document.createElement('canvas')
      c.width = c.height = lado
      const ctx = c.getContext('2d')
      ctx.fillStyle = '#09090b'
      ctx.fillRect(0, 0, lado, lado)
      const g = ctx.createRadialGradient(lado / 2, 0, 10, lado / 2, 0, lado * 0.85)
      g.addColorStop(0, tonoDe(libro.slug))
      g.addColorStop(1, '#09090b00')
      ctx.fillStyle = g
      ctx.fillRect(0, 0, lado, lado)
      ctx.fillStyle = '#ffffffb3'
      ctx.font = '600 26px -apple-system, system-ui, sans-serif'
      ctx.fillText((libro.autor || '').toUpperCase(), 80, 150)
      ctx.fillStyle = '#e3a53c'
      ctx.shadowColor = '#e3a53c'
      ctx.shadowBlur = 16
      ctx.fillRect(80, 196, 120, 3)
      ctx.shadowBlur = 0
      ctx.fillStyle = '#f7f8f8'
      ctx.font = '600 72px "Iowan Old Style", Palatino, Georgia, serif'
      partirLineas(ctx, libro.titulo, lado - 160).slice(0, 5).forEach((l, i) => ctx.fillText(l, 80, 300 + i * 82))
      ctx.beginPath()
      ctx.arc(88, lado - 96, 8, 0, Math.PI * 2)
      ctx.fillStyle = '#e3a53c'
      ctx.shadowBlur = 18
      ctx.fill()
      const blob = await new Promise((ok) => c.toBlob(ok, 'image/png'))
      await cache.put(url, new Response(blob, { headers: { 'content-type': 'image/png' } }))
    }
    return [{ src: url, sizes: '768x768', type: 'image/png' }]
  } catch {
    return [{ src: new URL('iconos/icono-512.png', location.href).href, sizes: '512x512', type: 'image/png' }]
  }
}
