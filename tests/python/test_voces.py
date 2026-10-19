import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.python.base import HAY_FFMPEG, HAY_SAY, TMP  # noqa: F401
import voces  # noqa: E402


@unittest.skipUnless(HAY_SAY and HAY_FFMPEG, "necesita macOS (say) y ffmpeg")
class Clonar(unittest.TestCase):
    def test_clonar_desde_m4a(self):
        d = Path(tempfile.mkdtemp(prefix="audioteca-voz-"))
        aiff, m4a = d / "g.aiff", d / "grabacion.m4a"
        texto = "Hola, esta es una grabación de prueba para clonar una voz en la Audioteca."
        subprocess.run(["say", "-o", str(aiff), texto], check=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(aiff), "-c:a", "aac", str(m4a)], check=True)
        self.assertEqual(voces.clonar("prueba", m4a, texto), 0)
        wav, txt = TMP / "voces/prueba.wav", TMP / "voces/prueba.txt"
        self.assertTrue(wav.exists() and txt.read_text().strip() == texto)
        import soundfile as sf
        info = sf.info(str(wav))
        self.assertEqual((info.channels, info.samplerate), (1, 24000))
        import narrar
        self.assertIn("prueba-clon", narrar.voces_disponibles())

    def test_nombre_y_texto_invalidos(self):
        with self.assertRaises(SystemExit):
            voces.clonar("Mi Voz", Path("/no/existe.wav"), "texto suficientemente largo para pasar")
        with self.assertRaises(SystemExit):
            voces.clonar("ok", Path(__file__), "corto")


if __name__ == "__main__":
    unittest.main()
