#!/usr/bin/env python3
"""Voces del narrador: listar, crear la voz genérica de Qwen y clonar la tuya.

    ./audioteca voz listar
    ./audioteca voz base                                   # crea `qwen-clon`, la voz genérica del modelo
    ./audioteca voz clonar mi-voz grabacion.m4a "Lo que dices en la grabación, palabra por palabra."
    ./audioteca voz probar mi-voz-clon "Una frase cualquiera."   # → .trabajo/prueba-mi-voz-clon.wav

Una voz clonada son dos archivos en `voces/` (AUDIOTECA_VOCES): `<nombre>.wav` (10-20 s de una sola
persona, sin música ni ruido) y `<nombre>.txt` (la transcripción exacta). El narrador la llama
`<nombre>-clon` y la app la ofrece sola en la ficha de cada libro. Clona solo tu voz o la de alguien
que te dio permiso.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

NOMBRE = re.compile(r"^[a-z0-9][a-z0-9-]{0,50}$")
MAX_S = 20.0           # referencias más largas no mejoran el clon y lo vuelven inestable
# Frase de referencia de la voz genérica: español neutro, ~10 s, con pausas y una pregunta.
FRASE_BASE = ("Hola. Esta es la voz con la que voy a narrar tus libros. "
              "Hablo despacio, con calma y con claridad, como en una buena tarde de lectura. ¿Empezamos?")


def listar() -> int:
    v = config.VOCES
    clones = sorted(w.stem for w in v.glob("*.wav") if (v / f"{w.stem}.txt").exists())
    print(f"macos{'':16} voz del sistema (say): siempre disponible")
    for c in clones:
        print(f"{c + '-clon':21} Qwen3-TTS clonando voces/{c}.wav")
    if not clones:
        print(f"(sin voces clonadas en {v}; crea una con `./audioteca voz base` o `./audioteca voz clonar`)")
    print(f"voz por defecto de libros nuevos: {config.VOZ_DEFECTO} (AUDIOTECA_VOZ en .env)")
    return 0


def _duracion(ruta: Path) -> float:
    import soundfile as sf
    info = sf.info(str(ruta))
    return info.frames / info.samplerate


def _a_wav(origen: Path, destino: Path, segundos: float = MAX_S) -> None:
    """Cualquier audio (m4a, mp3, wav…) → wav mono 24 kHz, normalizado y recortado a `segundos`."""
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-i", str(origen), "-ac", "1", "-ar", "24000",
                    "-t", str(segundos), "-af", "silenceremove=start_periods=1:start_threshold=-45dB,loudnorm=I=-18:TP=-2",
                    "-c:a", "pcm_s16le", str(destino)], check=True)


def clonar(nombre: str, audio: Path, texto: str) -> int:
    if not NOMBRE.match(nombre):
        sys.exit("nombre inválido: minúsculas, números y guiones (p. ej. mi-voz)")
    if nombre.endswith("-clon"):
        nombre = nombre.removesuffix("-clon")
    audio = audio.expanduser().resolve()
    if not audio.exists():
        sys.exit(f"no existe {audio}")
    texto = " ".join(texto.split())
    if len(texto) < 20:
        sys.exit("escribe la transcripción exacta de la grabación (al menos una frase completa)")
    config.VOCES.mkdir(parents=True, exist_ok=True)
    wav, txt = config.VOCES / f"{nombre}.wav", config.VOCES / f"{nombre}.txt"
    with tempfile.TemporaryDirectory(prefix="audioteca-voz-") as d:
        tmp = Path(d) / "ref.wav"
        _a_wav(audio, tmp)
        dur = _duracion(tmp)
        if dur < 3:
            sys.exit(f"la grabación dura {dur:.1f} s: graba entre 10 y 20 s hablando con naturalidad")
        tmp.replace(wav)
    txt.write_text(texto + "\n", encoding="utf-8")
    print(f"voz «{nombre}-clon» lista: {wav} ({dur:.1f} s) + {txt.name}")
    if dur > MAX_S - 0.5:
        print(f"  (recortada a {MAX_S:.0f} s: si la transcripción incluye lo que quedó fuera, ajústala en {txt})")
    print(f"  pruébala: ./audioteca voz probar {nombre}-clon \"Una frase de prueba.\"")
    print(f"  úsala:    ./audioteca narrar --libro <slug> --voz {nombre}-clon   (o AUDIOTECA_VOZ={nombre}-clon en .env)")
    return 0


def base(desde_macos: bool, semilla: int) -> int:
    """Voz genérica `qwen-clon`. Qwen3-TTS Base sin referencia inventa un hablante distinto en cada frase; para
    que un libro entero suene con la MISMA voz se genera una sola muestra (semilla fija) y se usa como referencia.
    Con --desde-macos la referencia es la voz de `say` y Qwen la vuelve más natural."""
    import numpy as np
    import soundfile as sf
    config.VOCES.mkdir(parents=True, exist_ok=True)
    wav, txt = config.VOCES / "qwen.wav", config.VOCES / "qwen.txt"
    if desde_macos:
        import narrar
        a = narrar.VozMacOS().decir(FRASE_BASE)
        sf.write(wav, a, narrar.VozMacOS.sr)
    else:
        import mlx.core as mx
        from mlx_audio.tts.utils import load_model
        print(f"cargando {config.MODELO_TTS} (la primera vez se descarga, ~1 GB)…", flush=True)
        m = load_model(config.MODELO_TTS)
        esperado = len(FRASE_BASE) / 14.5
        mejor = None
        for k in range(6):                                 # la muestra que dure lo esperado (sin bucles ni cortes)
            mx.random.seed(semilla + k)
            rs = list(m.generate(text=FRASE_BASE, lang_code="spanish", temperature=0.7, verbose=False,
                                 max_tokens=int(esperado * 12.5 * 2) + 40, split_pattern=""))
            a = np.concatenate([np.array(r.audio, dtype=np.float32) for r in rs]) if rs else np.zeros(1, np.float32)
            ratio = len(a) / m.sample_rate / esperado
            print(f"  muestra {k + 1}: {len(a) / m.sample_rate:.1f} s (ratio {ratio:.2f})", flush=True)
            if mejor is None or abs(np.log(max(ratio, 1e-3))) < abs(np.log(max(mejor[1], 1e-3))):
                mejor = (a, ratio)
            if 0.75 <= ratio <= 1.35:
                break
        a = mejor[0]
        pico = float(np.abs(a).max()) or 1.0
        sf.write(wav, (a / pico * 0.9).astype(np.float32), m.sample_rate)
    txt.write_text(FRASE_BASE + "\n", encoding="utf-8")
    print(f"voz «qwen-clon» lista: {wav} ({_duracion(wav):.1f} s)")
    print("  escúchala: afplay " + str(wav))
    print("  ¿no te gusta? vuelve a crearla con otra semilla: ./audioteca voz base --semilla 7")
    return 0


def probar(voz_id: str, texto: str) -> int:
    import soundfile as sf
    import narrar
    if voz_id not in narrar.voces_disponibles():
        sys.exit(f"la voz {voz_id} no existe; hay: {', '.join(sorted(narrar.voces_disponibles()))}")
    motor = narrar.Voces().para(voz_id)
    a = motor.decir(narrar.para_voz(texto))
    config.TRABAJO.mkdir(parents=True, exist_ok=True)
    salida = config.TRABAJO / f"prueba-{voz_id}.wav"
    sf.write(salida, a, motor.sr)
    print(f"{salida} ({len(a) / motor.sr:.1f} s) · escúchala: afplay {salida}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="orden", required=True)
    sub.add_parser("listar")
    b = sub.add_parser("base", help="crear la voz genérica qwen-clon")
    b.add_argument("--desde-macos", action="store_true", help="usar la voz de say como referencia (sin muestra de Qwen)")
    b.add_argument("--semilla", type=int, default=3)
    c = sub.add_parser("clonar", help="crear <nombre>-clon desde una grabación")
    c.add_argument("nombre")
    c.add_argument("audio", type=Path)
    c.add_argument("texto", help="transcripción exacta de la grabación")
    p = sub.add_parser("probar", help="narrar una frase con una voz")
    p.add_argument("voz")
    p.add_argument("texto", nargs="?", default="Había una vez un faro al final del puerto, y nadie recordaba quién lo encendía.")
    a = ap.parse_args()
    if a.orden == "listar":
        return listar()
    if a.orden == "base":
        return base(a.desde_macos, a.semilla)
    if a.orden == "clonar":
        return clonar(a.nombre, a.audio, a.texto)
    return probar(a.voz, a.texto)


if __name__ == "__main__":
    sys.exit(main())
