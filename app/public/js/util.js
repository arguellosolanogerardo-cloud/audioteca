// Utilidades de interfaz: íconos SVG en línea, formato de tiempos y avisos.

const s = (d, extra = '') => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${d}</svg>`

export const icono = {
  play: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M8 5.6v12.8c0 .8.9 1.3 1.6.8l10-6.4c.6-.4.6-1.3 0-1.7l-10-6.4C8.9 4.3 8 4.8 8 5.6z"/></svg>`,
  pausa: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect fill="currentColor" x="6" y="5" width="4.2" height="14" rx="1.2"/><rect fill="currentColor" x="13.8" y="5" width="4.2" height="14" rx="1.2"/></svg>`,
  atras: s('<path d="M15 18l-6-6 6-6"/>'),
  abajo: s('<path d="M6 9l6 6 6-6"/>'),
  menos15: s('<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 3.8v3.4h3.4"/>'),
  mas30: s('<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 3.8v3.4h-3.4"/>'),
  anterior: s('<path d="M6 5v14"/><path d="M18 6.2v11.6c0 .7-.8 1.1-1.4.7L9 13a1.2 1.2 0 0 1 0-2l7.6-5.5c.6-.4 1.4 0 1.4.7z" fill="currentColor" stroke="none"/>'),
  siguiente: s('<path d="M18 5v14"/><path d="M6 6.2v11.6c0 .7.8 1.1 1.4.7L15 13a1.2 1.2 0 0 0 0-2L7.4 5.5C6.8 5.1 6 5.5 6 6.2z" fill="currentColor" stroke="none"/>'),
  descargar: s('<path d="M12 4v11"/><path d="M7 10.5l5 5 5-5"/><path d="M5 19.5h14"/>'),
  descargado: s('<path d="M20 6.5L9.5 17 4.5 12"/>'),
  nube: s('<path d="M7 18.5h10a4 4 0 0 0 .6-8A5.5 5.5 0 0 0 7 9.2 4.7 4.7 0 0 0 7 18.5z"/>'),
  luna: s('<path d="M20 14.5A8 8 0 1 1 9.5 4a6.3 6.3 0 0 0 10.5 10.5z"/>'),
  lista: s('<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r=".9" fill="currentColor"/><circle cx="4.5" cy="12" r=".9" fill="currentColor"/><circle cx="4.5" cy="18" r=".9" fill="currentColor"/>'),
  letra: `<svg viewBox="0 0 24 24" aria-hidden="true"><text x="2" y="18" font-family="Iowan Old Style, Georgia, serif" font-size="15" fill="currentColor">A</text><text x="12" y="18" font-family="Iowan Old Style, Georgia, serif" font-size="10" fill="currentColor">a</text></svg>`,
  ajustes: s('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>'),
  libro: s('<path d="M12 6.5C10 5 7 4.6 3.5 5v13c3.5-.4 6.5 0 8.5 1.5 2-1.5 5-1.9 8.5-1.5V5C17 4.6 14 5 12 6.5z"/><path d="M12 6.5v13"/>'),
  voz: s('<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"/>'),
  basura: s('<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>'),
  subir: s('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>'),
  mas: s('<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>'),
  pdf: s('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'),
  check: s('<polyline points="20 6 9 17 4 12"/>'),
  buscar: s('<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>'),
  auriculares: s('<path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/>'),
  relojIcon: s('<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'),
  chispa: s('<path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z"/>'),
  cargando: `<svg class="girar" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10" stroke-opacity=".2"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>`,
}

export const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

/** 3725 → "1:02:05"; 65 → "1:05". */
export function reloj(seg) {
  seg = Math.max(0, Math.floor(seg || 0))
  const h = Math.floor(seg / 3600)
  const m = Math.floor((seg % 3600) / 60)
  const x = String(seg % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${x}` : `${m}:${x}`
}

/** 4500 → "1 h 15 min"; 300 → "5 min". */
export function duracionHumana(seg) {
  seg = Math.max(0, Math.round(seg || 0))
  const h = Math.floor(seg / 3600)
  const m = Math.round((seg % 3600) / 60)
  if (h && m) return `${h} h ${m} min`
  if (h) return `${h} h`
  if (m) return `${m} min`
  return seg ? `${seg} s` : '0 min'
}

export const velTexto = (v) => `${Number(v).toFixed(2).replace(/0$/, '').replace(/\.0$/, '')}×`

export function megas(bytes) {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`
  return `${Math.max(0.1, bytes / 1e6).toFixed(bytes > 1e8 ? 0 : 1)} MB`
}

let temporizadorAviso = null
export function avisar(texto, ms = 3200) {
  const el = document.getElementById('aviso')
  el.textContent = texto
  el.hidden = false
  clearTimeout(temporizadorAviso)
  temporizadorAviso = setTimeout(() => { el.hidden = true }, ms)
}

export const nn = (n) => String(n).padStart(2, '0')
export const h = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild }
