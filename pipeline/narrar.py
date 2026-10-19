#!/usr/bin/env python3
"""Narrador de la Audioteca: convierte texto/NN.md en audio/<voz>/NN.mp3 + audio/<voz>/NN.json.

    ./audioteca narrar                     # narra todo lo pendiente y termina
    ./audioteca narrar --libro mi-libro    # solo ese libro (en su voz o en --voz)
    ./audioteca narrar --vigilar           # se queda esperando libros nuevos (modo servicio)
    ./audioteca narrar --plan              # imprime la cola con su hora estimada de fin

Voces:
  · `macos`: la voz en español de `say` (sistema). Gratis, instantánea, sin descargar nada; suena robótica.
  · `<nombre>-clon`: Qwen3-TTS 0.6B Base (MLX 8 bit) clona la referencia `voces/<nombre>.wav` + `<nombre>.txt`
    (la transcripción exacta de ese audio). `./audioteca voz base` crea `qwen`, una voz genérica del propio
    modelo; `./audioteca voz clonar mi-voz grabacion.m4a "texto"` agrega la tuya.
Un libro puede tener varias narraciones, una por voz, y todas narran el MISMO texto, así que la app cambia
de voz conservando la oración. Cola = pares (libro, voz): `.trabajo/narrador/cola.json` «orden» admite
"slug" (voz de libro.json) o {"slug":…, "voces":[…]} (capítulo a capítulo, alternando voces); «excluidos»
y «pausas» (ventanas en las que no narra). `pedidos.json` (lo escribe la app cuando pides otra voz desde el
teléfono) adelanta el capítulo 1 como muestra y deja el resto al final. Cada trabajador reclama (voz,
capítulo) con un lock atómico (O_EXCL + pid). Cada segmento se cachea como wav en audio/.trabajo/NN/, así
que si el proceso cae, al volver reanuda en el segmento siguiente. mp3 + json se escriben tmp → rename y
después se marca libro.json (con flock: el traductor también lo edita). Formato: docs/FORMATO.md
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

LIBROS = config.LIBROS
VOCES = config.VOCES
MODELO = config.MODELO_TTS
FFMPEG = config.ffmpeg()
ESTADO = config.NARRADOR / "estado.json"
COLA = config.NARRADOR / "cola.json"      # orden, exclusiones y pausas; se relee en cada vuelta
PEDIDOS = COLA.with_name("pedidos.json")  # voces pedidas desde la app; se relee en cada vuelta
LISTOS = {"texto-listo", "narrando"}
NARRABLES = LISTOS | {"completo"}         # un libro completo en su voz aún puede narrarse en otra
VOZ_SISTEMA = config.VOZ_SISTEMA
VOZ_DEFECTO = config.VOZ_DEFECTO
VOZ_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")

MAX_SEG = 240          # caracteres por segmento (Qwen se pierde en trozos largos)
MIN_SEG = 70           # oraciones más cortas se unen a la siguiente
CPS = 14.5             # caracteres por segundo de una narración en español a ritmo normal (150 palabras ≈ 62 s)
PAUSA_FRASE = 0.28
PAUSA_PARRAFO = 0.65
PAUSA_TITULO = 1.1


def log(msg: str) -> None:
    linea = f"{datetime.now():%Y-%m-%d %H:%M:%S} [{os.getpid()}] {msg}"
    print(linea, flush=True)


# ----------------------------------------------------------------- texto → segmentos
def oraciones(p: str) -> list[str]:
    partes = re.split(r"(?<=[.!?…»\"”])\s+(?=[¡¿«\"“A-ZÁÉÍÓÚÑ0-9—-])", p)
    out: list[str] = []
    for s in partes:
        s = s.strip()
        while len(s) > MAX_SEG:                     # oración larguísima: cortar en , ; :
            cortes = [m.end() for m in re.finditer(r"[,;:]\s", s[:MAX_SEG])]
            c = cortes[-1] if cortes and cortes[-1] > 60 else s.rfind(" ", 0, MAX_SEG)
            out.append(s[:c].strip())
            s = s[c:].strip()
        if s:
            out.append(s)
    # unir las cortas
    juntas: list[str] = []
    for s in out:
        if juntas and (len(juntas[-1]) < MIN_SEG or len(s) < 25) and len(juntas[-1]) + 1 + len(s) <= MAX_SEG:
            juntas[-1] = f"{juntas[-1]} {s}"
        else:
            juntas.append(s)
    return juntas


def segmentos(md: str) -> list[dict]:
    """[{texto, pausa}] — el título primero; pausa = silencio después del segmento."""
    lineas = md.strip().split("\n\n")
    segs: list[dict] = []
    for i, bloque in enumerate(lineas):
        bloque = " ".join(bloque.split())
        if not bloque:
            continue
        if i == 0 and bloque.startswith("# "):
            segs.append({"texto": bloque[2:].strip(), "pausa": PAUSA_TITULO})
            continue
        ors = oraciones(bloque)
        for j, s in enumerate(ors):
            segs.append({"texto": s, "pausa": PAUSA_PARRAFO if j == len(ors) - 1 else PAUSA_FRASE})
    return segs


def para_voz(t: str) -> str:
    """Lo que oye Qwen (el json conserva el texto original para el resaltado)."""
    t = re.sub(r"([¡!¿?])\1+", r"\1", t)
    t = re.sub(r"\.{4,}", "...", t)
    t = t.replace("*", "").replace("“", "\"").replace("”", "\"")
    t = re.sub(r"(?<=\d)\s*—\s*", ". ", t)                    # «1— Rechazar» → «1. Rechazar»
    t = re.sub(r"\s*—\s*", ", ", t)
    # MAYÚSCULAS sostenidas → minúsculas con inicial (Qwen tiende a deletrear o gritar)
    def caps(m: re.Match) -> str:
        w = m.group(0)
        return w if len(w) <= 3 else w.capitalize()
    t = re.sub(r"\b[A-ZÁÉÍÓÚÑÜ]{2,}\b", caps, t)
    t = re.sub(r"\s+", " ", t).strip()
    if t and t[-1] not in ".!?…\"»":
        t += "."
    return t


# ----------------------------------------------------------------- libro.json con flock
class Libro:
    def __init__(self, slug: str):
        self.slug = slug
        self.dir = LIBROS / slug
        self.meta_path = self.dir / "libro.json"

    def leer(self) -> dict:
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def actualizar(self, fn) -> dict:
        lock = self.dir / ".libro.lock"
        with open(lock, "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            meta = self.leer()
            fn(meta)
            tmp = self.meta_path.with_name(f".libro.json.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.meta_path)
            return meta

    def voz(self, meta: dict | None = None) -> str:
        """Voz principal del libro (libro.json «voz»)."""
        v = str((meta if meta is not None else self.leer()).get("voz") or VOZ_DEFECTO)
        return v if VOZ_RE.match(v) else VOZ_DEFECTO

    def audio(self, n: int, voz: str) -> tuple[Path, Path] | None:
        """mp3 + json de la narración del capítulo n en esa voz."""
        d = self.dir / "audio" / voz
        a, j = d / f"{n:02d}.mp3", d / f"{n:02d}.json"
        if a.exists() and j.exists():
            return a, j
        return None

    def audio_listo(self, n: int, voz: str) -> bool:
        return self.audio(n, voz) is not None


def voces_disponibles() -> set[str]:
    """`macos` siempre; y cada referencia completa (wav + txt) en voces/: `<nombre>-clon`."""
    clones = {f"{w.stem}-clon" for w in VOCES.glob("*.wav") if (VOCES / f"{w.stem}.txt").exists()}
    return {VOZ_SISTEMA} | {v for v in clones if VOZ_RE.match(v)}


def leer_json(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def en_pausa() -> str | None:
    """Motivo si ahora cae dentro de una ventana de `pausas` de cola.json."""
    try:
        pausas = json.loads(COLA.read_text(encoding="utf-8")).get("pausas", [])
    except Exception:  # noqa: BLE001
        return None
    ahora = datetime.now()
    for v in pausas:
        try:
            if datetime.fromisoformat(v["desde"]) <= ahora < datetime.fromisoformat(v["hasta"]):
                return f"{v.get('por', 'pausa')} (hasta {v['hasta']})"
        except Exception:  # noqa: BLE001
            continue
    return None


SOLO: dict = {}          # --libro / --voz: limita la cola a ese libro (y esa voz)


def plan() -> list[tuple[str, str, int | None]]:
    """Cola en orden: [(slug, voz, solo_capitulo|None)]. Primero las muestras pedidas desde la app
    (capítulo 1 en la voz nueva), luego `orden` de cola.json (cada entrada con sus voces), luego los
    demás libros listos por antigüedad en su voz, y al final el resto de los libros pedidos."""
    if SOLO.get("libro"):
        slug = SOLO["libro"]
        if not (SLUG_RE.match(slug) and (LIBROS / slug / "libro.json").exists()):
            return []
        voz = SOLO.get("voz") or Libro(slug).voz()
        return [(slug, voz, None)] if voz in voces_disponibles() else []
    cola, pedidos = leer_json(COLA), leer_json(PEDIDOS).get("pedidos", [])
    fuera = set(cola.get("excluidos", []))
    hay = voces_disponibles()
    metas: dict[str, dict] = {}

    def meta(slug: str) -> dict | None:
        if slug not in metas:
            try:
                metas[slug] = Libro(slug).leer() if SLUG_RE.match(slug) and (LIBROS / slug / "libro.json").exists() else None
            except Exception:  # noqa: BLE001  (otro agente escribiendo: siguiente vuelta)
                metas[slug] = None
        return metas[slug]

    tareas: list[tuple[str, str, int | None]] = []
    vistos: set[tuple[str, str]] = set()

    def agregar(slug: str, voces: list[str], muestra: bool = False) -> None:
        m = meta(slug)
        if slug in fuera or not m or m.get("estado") not in NARRABLES:
            return
        voces = [v for v in voces if v in hay]
        if muestra:
            caps = [c["n"] for c in m.get("capitulos", []) if isinstance(c.get("n"), int)]
            for v in voces:
                if caps:
                    tareas.append((slug, v, min(caps)))
            return
        voces = [v for v in voces if (slug, v) not in vistos]
        if voces:
            vistos.update((slug, v) for v in voces)
            tareas.append((slug, "|".join(voces), None))

    validos = [p for p in pedidos if isinstance(p, dict) and isinstance(p.get("slug"), str) and isinstance(p.get("voz"), str)]
    for p in validos:
        agregar(p["slug"], [p["voz"]], muestra=True)
    for item in cola.get("orden", []):
        if isinstance(item, str):
            m = meta(item)
            if m:
                agregar(item, [Libro(item).voz(m)])
        elif isinstance(item, dict) and isinstance(item.get("slug"), str):
            m = meta(item["slug"])
            if m:
                voces = item.get("voces") if isinstance(item.get("voces"), list) else [Libro(item["slug"]).voz(m)]
                agregar(item["slug"], [str(v) for v in voces])
    resto = [p.parent.name for p in LIBROS.glob("*/libro.json")]
    resto.sort(key=lambda s: (LIBROS / s / "libro.json").stat().st_mtime)
    for s in resto:
        m = meta(s)
        if m and m.get("estado") in LISTOS:
            agregar(s, [Libro(s).voz(m)])
    for p in validos:
        agregar(p["slug"], [p["voz"]])
    return tareas


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}$")


def pid_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def reclamar(libro: Libro, voz: str, n: int) -> Path | None:
    lock = libro.dir / f"audio/.{voz}.{n:02d}.lock"
    lock.parent.mkdir(exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return lock
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or 0)
            except Exception:  # noqa: BLE001
                pid = 0
            if pid and pid_vivo(pid):
                return None
            lock.unlink(missing_ok=True)                 # lock huérfano de un proceso muerto
    return None


def siguiente() -> tuple[Libro, str, dict, Path] | None:
    for slug, voces, solo in plan():
        libro = Libro(slug)
        try:
            meta = libro.leer()
        except Exception:  # noqa: BLE001
            continue
        for cap in meta.get("capitulos", []):
            n = cap["n"]
            if solo is not None and n != solo:
                continue
            if not (libro.dir / cap["archivo_texto"]).exists():
                continue
            for voz in voces.split("|"):               # varias voces: capítulo a capítulo, alternando
                if libro.audio_listo(n, voz):
                    if voz == libro.voz(meta) and not cap.get("archivo_audio", "").startswith(f"audio/{voz}/"):
                        sincronizar(libro)            # autocuración si el traductor reescribió libro.json
                    continue
                lock = reclamar(libro, voz, n)
                if lock:
                    return libro, voz, cap, lock
    return None


def sincronizar(libro: Libro) -> None:
    """libro.json refleja la voz principal: archivo_audio/duracion_s de esa voz y el estado del libro."""
    def fn(meta):
        voz = libro.voz(meta)
        todos = True
        for c in meta.get("capitulos", []):
            par = libro.audio(c["n"], voz)
            if par:
                c["archivo_audio"] = str(par[0].relative_to(libro.dir))
                try:
                    c["duracion_s"] = json.loads(par[1].read_text())["duracion_s"]
                except Exception:  # noqa: BLE001
                    pass
            else:
                c.pop("archivo_audio", None)
                todos = False
        if meta.get("capitulos") and todos and meta.get("estado") in LISTOS:
            meta["estado"] = "completo"
        elif meta.get("estado") == "texto-listo" and any(c.get("archivo_audio") for c in meta.get("capitulos", [])):
            meta["estado"] = "narrando"
    libro.actualizar(fn)


# ----------------------------------------------------------------- motor
def voz_macos() -> str:
    """Voz de `say` en español: AUDIOTECA_VOZ_MACOS o la primera es_* instalada (Paulina, Mónica, Juan…)."""
    if config.VOZ_MACOS:
        return config.VOZ_MACOS
    try:
        lista = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=20).stdout
    except Exception:  # noqa: BLE001
        return "Paulina"
    voces = [re.split(r"\s{2,}", l.strip())[0] for l in lista.splitlines() if re.search(r"\bes_(MX|US|419|ES)\b", l)]
    for preferida in ("Paulina", "Mónica", "Juan"):
        if preferida in voces:
            return preferida
    return voces[0] if voces else "Paulina"


class VozMacOS:
    """`say` del sistema: sin modelo ni GPU. Ritmo AUDIOTECA_RITMO_MACOS (palabras por minuto, 180 por defecto)."""
    sr = 24000

    def __init__(self):
        self.nombre = VOZ_SISTEMA
        self.say = voz_macos()
        self.ritmo = config.valor("AUDIOTECA_RITMO_MACOS", "180")

    def decir(self, texto: str):
        import soundfile as sf
        import tempfile
        with tempfile.TemporaryDirectory(prefix="audioteca-say-") as d:
            wav = Path(d) / "s.wav"
            subprocess.run(["say", "-v", self.say, "-r", self.ritmo, "--file-format=WAVE",
                            f"--data-format=LEI16@{self.sr}", "-o", str(wav), texto], check=True, timeout=300)
            a, _ = sf.read(wav, dtype="float32")
        if a.ndim > 1:
            a = a.mean(axis=1)
        return recortar(a, self.sr)


class VozQwen:
    """Qwen3-TTS Base en MLX: clon zero-shot de una referencia `voces/<nombre>.wav` + `.txt`."""

    def __init__(self):
        import mlx.core as mx
        from mlx_audio.tts.utils import load_model
        from mlx_audio.utils import load_audio
        # Sin tope, MLX guarda en caché buffers ya usados y macOS termina paginándolos a disco. Tope chico = se liberan.
        mx.set_cache_limit(256 * 1024 * 1024)
        t0 = time.time()
        self.m = load_model(MODELO)
        self.sr = self.m.sample_rate
        self._load_audio = load_audio
        self._refs: dict = {}
        self.nombre = ""
        log(f"modelo {MODELO} cargado en {time.time() - t0:.1f}s")

    def usar(self, nombre: str) -> None:
        if not ((VOCES / f"{nombre}.wav").exists() and (VOCES / f"{nombre}.txt").exists()):
            raise RuntimeError(f"la voz {nombre}-clon no tiene referencia (voces/{nombre}.wav + .txt)")
        if nombre not in self._refs:
            self._refs[nombre] = (self._load_audio(str(VOCES / f"{nombre}.wav"), sample_rate=self.sr),
                                  (VOCES / f"{nombre}.txt").read_text(encoding="utf-8").strip())
        self.ref, self.ref_text = self._refs[nombre]
        self.nombre = nombre

    def decir(self, texto: str):
        """Un segmento con guardia contra bucles y silencios: duración esperada por caracteres."""
        import mlx.core as mx
        import numpy as np
        esperado = max(1.2, len(texto) / CPS)
        tope = int(esperado * 12.5 * 2.2) + 40                         # 12.5 tokens/s del códec
        mejor = None
        for intento in range(3):
            mx.random.seed(int(hashlib.md5(f"{texto}{intento}".encode()).hexdigest()[:8], 16))
            rs = list(self.m.generate(text=texto, ref_audio=self.ref, ref_text=self.ref_text,
                                      lang_code="spanish", max_tokens=tope, verbose=False,
                                      temperature=0.8 if intento == 0 else 0.7))
            a = np.concatenate([np.array(r.audio, dtype=np.float32) for r in rs]) if rs else np.zeros(1, np.float32)
            dur = len(a) / self.sr
            ratio = dur / esperado
            if mejor is None or abs(np.log(max(ratio, 1e-3))) < abs(np.log(max(mejor[1], 1e-3))):
                mejor = (a, ratio)
            alto = 2.6 if len(texto) < 40 else 1.75          # frases cortas llevan respiración propia
            if 0.55 <= ratio <= alto:
                break
            log(f"  reintento {intento + 1}: {dur:.1f}s para {len(texto)} car (ratio {ratio:.2f})")
        mx.clear_cache()
        return recortar(mejor[0], self.sr)


class Voces:
    """Motores por voz, cargados solo cuando hacen falta (Qwen no se carga si todo va en `macos`)."""

    def __init__(self):
        self._macos: VozMacOS | None = None
        self._qwen: VozQwen | None = None

    def para(self, voz_id: str):
        if voz_id == VOZ_SISTEMA:
            self._macos = self._macos or VozMacOS()
            return self._macos
        if not voz_id.endswith("-clon"):
            raise RuntimeError(f"voz desconocida: {voz_id} (usa macos o <nombre>-clon)")
        self._qwen = self._qwen or VozQwen()
        self._qwen.usar(voz_id.removesuffix("-clon"))
        return self._qwen


def recortar(a, sr):
    """Quita silencio al inicio y al final (la pausa la pone el ensamblado)."""
    import numpy as np
    if a.size == 0:
        return a
    env = np.abs(a)
    umbral = max(0.01, env.max() * 0.02)
    idx = np.where(env > umbral)[0]
    if idx.size == 0:
        return a[:0]
    ini = max(0, idx[0] - int(0.03 * sr))
    fin = min(len(a), idx[-1] + int(0.08 * sr))
    return a[ini:fin]


class Pausa(Exception):
    pass


def clave_cache(voz_id: str, texto: str) -> str:
    return hashlib.md5(f"{voz_id}|{texto}".encode()).hexdigest()[:10]


def narrar_capitulo(voces: Voces, libro: Libro, cap: dict, solo_segundos: float | None = None,
                    destino: Path | None = None, voz_id: str | None = None,
                    al_avanzar=None) -> dict:
    import numpy as np
    import soundfile as sf
    n = cap["n"]
    voz_id = voz_id or libro.voz()
    voz = voces.para(voz_id)
    md = (libro.dir / cap["archivo_texto"]).read_text(encoding="utf-8")
    segs = segmentos(md)
    trabajo = (destino or libro.dir / "audio") / f".trabajo/{n:02d}"
    trabajo.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    hechos = 0
    audio_total = 0.0
    for i, s in enumerate(segs):
        wav = trabajo / f"{i:05d}-{clave_cache(voz_id, s['texto'])}.wav"
        if not wav.exists() and not solo_segundos and (motivo := en_pausa()):
            raise Pausa(motivo)                      # lo hecho queda en caché; se reanuda al terminar la pausa
        if not wav.exists():
            a = voz.decir(para_voz(s["texto"]))
            tmp = wav.with_suffix(".tmp.wav")
            sf.write(tmp, a, voz.sr)
            os.replace(tmp, wav)
            hechos += 1
            audio_total += len(a) / voz.sr
            if hechos % 20 == 0 or i + 1 == len(segs):
                dt = time.time() - t0
                log(f"  {libro.slug} cap {n:02d} [{voz_id}]: {i + 1}/{len(segs)} segmentos · "
                    f"{audio_total / dt:.2f}x tiempo real")
                if al_avanzar:
                    al_avanzar(i + 1, len(segs))
        if solo_segundos and time.time() - t0 >= solo_segundos:
            return {"segmentos": i + 1, "audio_s": audio_total, "computo_s": time.time() - t0}
    if solo_segundos:
        return {"segmentos": len(segs), "audio_s": audio_total, "computo_s": time.time() - t0}

    # ensamblar: segmentos + pausas → un wav → mp3; tiempos exactos por muestras
    piezas, salida, cursor = [], [], 0.0
    for i, s in enumerate(segs):
        a, sr = sf.read(trabajo / f"{i:05d}-{clave_cache(voz_id, s['texto'])}.wav", dtype="float32")
        dur = len(a) / sr
        salida.append({"i": i, "texto": s["texto"], "inicio": round(cursor, 2), "fin": round(cursor + dur, 2)})
        piezas.append(a)
        piezas.append(np.zeros(int(s["pausa"] * sr), dtype=np.float32))
        cursor += dur + int(s["pausa"] * sr) / sr
    total = np.concatenate([np.zeros(int(0.3 * sr), np.float32)] + piezas)
    for seg in salida:                                 # 0.3 s de entrada
        seg["inicio"] = round(seg["inicio"] + 0.3, 2)
        seg["fin"] = round(seg["fin"] + 0.3, 2)
    audio_dir = libro.dir / "audio" / voz_id
    audio_dir.mkdir(parents=True, exist_ok=True)
    wav_full = trabajo / f"completo-{voz_id}.wav"
    sf.write(wav_full, total, sr)
    mp3_tmp = audio_dir / f".{n:02d}.mp3.tmp"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(wav_full), "-ac", "1",
                    "-codec:a", "libmp3lame", "-b:a", "80k", "-f", "mp3", str(mp3_tmp)],
                   check=True, timeout=1800)
    duracion = round(len(total) / sr, 2)
    js_tmp = audio_dir / f".{n:02d}.json.tmp"
    js_tmp.write_text(json.dumps({"duracion_s": duracion, "voz": voz_id, "segmentos": salida},
                                 ensure_ascii=False), encoding="utf-8")
    os.replace(mp3_tmp, audio_dir / f"{n:02d}.mp3")
    os.replace(js_tmp, audio_dir / f"{n:02d}.json")
    wav_full.unlink(missing_ok=True)
    sincronizar(libro)
    dt = time.time() - t0
    return {"segmentos": len(segs), "audio_s": duracion, "computo_s": dt}


def guardar_estado(clave: str, datos: dict) -> None:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    lock = ESTADO.with_suffix(".lock")
    with open(lock, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            est = json.loads(ESTADO.read_text())
        except Exception:  # noqa: BLE001
            est = {}
        est[clave] = datos
        tmp = ESTADO.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(est, ensure_ascii=False, indent=2))
        os.replace(tmp, ESTADO)


def trabajador(idx: int, vigilar: bool = False) -> int:
    """Narra la cola. Sin --vigilar termina cuando no queda nada; con --vigilar espera libros nuevos."""
    if motivo := en_pausa():
        log(f"trabajador {idx}: en pausa: {motivo}")
        return 0
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # al matarlo por PID suelta su lock (finally)
    voces = Voces()
    hechos = 0
    while True:
        if motivo := en_pausa():
            log(f"trabajador {idx}: entra en pausa: {motivo}")
            return 0
        tarea = siguiente()
        if not tarea:
            guardar_estado(f"trabajador-{idx}", {"pid": os.getpid(), "estado": "esperando",
                                                 "desde": datetime.now().isoformat(timespec="seconds")})
            if not vigilar:
                log(f"trabajador {idx}: nada más por narrar ({hechos} capítulo(s) en esta vuelta)")
                return 0
            time.sleep(60)
            continue
        libro, voz_id, cap, lock = tarea
        log(f"trabajador {idx}: narrando {libro.slug} cap {cap['n']:02d} [{voz_id}] «{cap.get('titulo', '')}»")
        actual = {"pid": os.getpid(), "estado": "narrando", "libro": libro.slug, "voz": voz_id,
                  "capitulo": cap["n"], "desde": datetime.now().isoformat(timespec="seconds")}
        guardar_estado(f"trabajador-{idx}", actual)

        def avance(hechos: int, total: int, actual=actual) -> None:
            guardar_estado(f"trabajador-{idx}", {**actual, "segmentos": [hechos, total]})
        try:
            try:
                r = narrar_capitulo(voces, libro, cap, voz_id=voz_id, al_avanzar=avance)
            except Pausa as e:
                log(f"trabajador {idx}: pausa a mitad de {libro.slug} cap {cap['n']:02d}: {e}")
                return 0
            hechos += 1
            log(f"trabajador {idx}: listo {libro.slug} cap {cap['n']:02d} [{voz_id}]: {r['audio_s'] / 60:.1f} min de audio "
                f"en {r['computo_s'] / 60:.1f} min ({r['audio_s'] / max(r['computo_s'], 1):.2f}x)")
            guardar_estado(f"ultimo-{idx}", {"libro": libro.slug, "voz": voz_id, "capitulo": cap["n"], **r,
                                             "fin": datetime.now().isoformat(timespec="seconds")})
        except Exception as e:  # noqa: BLE001
            log(f"trabajador {idx}: ERROR en {libro.slug} cap {cap['n']:02d}: {type(e).__name__}: {e}")
            if "METAL" in str(e).upper():             # GPU en mal estado: salir y que el supervisor reviva limpio
                lock.unlink(missing_ok=True)
                time.sleep(20)
                sys.exit(3)
            if not vigilar:
                lock.unlink(missing_ok=True)
                return 1
            time.sleep(30)
        finally:
            lock.unlink(missing_ok=True)


def pendiente_s(libro: Libro, cap: dict, voz_id: str) -> float:
    """Segundos de audio que faltan por narrar de un capítulo en una voz (descuenta la caché de segmentos)."""
    if libro.audio_listo(cap["n"], voz_id):
        return 0.0
    try:
        segs = segmentos((libro.dir / cap["archivo_texto"]).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return 0.0
    trabajo = libro.dir / "audio" / f".trabajo/{cap['n']:02d}"
    falta = 0
    for i, sg in enumerate(segs):
        if not (trabajo / f"{i:05d}-{clave_cache(voz_id, sg['texto'])}.wav").exists():
            falta += len(sg["texto"])
    return falta / CPS


def imprimir_plan(procesos: int, ritmo: float) -> None:
    """Simula la cola (mismo orden que siguiente()) con `procesos` trabajadores a `ritmo`× tiempo real.
    No cuenta pausas: avisa si un fin cae dentro de una."""
    trabajos: list[tuple[str, str, int, float]] = []
    vistos: set[tuple[str, str, int]] = set()
    for slug, voces, solo in plan():
        libro = Libro(slug)
        for cap in libro.leer().get("capitulos", []):
            if (solo is not None and cap["n"] != solo) or not (libro.dir / cap["archivo_texto"]).exists():
                continue
            for v in voces.split("|"):
                if (slug, v, cap["n"]) in vistos:
                    continue
                vistos.add((slug, v, cap["n"]))
                falta = pendiente_s(libro, cap, v)
                if falta > 0:
                    trabajos.append((slug, v, cap["n"], falta))
    libres = [time.time()] * procesos
    fin_por: dict[tuple[str, str], float] = {}
    for slug, v, n, falta in trabajos:
        i = min(range(procesos), key=lambda k: libres[k])
        libres[i] += falta / ritmo
        fin_por[(slug, v)] = max(fin_por.get((slug, v), 0), libres[i])
    pausas = leer_json(COLA).get("pausas", [])
    for (slug, v), t in fin_por.items():
        aviso = ""
        for pz in pausas:
            try:
                if datetime.fromisoformat(pz["desde"]).timestamp() <= t:
                    aviso = f"  ⚠ cruza la pausa de {pz['desde']} (se recorre hasta {pz['hasta']})"
                    break
            except Exception:  # noqa: BLE001
                continue
        horas = sum(f for s2, v2, _, f in trabajos if (s2, v2) == (slug, v)) / 3600
        print(f"{slug:38} {v:14} {horas:5.1f} h de audio por narrar · termina ~{datetime.fromtimestamp(t):%a %d %H:%M}{aviso}")


def supervisor(procesos: int, vigilar: bool) -> int:
    """Lanza `procesos` trabajadores y revive al que cae con error. Con un solo proceso trabaja aquí mismo."""
    if procesos <= 1:
        return trabajador(0, vigilar)
    hijos: dict[int, subprocess.Popen] = {}
    terminados: set[int] = set()
    parar = False

    def salir(*_):
        nonlocal parar
        parar = True
        for p in hijos.values():
            p.terminate()
    signal.signal(signal.SIGTERM, salir)
    signal.signal(signal.SIGINT, salir)
    log(f"supervisor: {procesos} trabajadores")
    extra = ["--vigilar"] if vigilar else []
    while not parar and len(terminados) < procesos:
        if vigilar and (motivo := en_pausa()):
            if any(p.poll() is None for p in hijos.values()):
                log(f"supervisor: pausa ({motivo}); espero a que los trabajadores suelten")
            time.sleep(60)
            continue
        for i in range(procesos):
            if i in terminados:
                continue
            p = hijos.get(i)
            if p is not None and p.poll() == 0 and not vigilar:
                terminados.add(i)                  # sin --vigilar: terminó porque no hay más
                continue
            if p is None or p.poll() is not None:
                if p is not None:
                    log(f"supervisor: trabajador {i} salió con {p.returncode}; lo revivo")
                    time.sleep(5)
                hijos[i] = subprocess.Popen([sys.executable, __file__, "--trabajador", str(i), *extra])
                time.sleep(20)                        # escalonar la carga del modelo
        time.sleep(5)
    for p in hijos.values():
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Narrador local de la Audioteca")
    ap.add_argument("--procesos", type=int, default=int(config.valor("AUDIOTECA_PROCESOS", "1")),
                    help="trabajadores en paralelo (cada uno carga su modelo; 1 basta en la mayoría de Macs)")
    ap.add_argument("--vigilar", action="store_true", help="no terminar: esperar libros nuevos (modo servicio)")
    ap.add_argument("--libro", help="narrar solo este libro (slug)")
    ap.add_argument("--voz", help="con --libro: narrarlo en esta voz (macos, qwen-clon, mi-voz-clon…)")
    ap.add_argument("--trabajador", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--bench", nargs=2, metavar=("SLUG", "NN"), help="mide un trozo real sin escribir en la biblioteca")
    ap.add_argument("--segundos", type=float, default=120)
    ap.add_argument("--plan", action="store_true", help="imprime la cola con su hora estimada de fin")
    ap.add_argument("--ritmo", type=float, default=1.6, help="× tiempo real por trabajador para --plan")
    a = ap.parse_args()
    if a.libro:
        SOLO["libro"] = a.libro
        if a.voz:
            SOLO["voz"] = a.voz
            if a.voz not in voces_disponibles():
                sys.exit(f"la voz {a.voz} no existe; hay: {', '.join(sorted(voces_disponibles()))}")
    if a.bench:
        import tempfile
        libro = Libro(a.bench[0])
        cap = next(c for c in libro.leer()["capitulos"] if c["n"] == int(a.bench[1]))
        with tempfile.TemporaryDirectory(prefix="audioteca-bench-") as d:
            r = narrar_capitulo(Voces(), libro, cap, solo_segundos=a.segundos, destino=Path(d), voz_id=a.voz)
        print("BENCH " + json.dumps(r), flush=True)
        return 0
    if a.plan:
        imprimir_plan(max(1, a.procesos), a.ritmo)
        return 0
    if a.trabajador is not None:
        return trabajador(a.trabajador, a.vigilar)
    return supervisor(a.procesos, a.vigilar)


if __name__ == "__main__":
    sys.exit(main())
