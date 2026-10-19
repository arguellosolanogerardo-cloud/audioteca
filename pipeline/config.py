"""Configuración compartida del pipeline (extraer, traducir, narrar).

Lee las variables del entorno y, si existe, el `.env` de la raíz del repo (mismo formato que `.env.example`;
el entorno gana). Las rutas relativas son relativas a la raíz del repo, igual que en el servidor Node.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[1]


def _leer_env(ruta: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError:
        return out
    for linea in texto.splitlines():
        if linea.strip().startswith("#"):
            continue
        m = re.match(r"^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*?)\s*$", linea)
        if not m:
            continue
        v = m.group(2)
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        else:
            v = re.sub(r"\s+#.*$", "", v)
        out[m.group(1)] = v
    return out


def entorno() -> dict[str, str]:
    archivo = Path(os.environ.get("AUDIOTECA_ENV") or RAIZ_REPO / ".env")
    return {**_leer_env(archivo), **os.environ}


ENV = entorno()


def valor(clave: str, defecto: str = "") -> str:
    return ENV.get(clave) or defecto


def ruta(clave: str, defecto: str) -> Path:
    p = Path(valor(clave, defecto)).expanduser()
    return p if p.is_absolute() else RAIZ_REPO / p


LIBROS = ruta("AUDIOTECA_LIBROS", "biblioteca")
VOCES = ruta("AUDIOTECA_VOCES", "voces")
TRABAJO = ruta("AUDIOTECA_TRABAJO", ".trabajo")
NARRADOR = TRABAJO / "narrador"          # cola.json, pedidos.json, estado.json
TRADUCTOR = TRABAJO / "traductor"        # extracción y caché de traducción por libro
LOGS = TRABAJO / "logs"

VOZ_SISTEMA = "macos"                    # `say` de macOS: siempre disponible, sin descargar nada
VOZ_DEFECTO = valor("AUDIOTECA_VOZ", VOZ_SISTEMA)
VOZ_MACOS = valor("AUDIOTECA_VOZ_MACOS", "")             # vacío = la primera voz en español del sistema
MODELO_TTS = valor("AUDIOTECA_MODELO_TTS", "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit")
MOTOR_TRADUCCION = valor("AUDIOTECA_MOTOR_TRADUCCION", "gemma4-12b")


def ffmpeg() -> str:
    return valor("AUDIOTECA_FFMPEG") or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
