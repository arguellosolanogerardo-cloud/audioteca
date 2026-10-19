import json
import subprocess
import sys
import unittest

from tests.python.base import FIXTURES, HAY_PDFTOTEXT, REPO, TMP  # noqa: F401  (prepara el entorno)
import extraer  # noqa: E402

FABULAS = ["The Lion and the Mouse", "The Hare and the Tortoise"]


class Extraer(unittest.TestCase):
    def titulos(self, caps):
        return [c["titulo"].lower() for c in caps]

    def test_markdown_en_espanol(self):
        caps = extraer.extraer(FIXTURES / "quijote.md", idioma="es")
        self.assertEqual(len(caps), 2)
        self.assertTrue(caps[0]["titulo"].startswith("Capítulo primero"))
        self.assertTrue(caps[0]["parrafos"][0].startswith("En un lugar de la Mancha"))
        self.assertEqual(len(caps[0]["parrafos"]), 2)

    def test_txt_con_titulos_en_mayusculas(self):
        caps = extraer.extraer(FIXTURES / "fabulas.txt")
        self.assertEqual(self.titulos(caps), [t.lower() for t in FABULAS], "la portada (título y traductor) queda fuera")
        self.assertEqual(len(caps[1]["parrafos"]), 3)

    def test_epub_con_div_en_vez_de_p(self):
        caps = extraer.extraer(FIXTURES / "fabulas.epub")
        self.assertEqual(self.titulos(caps), [t.lower() for t in FABULAS], "fuera portada y copyright")
        leon, liebre = caps
        self.assertEqual(len(leon["parrafos"]), 2, "cada <div> es un párrafo")
        # el <h3> metido a mitad de un <div> con texto suelto: subtítulo y texto salen por separado
        self.assertEqual(liebre["parrafos"][-2:], ["Moral", "Slow but steady wins the race."])

    def test_bloques_html_mezclados(self):
        html = "<body><div>Antes <em>del</em> título<h3>Sub</h3>después</div><ul><li>uno</li><li><p>dos</p></li></ul><blockquote><p>a</p><p>b</p></blockquote></body>"
        self.assertEqual(extraer.bloques_html(html), [("p", "Antes del título"), ("h3", "Sub"), ("p", "después"),
                                                      ("p", "uno"), ("p", "dos"), ("p", "a"), ("p", "b")])

    @unittest.skipUnless(HAY_PDFTOTEXT, "falta pdftotext (brew install poppler)")
    def test_pdf_sin_cabeceras_ni_numeros_de_pagina(self):
        caps = extraer.extraer(FIXTURES / "fabulas.pdf")
        self.assertEqual(self.titulos(caps), [t.lower() for t in FABULAS])
        todo = " ".join(p for c in caps for p in c["parrafos"])
        self.assertNotIn("Aesop's Fables", todo, "cabecera repetida fuera")
        self.assertNotRegex(todo, r"(^|\s)[2-5](\s|$)", "números de página fuera")
        # los renglones partidos se vuelven a unir en párrafos completos
        self.assertTrue(caps[0]["parrafos"][0].endswith("The Lion laughed and let him go."))
        self.assertEqual(len(caps[0]["parrafos"]), 2)

    def test_capitulares_segun_idioma(self):
        self.assertEqual(extraer.limpiar_parrafo("W hat a day", "en"), "What a day")
        self.assertEqual(extraer.limpiar_parrafo("E l día empezó", "es"), "El día empezó")
        self.assertEqual(extraer.limpiar_parrafo("Y luego se fue", "es"), "Y luego se fue")
        self.assertEqual(extraer.limpiar_parrafo("A veces llueve", "es"), "A veces llueve")
        self.assertEqual(extraer.limpiar_parrafo("Costó 50,000 pesos y 1.5 kilos", "es"), "Costó 50,000 pesos y 1.5 kilos")

    def test_cli_escribe_el_libro_listo_para_narrar(self):
        r = subprocess.run([sys.executable, str(REPO / "pipeline/extraer.py"), str(FIXTURES / "quijote.md"), "--slug", "quijote-cli",
                            "--titulo", "Don Quijote", "--autor", "Miguel de Cervantes"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = TMP / "biblioteca" / "quijote-cli"
        meta = json.loads((d / "libro.json").read_text())
        self.assertEqual((meta["estado"], meta["voz"], meta["traducido"], len(meta["capitulos"])), ("texto-listo", "macos", False, 2))
        self.assertTrue((d / "texto/01.md").read_text().startswith("# Capítulo primero"))


if __name__ == "__main__":
    unittest.main()
