"""El repo es de marca blanca: ningún archivo versionado lleva rutas personales, correos, llaves, dominios de
túneles ni datos de quien lo instaló. Corre sobre `git ls-files` (lo que se publica)."""
import re
import subprocess
import unittest

from tests.python.base import REPO

PROHIBIDO = [
    (r"/Users/[A-Za-z]", "ruta de una carpeta personal de macOS"),
    (r"/home/[a-z]", "ruta de una carpeta personal"),
    (r"[\w.+-]+@(?!ejemplo\.com|example\.com|noreply)[\w-]+\.[a-z]{2,}", "correo"),
    (r"[a-z0-9-]+\.ts\.net\b|[a-z0-9-]+\.ngrok(-free)?\.(io|app)|[a-z0-9-]+\.trycloudflare\.com", "dominio de un túnel concreto"),
    (r"(?i)supabase", "login de un servicio externo"),
    (r"\b(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[bp]-[A-Za-z0-9-]{10,})", "llave o token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "llave privada"),
]
BINARIOS = re.compile(r"\.(png|jpe?g|ico|pdf|epub|mp3|wav|m4a)$")


class MarcaBlanca(unittest.TestCase):
    def test_sin_datos_personales(self):
        archivos = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split()
        if not archivos:
            self.skipTest("fuera de un repo git")
        hallazgos = []
        for f in archivos:
            if BINARIOS.search(f) or f == "package-lock.json":
                continue
            try:
                texto = (REPO / f).read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue
            for patron, que in PROHIBIDO:
                for m in re.finditer(patron, texto):
                    if f.endswith("test_marca_blanca.py"):
                        continue
                    hallazgos.append(f"{f}: {que}: {m.group(0)[:40]}")
        self.assertEqual(hallazgos, [])

    def test_sin_libros_audios_ni_voces_versionados(self):
        archivos = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split()
        malos = [f for f in archivos if re.search(r"\.(mp3|wav|m4a|aiff)$", f) or f.startswith(("biblioteca/", ".data/", ".trabajo/", "voces/") ) and not f.endswith("LEEME.md")]
        self.assertEqual(malos, [])


if __name__ == "__main__":
    unittest.main()
