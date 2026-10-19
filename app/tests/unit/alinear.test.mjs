import { test } from 'node:test'
import assert from 'node:assert/strict'
import { alinearCapitulo, parsearMarkdown, normalizar } from '../../server/alinear.mjs'

const textoDe = (bloques, s) => bloques.flatMap((b) => b.tramos).filter((t) => t[1] === s).map((t) => t[0]).join('').trim()

test('parsea título, párrafos, énfasis y citas', () => {
  const { titulo, bloques } = parsearMarkdown('# Uno *dos*\n\nHola **mundo** y _todo_.\nSigue.\n\n> cita\n\n- punto\n')
  assert.equal(titulo, 'Uno dos')
  assert.deepEqual(bloques.map((b) => b.tipo), ['h1', 'p', 'q', 'li'])
  assert.equal(bloques[1].plano, 'Hola mundo y todo. Sigue.')
  assert.equal(bloques[1].marcas[5], 'strong')
  assert.equal(bloques[1].marcas[13], 'em')
})

test('alinea oraciones exactas, con signos de apertura y cierre dentro de su segmento', () => {
  const md = '# El puerto\n\n¿Quién trae carga? Nadie respondió. «Llegaste a tiempo».\n'
  const segs = [{ texto: 'El puerto.' }, { texto: '¿Quién trae carga?' }, { texto: 'Nadie respondió.' }, { texto: '«Llegaste a tiempo».' }]
  const { bloques } = alinearCapitulo(md, segs)
  assert.equal(textoDe(bloques, 0), 'El puerto')
  assert.equal(textoDe(bloques, 1), '¿Quién trae carga?')
  assert.equal(textoDe(bloques, 2), 'Nadie respondió.')
  assert.equal(textoDe(bloques, 3), '«Llegaste a tiempo».')
})

test('un segmento que el narrador cambió (cifras deletreadas) no arrastra a los siguientes', () => {
  const md = '# C\n\nEn 1984 todo cambió. Después vino la calma. Y luego el mar.\n'
  const segs = [{ texto: 'C' }, { texto: 'En mil novecientos ochenta y cuatro todo cambió.' }, { texto: 'Después vino la calma.' }, { texto: 'Y luego el mar.' }]
  const { bloques } = alinearCapitulo(md, segs)
  assert.equal(textoDe(bloques, 2), 'Después vino la calma.')
  assert.equal(textoDe(bloques, 3), 'Y luego el mar.')
  assert.match(textoDe(bloques, 1), /1984 todo cambió/)
})

test('acentos y mayúsculas no rompen el anclaje', () => {
  assert.equal(normalizar('¡ÁRBOL, ñandú!'), 'arbolnandu')
  const { bloques } = alinearCapitulo('# T\n\nÁrbol grande.\n', [{ texto: 'T' }, { texto: 'arbol GRANDE' }])
  assert.equal(textoDe(bloques, 1), 'Árbol grande.')
})

test('capítulo sin audio: todo el texto queda sin segmento', () => {
  const { bloques } = alinearCapitulo('# T\n\nUno. Dos.\n', [])
  assert.ok(bloques.flatMap((b) => b.tramos).every((t) => t[1] === -1))
})

test('un capítulo largo alinea cada segmento en orden y sin solaparse', () => {
  const oraciones = Array.from({ length: 400 }, (_, i) => `Oración número ${i} con algo de texto repetido.`)
  const md = `# Largo\n\n${oraciones.slice(0, 200).join(' ')}\n\n${oraciones.slice(200).join(' ')}\n`
  const segs = [{ texto: 'Largo' }, ...oraciones.map((texto) => ({ texto }))]
  const t0 = performance.now()
  const { bloques } = alinearCapitulo(md, segs)
  assert.ok(performance.now() - t0 < 500)
  for (const i of [1, 57, 200, 201, 400]) assert.equal(textoDe(bloques, i), oraciones[i - 1])
})
