import json
import tempfile
import unittest
from pathlib import Path

from tests.python.base import FIXTURES, HAY_FFMPEG, HAY_SAY  # noqa: F401
import extraer  # noqa: E402
import narrar  # noqa: E402


class Segmentos(unittest.TestCase):
    def test_titulo_y_oraciones_con_pausas(self):
        segs = narrar.segmentos("# Capítulo uno\n\nPrimera oración que es lo bastante larga para no unirse con nada más. ¿Segunda? Sí.\n\nOtro párrafo.")
        self.assertEqual(segs[0], {"texto": "Capítulo uno", "pausa": narrar.PAUSA_TITULO})
        # las oraciones muy cortas se unen a la anterior (Qwen se pierde con trozos de dos palabras)
        self.assertEqual([s["texto"] for s in segs[1:]], ["Primera oración que es lo bastante larga para no unirse con nada más. ¿Segunda? Sí.", "Otro párrafo."])
        self.assertEqual(segs[-1]["pausa"], narrar.PAUSA_PARRAFO)

    def test_oracion_larguisima_se_corta(self):
        larga = ("palabra, " * 60).strip()
        self.assertTrue(all(len(s) <= narrar.MAX_SEG for s in narrar.oraciones(larga)))

    def test_lo_que_oye_la_voz(self):
        self.assertEqual(narrar.para_voz("*Hola* — dijo — ¡¡¡CUIDADO!!! 1— Uno"), "Hola, dijo, ¡Cuidado! 1. Uno.")


class Cola(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="audioteca-cola-"))
        self.viejo = {k: getattr(narrar, k) for k in ("LIBROS", "COLA", "PEDIDOS", "ESTADO", "VOCES")}
        narrar.LIBROS = self.tmp / "biblioteca"
        narrar.COLA = self.tmp / "narrador/cola.json"
        narrar.PEDIDOS = self.tmp / "narrador/pedidos.json"
        narrar.ESTADO = self.tmp / "narrador/estado.json"
        narrar.VOCES = self.tmp / "voces"
        narrar.VOCES.mkdir(parents=True)
        (self.tmp / "narrador").mkdir()
        for slug, estado in (("a", "texto-listo"), ("b", "texto-listo"), ("c", "pendiente-traduccion"), ("d", "completo")):
            d = narrar.LIBROS / slug / "texto"
            d.mkdir(parents=True)
            (d / "01.md").write_text("# Uno\n\nHola.\n")
            (d.parent / "libro.json").write_text(json.dumps({"slug": slug, "voz": "macos", "estado": estado,
                                                              "capitulos": [{"n": 1, "titulo": "Uno", "archivo_texto": "texto/01.md"}]}))

    def tearDown(self):
        for k, v in self.viejo.items():
            setattr(narrar, k, v)
        narrar.SOLO.clear()

    def test_voces_disponibles(self):
        (narrar.VOCES / "mi-voz.wav").write_bytes(b"RIFF")
        (narrar.VOCES / "mi-voz.txt").write_text("hola")
        (narrar.VOCES / "incompleta.wav").write_bytes(b"RIFF")
        self.assertEqual(narrar.voces_disponibles(), {"macos", "mi-voz-clon"})

    def test_orden_excluidos_y_pedidos(self):
        (narrar.VOCES / "mi-voz.wav").write_bytes(b"RIFF")
        (narrar.VOCES / "mi-voz.txt").write_text("hola")
        narrar.COLA.write_text(json.dumps({"orden": ["b"], "excluidos": ["a"]}))
        narrar.PEDIDOS.write_text(json.dumps({"pedidos": [{"slug": "d", "voz": "mi-voz-clon"}]}))
        self.assertEqual(narrar.plan(), [("d", "mi-voz-clon", 1), ("b", "macos", None), ("d", "mi-voz-clon", None)],
                         "muestra pedida primero, luego el orden; «a» excluido, «c» sin texto listo, «d» ya completo en su voz")

    def test_solo_un_libro(self):
        narrar.SOLO.update({"libro": "a", "voz": "macos"})
        self.assertEqual(narrar.plan(), [("a", "macos", None)])
        narrar.SOLO.update({"libro": "a", "voz": "nadie-clon"})
        self.assertEqual(narrar.plan(), [])

    def test_lock_atomico(self):
        libro = narrar.Libro("a")
        lock = narrar.reclamar(libro, "macos", 1)
        self.assertIsNotNone(lock)
        self.assertIsNone(narrar.reclamar(libro, "macos", 1), "otro trabajador no puede tomar el mismo capítulo")
        lock.write_text("999999")                              # pid muerto: el lock huérfano se recupera
        self.assertIsNotNone(narrar.reclamar(libro, "macos", 1))


@unittest.skipUnless(HAY_SAY and HAY_FFMPEG, "necesita macOS (say) y ffmpeg")
class NarrarConMacOS(unittest.TestCase):
    """Narración real de un libro de dominio público con la voz del sistema: mp3 + json + libro.json completo."""

    def test_libro_completo_y_reanudable(self):
        caps = extraer.extraer(FIXTURES / "quijote.md", idioma="es")
        d = narrar.LIBROS / "quijote-narrado"
        for n, c in enumerate(caps, 1):
            extraer.escribir_atomico(d / "texto" / f"{n:02d}.md", f"# {c['titulo']}\n\n" + "\n\n".join(c["parrafos"]) + "\n")
        extraer.actualizar_libro(d, lambda m: m.update({"slug": "quijote-narrado", "voz": "macos", "estado": "texto-listo",
                                                         "capitulos": extraer.capitulos_en_meta(m, [c["titulo"] for c in caps])}))
        narrar.SOLO.update({"libro": "quijote-narrado"})
        decir = narrar.VozMacOS.decir
        try:
            self.assertEqual(narrar.trabajador(0), 0)
            meta = json.loads((d / "libro.json").read_text())
            self.assertEqual(meta["estado"], "completo")
            for c in meta["capitulos"]:
                self.assertEqual(c["archivo_audio"], f"audio/macos/{c['n']:02d}.mp3")
                self.assertGreater((d / c["archivo_audio"]).stat().st_size, 10_000)
                segs = json.loads((d / f"audio/macos/{c['n']:02d}.json").read_text())
                self.assertEqual(segs["voz"], "macos")
                tiempos = [(s["inicio"], s["fin"]) for s in segs["segmentos"]]
                self.assertTrue(all(a < b for a, b in tiempos) and all(tiempos[i][1] <= tiempos[i + 1][0] for i in range(len(tiempos) - 1)))
                self.assertAlmostEqual(segs["duracion_s"], c["duracion_s"])
            self.assertTrue(segs["segmentos"][0]["texto"].startswith("Capítulo segundo"))
            # reanudable: borrar el mp3 y volver a narrar usa la caché de segmentos (no llama a say)
            (d / "audio/macos/02.mp3").unlink()
            narrar.VozMacOS.decir = lambda *_: (_ for _ in ()).throw(AssertionError("no debía volver a sintetizar"))
            self.assertEqual(narrar.trabajador(0), 0)
            self.assertTrue((d / "audio/macos/02.mp3").exists())
        finally:
            narrar.VozMacOS.decir = decir
            narrar.SOLO.clear()


if __name__ == "__main__":
    unittest.main()
