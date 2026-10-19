"""Traductor de punta a punta con un motor falso (sin GPU ni descargas): extracción, caché, glosario, calidad
y libro.json. El motor real (Gemma 4 en MLX) se prueba a mano: ver README («Probar el traductor»)."""
import json
import re
import sys
import unittest
from unittest import mock

from tests.python.base import FIXTURES, TMP  # noqa: F401
import motores  # noqa: E402
import traducir  # noqa: E402

DICCIONARIO = {
    "The Lion and the Mouse": "El león y el ratón", "The Hare and the Tortoise": "La liebre y la tortuga",
    "Slow but steady wins the race.": "Lento pero seguro se gana la carrera.", "Moral": "Moraleja",
}


# 61 palabras distintas (primo): el relleno no repite frases de 5 palabras, que calidad.py tomaría por un bucle.
PALABRAS = ("el de que y en un una por con para se su al lo como más pero sus le ya o este fue muy sin sobre también "
            "hasta hay donde quien desde todo nos durante todos uno les ni contra otros ese eso ante ellos esto antes "
            "algunos casa camino tiempo noche mañana campo río monte puerto ciudad luz agua fuego").split()


class MotorFalso(motores.Motor):
    """«Traduce» devolviendo un español plausible del mismo largo; respeta el glosario que recibe."""
    llamadas = 0

    def __init__(self, ingles=False):
        super().__init__("falso", "falso", "mlx-chat", {}, acepta_glosario=True)
        self.ingles = ingles

    def traducir(self, texto, contexto=None, glosario=None, nota=""):
        MotorFalso.llamadas += 1
        if self.ingles:
            return texto
        if texto in DICCIONARIO:
            return DICCIONARIO[texto]
        n = len(re.findall(r"\w+", texto))
        cifras = re.findall(r"\d[\d,.]*", texto)
        glos = [es for _, es in (glosario or [])]
        relleno = [PALABRAS[(i * 7) % len(PALABRAS)] for i in range(max(n - len(glos) - len(cifras), 4))]
        return " ".join(["la"] + glos + cifras + relleno).capitalize() + "."


class Traducir(unittest.TestCase):
    def correr(self, slug, motor, *extra):
        argv = ["traducir.py", str(FIXTURES / "fabulas.epub"), "--slug", slug, "--glosario", str(FIXTURES / "glosario.md"),
                "--titulo", "Fábulas de Esopo", "--autor", "Esopo", *extra]
        with mock.patch.object(motores, "cargar", lambda *a, **k: motor), mock.patch.object(sys, "argv", argv):
            self.assertEqual(traducir.main(), 0)
        d = TMP / "biblioteca" / slug
        return d, json.loads((d / "libro.json").read_text())

    def test_libro_traducido_y_reanudable(self):
        d, meta = self.correr("fabulas", MotorFalso())
        self.assertEqual([c["titulo"] for c in meta["capitulos"]], ["El león y el ratón", "La liebre y la tortuga"])
        self.assertEqual((meta["traducido"], meta["idioma_original"], meta["voz"]), (True, "en", "macos"))
        self.assertEqual(meta["estado"], "texto-listo")
        md = (d / "texto/02.md").read_text()
        self.assertTrue(md.startswith("# La liebre y la tortuga\n\n"))
        self.assertIn("liebre (*Hare*)", md, "primera aparición del término con su original")
        self.assertEqual(md.count("(*Hare*)"), 1)
        self.assertIn("aprobado", (d / "calidad-traduccion.md").read_text())
        antes = MotorFalso.llamadas
        self.correr("fabulas", MotorFalso())
        self.assertEqual(MotorFalso.llamadas, antes, "la segunda vez todo sale de la caché")

    def test_traduccion_mala_queda_en_revision(self):
        d, meta = self.correr("fabulas-mal", MotorFalso(ingles=True))
        self.assertEqual(meta["estado"], "revision-traduccion", "el narrador no la toma")
        self.assertIn("REVISAR", (d / "calidad-traduccion.md").read_text())


if __name__ == "__main__":
    unittest.main()
