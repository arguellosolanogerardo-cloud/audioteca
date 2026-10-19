"""Entorno aislado para los tests del pipeline: todo va a una carpeta temporal y no se lee el .env del usuario.
Se importa antes que cualquier módulo de pipeline/ (config.py lee el entorno al importarse)."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"
TMP = Path(tempfile.mkdtemp(prefix="audioteca-tests-"))
os.environ.update({
    "AUDIOTECA_ENV": str(TMP / "no-existe.env"),
    "AUDIOTECA_LIBROS": str(TMP / "biblioteca"),
    "AUDIOTECA_VOCES": str(TMP / "voces"),
    "AUDIOTECA_TRABAJO": str(TMP / "trabajo"),
    "AUDIOTECA_VOZ": "macos",
    "TRADUCTOR_FONDO": "1",          # no relanzar bajo taskpolicy durante los tests
})
for k in ("AUDIOTECA_VOZ_MACOS", "AUDIOTECA_MODELO_TTS", "AUDIOTECA_MOTOR_TRADUCCION"):
    os.environ.pop(k, None)
sys.path.insert(0, str(REPO / "pipeline"))

HAY_SAY = shutil.which("say") is not None
HAY_FFMPEG = shutil.which("ffmpeg") is not None
HAY_PDFTOTEXT = shutil.which("pdftotext") is not None
