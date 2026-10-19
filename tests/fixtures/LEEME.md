# Fixtures de dominio público

- `quijote.md`: fragmentos de los capítulos I y II de *El ingenioso hidalgo don Quijote de la Mancha*,
  Miguel de Cervantes (1605). Dominio público.
- `fabulas.txt`, `fabulas.epub`, `fabulas.pdf`: dos fábulas de Esopo en la traducción inglesa de
  George Fyler Townsend (1867). Dominio público. El EPUB y el PDF los genera `crear_fixtures.py` a partir
  del texto (sin dependencias): el EPUB usa `<div>` en lugar de `<p>` y mete un subtítulo `<h3>` a mitad de
  un `<div>`, como algunos EPUB comerciales; el PDF repite una cabecera y numera páginas, como un libro impreso.
- `glosario.md`: glosario de ejemplo en los dos formatos que entiende el traductor.
