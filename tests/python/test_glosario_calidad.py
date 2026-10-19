import unittest

from tests.python.base import FIXTURES  # noqa: F401
import calidad  # noqa: E402
import glosario as G  # noqa: E402


class Glosario(unittest.TestCase):
    def setUp(self):
        self.e = G.leer(FIXTURES / "glosario.md")

    def test_lee_lista_y_tabla(self):
        self.assertEqual(sorted((x.en, x.es) for x in self.e),
                         [("Hare", "liebre"), ("Tortoise", "tortuga"), ("slow but steady", "lento pero seguro")])

    def test_verifica_con_flexion(self):
        en = "The Tortoise and the Hare met again."
        self.assertEqual(G.verificar(self.e, en, "La tortuga y la liebre se vieron otra vez."), [])
        faltan = G.verificar(self.e, en, "El galápago y la liebre se vieron otra vez.")
        self.assertEqual([x.en for x in faltan], ["Tortoise"])

    def test_primera_aparicion_lleva_el_original(self):
        ya = set()
        es = G.marcar_primera_vez(self.e, "The Tortoise won.", "La tortuga ganó.", ya)
        self.assertEqual(es, "La tortuga (*Tortoise*) ganó.")
        self.assertEqual(G.marcar_primera_vez(self.e, "The Tortoise won.", "La tortuga ganó.", ya), "La tortuga ganó.")


class Calidad(unittest.TestCase):
    EN = "The Hare, lying down by the wayside, fell fast asleep while the Tortoise kept walking for 1,200 steps."

    def test_traduccion_buena_pasa(self):
        es = "La liebre, recostada a la orilla del camino, se quedó dormida mientras la tortuga siguió caminando 1,200 pasos."
        self.assertEqual(calidad.revisar_parrafo(self.EN, es), [])

    def test_detecta_ingles_cifras_y_bucles(self):
        self.assertTrue(any("inglés" in p or "idéntico" in p for p in calidad.revisar_parrafo(self.EN, self.EN)))
        self.assertTrue(any("cifras" in p for p in calidad.revisar_parrafo(self.EN, "La liebre se durmió a la orilla del camino mientras la tortuga caminaba muchos pasos.")))
        bucle = "la liebre se durmió en el camino " * 5
        self.assertTrue(any("repetición" in p for p in calidad.revisar_parrafo(self.EN + " 1,200", bucle + "1,200")))

    def test_capitulo(self):
        self.assertEqual(calidad.revisar_capitulo([("one two three four five", "uno dos tres cuatro cinco")])["estado"], "ok")
        self.assertEqual(calidad.revisar_capitulo([("one two three four five six seven eight nine ten", "uno dos")])["estado"], "omisión probable")


if __name__ == "__main__":
    unittest.main()
