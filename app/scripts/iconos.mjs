// Ícono, favicon y splash de la Audioteca desde un solo SVG maestro: claroscuro sobre el casi negro,
// una sombra azul arriba y el oro como la luz: un libro abierto del que sube la voz.
// Uso: node app/scripts/iconos.mjs → public/iconos/{icono.svg, favicon.ico, *.png, splash/*.png}
import { webkit } from 'playwright'
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync, readFileSync, renameSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const dir = join(dirname(fileURLToPath(import.meta.url)), '../public/iconos')
mkdirSync(join(dir, 'splash'), { recursive: true })

const ORO = { claro: '#f3c676', base: '#e3a53c', osc: '#b07d24' }
const MORADO = '#3f6fe0'
const VACIO = '#09090b'

/** La marca (libro + voz) en un lienzo de 1024; `grosor` engruesa los trazos para tamaños chicos. */
const marca = (grosor = 1) => `
  <g filter="url(#brillo)" stroke="url(#oro)" stroke-linecap="round" fill="none">
    <g stroke-width="${38 * grosor}">
      <line x1="392" y1="424" x2="392" y2="498"/>
      <line x1="452" y1="352" x2="452" y2="498"/>
      <line x1="512" y1="268" x2="512" y2="498"/>
      <line x1="572" y1="330" x2="572" y2="498"/>
      <line x1="632" y1="404" x2="632" y2="498"/>
    </g>
    <path stroke-width="${24 * grosor}" stroke-linejoin="round" d="M512 606 C 440 556 330 544 228 562 L 228 772 C 330 754 440 766 512 816 C 584 766 694 754 796 772 L 796 562 C 694 544 584 556 512 606 Z"/>
    <path stroke-width="${24 * grosor}" d="M512 606 L 512 816"/>
  </g>`

const defs = (brillo = 14) => `
  <defs>
    <radialGradient id="sombra" cx="50%" cy="30%" r="62%"><stop offset="0" stop-color="${MORADO}" stop-opacity=".34"/><stop offset=".7" stop-color="${MORADO}" stop-opacity=".06"/><stop offset="1" stop-color="${MORADO}" stop-opacity="0"/></radialGradient>
    <radialGradient id="luz" cx="50%" cy="44%" r="34%"><stop offset="0" stop-color="${ORO.base}" stop-opacity=".22"/><stop offset="1" stop-color="${ORO.base}" stop-opacity="0"/></radialGradient>
    <linearGradient id="fondo" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1a1621"/><stop offset=".55" stop-color="#0f0d13"/><stop offset="1" stop-color="${VACIO}"/></linearGradient>
    <linearGradient id="oro" gradientUnits="userSpaceOnUse" x1="0" y1="250" x2="0" y2="830"><stop offset="0" stop-color="${ORO.claro}"/><stop offset=".6" stop-color="${ORO.base}"/><stop offset="1" stop-color="${ORO.osc}"/></linearGradient>
    <filter id="brillo" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="${brillo}" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>`

/** Ícono cuadrado a sangre (iOS y Android le ponen su propia máscara). `escala` < 1 deja zona segura (maskable). */
const icono = ({ escala = 1.1, grosor = 1, brillo = 14, radio = 0 } = {}) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">${defs(brillo)}
  <rect width="1024" height="1024" rx="${radio}" fill="url(#fondo)"/>
  <rect width="1024" height="1024" rx="${radio}" fill="url(#sombra)"/>
  <rect width="1024" height="1024" rx="${radio}" fill="url(#luz)"/>
  <g transform="translate(512 512) scale(${escala}) translate(-512 -542)">${marca(grosor)}</g>
</svg>`

// favicon.svg: esquinas redondeadas (la pestaña no le pone máscara) y trazos más gruesos.
const faviconSvg = icono({ escala: 1.18, grosor: 1.35, brillo: 10, radio: 224 })
writeFileSync(join(dir, 'icono.svg'), faviconSvg.replace(/\n\s*/g, ' '))

const navegador = await webkit.launch()
const pagina = await navegador.newPage()
async function png(svg, lado, ruta, { fondo = VACIO } = {}) {
  await pagina.setViewportSize({ width: lado, height: lado })
  await pagina.setContent(`<html><body style="margin:0;background:${fondo}">${svg.replace('width="1024" height="1024"', `width="${lado}" height="${lado}"`)}</body></html>`)
  return pagina.screenshot({ path: ruta, clip: { x: 0, y: 0, width: lado, height: lado }, omitBackground: fondo === 'transparent' })
}

for (const [nombre, lado, opts] of [
  ['icono-512.png', 512, {}],
  ['icono-192.png', 192, { grosor: 1.1 }],
  ['apple-touch-icon.png', 180, { grosor: 1.1 }],
  // Maskable: la marca dentro del círculo seguro (80 %) para que Android no la recorte.
  ['icono-maskable-512.png', 512, { escala: 0.84 }],
]) {
  await png(icono(opts), lado, join(dir, nombre))
  // Paleta de 256 colores con difuminado: un tercio del peso y sin bandas visibles en el degradado.
  const tmp = join(tmpdir(), `audioteca-${nombre}`)
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', join(dir, nombre), '-vf', 'split[a][b];[a]palettegen=max_colors=256:stats_mode=full[p];[b][p]paletteuse=dither=sierra2_4a', tmp])
  renameSync(tmp, join(dir, nombre))
}

// favicon.ico con 16, 32 y 48 (PNG dentro del ICO: lo aceptan todos los navegadores actuales).
const chicos = []
for (const lado of [16, 32, 48]) chicos.push([lado, await png(icono({ escala: 1.3, grosor: lado < 32 ? 1.9 : 1.5, brillo: 6 }), lado)])
const cabecera = Buffer.alloc(6)
cabecera.writeUInt16LE(0, 0); cabecera.writeUInt16LE(1, 2); cabecera.writeUInt16LE(chicos.length, 4)
let desplazamiento = 6 + 16 * chicos.length
const entradas = chicos.map(([lado, datos]) => {
  const e = Buffer.alloc(16)
  e.writeUInt8(lado, 0); e.writeUInt8(lado, 1); e.writeUInt8(0, 2); e.writeUInt8(0, 3)
  e.writeUInt16LE(1, 4); e.writeUInt16LE(32, 6); e.writeUInt32LE(datos.length, 8); e.writeUInt32LE(desplazamiento, 12)
  desplazamiento += datos.length
  return e
})
writeFileSync(join(dir, 'favicon.ico'), Buffer.concat([cabecera, ...entradas, ...chicos.map(([, d]) => d)]))

// Splash de iOS (apple-touch-startup-image): una por tamaño de pantalla, en vertical.
export const PANTALLAS = [
  [440, 956, 3], [402, 874, 3], [430, 932, 3], [393, 852, 3], [428, 926, 3],
  [390, 844, 3], [375, 812, 3], [414, 896, 3], [414, 896, 2], [375, 667, 2],
]
const marcaSola = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="160 220 704 660" width="100%" height="100%">${defs(14)}${marca(1)}</svg>`
for (const [w, h, dpr] of PANTALLAS) {
  const ctx = await navegador.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: dpr })
  const p = await ctx.newPage()
  await p.setContent(`<html><body style="margin:0;height:100vh;display:grid;place-items:center;background:
      radial-gradient(70% 40% at 50% 38%, ${MORADO}2e, #0000 70%), radial-gradient(40% 22% at 50% 42%, ${ORO.base}1a, #0000 70%), ${VACIO}">
    <div style="display:flex;flex-direction:column;align-items:center;gap:18px;margin-top:-6vh">
      <div style="width:132px;height:124px">${marcaSola}</div>
      <div style="font-family:'Iowan Old Style',Palatino,Georgia,serif;font-size:34px;font-weight:600;color:#f7f8f8;letter-spacing:-.01em">Audio<em style="color:${ORO.claro};font-weight:500">teca</em></div>
    </div></body></html>`)
  await p.screenshot({ path: join(dir, 'splash', `splash-${w * dpr}x${h * dpr}.jpg`), type: 'jpeg', quality: 80 })
  await ctx.close()
}
await navegador.close()

// Las etiquetas <link> de splash que van en index.html (se imprimen para pegarlas si cambia la lista).
const links = PANTALLAS.map(([w, h, dpr]) => `  <link rel="apple-touch-startup-image" media="(device-width: ${w}px) and (device-height: ${h}px) and (-webkit-device-pixel-ratio: ${dpr}) and (orientation: portrait)" href="iconos/splash/splash-${w * dpr}x${h * dpr}.jpg">`).join('\n')
const index = join(dir, '../index.html')
const html = readFileSync(index, 'utf8')
if (!html.includes('apple-touch-startup-image')) console.log('Agrega a index.html:\n' + links)
console.log('íconos listos en', dir)
