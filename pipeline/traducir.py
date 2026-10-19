#!/usr/bin/env python3
"""Traductor local EN→ES de la Audioteca: libro (pdf|epub|txt|md) → biblioteca/<slug>/texto/NN.md + libro.json.

    ./audioteca traducir <archivo> --slug <slug> [--glosario ruta] [--motor gemma4-12b]
    ./audioteca traducir <archivo> --slug <slug> --solo-extraer     # revisar capítulos antes de traducir

100 % local en tu Mac (Apple Silicon), sin costo por uso. Motor por defecto: Gemma 4 12B 4 bit en MLX.

- Extrae con `extraer.py` (PDF por outline o encabezados, EPUB por bloques, TXT/MD), o con un spec manual
  (`--capitulos spec.json`: [["Título", pag_ini, pag_fin], ...]).
- Traduce párrafo a párrafo con el párrafo anterior como contexto y el glosario como instrucción;
  el glosario se verifica y la primera aparición de cada concepto lleva «término (*original*)».
- Reanudable e idempotente: cada párrafo traducido queda en .trabajo/traductor/<slug>/cache.jsonl; si el proceso cae,
  al volver salta lo hecho. Volver a correrlo con lo mismo produce lo mismo.
- Prioridad baja (taskpolicy -b + nice) y, si el narrador está activo, ciclo de trabajo 50 %: deja
  huecos de GPU para que la narración no se caiga (medido: sin pausas la frena ~45 %).
- Calidad: proporción ES/EN por capítulo, párrafos sin traducir, repeticiones, cifras y glosario;
  reporte en biblioteca/<slug>/calidad-traduccion.md. `estado: texto-listo` solo si pasa (o con --forzar-listo).
Formato de un libro: docs/FORMATO.md
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import calidad  # noqa: E402
import config  # noqa: E402
import glosario as G  # noqa: E402
from extraer import (actualizar_libro, capitulos_en_meta, escribir_atomico, extraer, mostrar,  # noqa: E402
                     nfc, palabras as _palabras, slug_valido)

LIBROS = config.LIBROS
TRABAJO = config.TRADUCTOR
ESTADO_NARRADOR = config.NARRADOR / "estado.json"
MAX_PAL = 200          # párrafos más largos se parten por oraciones (el modelo es más fiel en trozos cortos)

def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def trocear(p: str) -> list[str]:
    if _palabras(p) <= MAX_PAL:
        return [p]
    from motores import oraciones
    trozos, cur = [], ""
    for o in oraciones(p):
        if cur and _palabras(cur + " " + o) > MAX_PAL * 0.75:
            trozos.append(cur)
            cur = o
        else:
            cur = f"{cur} {o}".strip()
    if cur:
        trozos.append(cur)
    return trozos


# ============================================================ cortesía con el narrador
def narrador_activo() -> bool:
    try:
        est = json.loads(ESTADO_NARRADOR.read_text())
    except Exception:
        return False
    for v in est.values():
        if isinstance(v, dict) and v.get("estado") == "narrando" and v.get("pid"):
            try:
                os.kill(int(v["pid"]), 0)
                return True
            except (OSError, ValueError):
                pass
    return False


def baja_prioridad() -> None:
    """Se relanza bajo `taskpolicy -b` (QoS de fondo: CPU, disco y GPU ceden a todo lo demás) + nice 15."""
    if os.environ.get("TRADUCTOR_FONDO") == "1":
        return
    os.environ["TRADUCTOR_FONDO"] = "1"
    os.execvp("taskpolicy", ["taskpolicy", "-b", "nice", "-n", "15", sys.executable, *sys.argv])


# ============================================================ cache y libro.json
class Cache:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        self.d: dict[str, dict] = {}
        if ruta.exists():
            for l in ruta.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(l)
                    self.d[r["k"]] = r
                except Exception:
                    pass                    # última línea a medias si el proceso cayó: se rehace

    @staticmethod
    def clave(motor: str, en: str, glos: list) -> str:
        g = "|".join(f"{e.en}={e.es}" for e in glos)
        return hashlib.sha1(f"{motor}\n{g}\n{en}".encode()).hexdigest()[:20]

    def poner(self, k: str, r: dict) -> None:
        r = {"k": k, **r}
        self.d[k] = r
        with open(self.ruta, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


# ============================================================ traducción
class Traductor:
    def __init__(self, motor: str, entradas: list, cache: Cache, ciclo: float, hilos: int):
        self.nombre = motor
        self.entradas = entradas
        self.cache = cache
        self.ciclo = ciclo
        self.hilos = hilos
        self._m = None
        self.t_modelo = 0.0
        self.pal_modelo = 0

    @property
    def m(self):
        if self._m is None:
            import motores
            t = time.time()
            self._m = motores.cargar(self.nombre, hilos=self.hilos)
            log(f"motor {self.nombre} cargado en {time.time() - t:.1f}s")
        return self._m

    def _una(self, en, contexto, glos, nota=""):
        t = time.time()
        es = nfc(self.m.traducir(en, contexto=contexto, glosario=[(e.en, e.es) for e in glos], nota=nota))
        dt = time.time() - t
        self.t_modelo += dt
        self.pal_modelo += _palabras(en)
        if self.ciclo < 1:
            ciclo = self.ciclo if narrador_activo() else 1.0
            if ciclo < 1:
                time.sleep(dt * (1 - ciclo) / ciclo)
        return es

    def traducir(self, en: str, contexto=None) -> dict:
        if not re.search(r"[^\W\d_]", en):      # «. . .», «* * *», cifras sueltas: no hay nada que traducir
            return {"es": en, "problemas": [], "glosario_falta": [], "intentos": 0, "s": 0.0}
        glos = G.relevantes(self.entradas, en)
        k = Cache.clave(self.nombre, en, glos)
        if k in self.cache.d:
            return self.cache.d[k]
        t_ini = self.t_modelo
        es = self._una(en, contexto, glos)
        problemas = calidad.revisar_parrafo(en, es)
        faltan = [e for e in G.verificar(self.entradas, en, es) if e.original]
        intentos = 1
        if problemas or faltan:
            nota = "Atención, la traducción anterior falló:"
            if problemas:
                nota += " " + "; ".join(problemas) + "."
            if faltan:
                nota += " Usa obligatoriamente: " + "; ".join(f"«{e.en}» → «{e.es}»" for e in faltan) + "."
            nota += " Traduce TODO el texto, fiel y completo."
            es2 = self._una(en, None, glos, nota=nota)
            intentos = 2
            p2 = calidad.revisar_parrafo(en, es2)
            f2 = [e for e in G.verificar(self.entradas, en, es2) if e.original]
            if len(p2) + len(f2) < len(problemas) + len(faltan):
                es, problemas, faltan = es2, p2, f2
        r = {"es": es, "problemas": problemas, "glosario_falta": [e.en for e in faltan], "intentos": intentos,
             "s": round(self.t_modelo - t_ini, 2)}
        self.cache.poner(k, r)
        return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("entrada", type=Path, help="libro en pdf, epub, txt o md (no se modifica)")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--glosario", type=Path, help="glosario.md (por defecto libros/<slug>/glosario.md si existe)")
    ap.add_argument("--motor", default=config.MOTOR_TRADUCCION)
    ap.add_argument("--salida", type=Path, default=LIBROS, help="carpeta de libros (para probar: otra, así el narrador no la ve)")
    ap.add_argument("--capitulos", type=Path, help="spec manual: [[título, pág_ini, pág_fin], ...]")
    ap.add_argument("--solo-extraer", action="store_true", help="extrae y muestra capítulos; no traduce")
    ap.add_argument("--hasta", type=int, help="traduce solo hasta el capítulo N (prueba)")
    ap.add_argument("--ciclo", type=float, default=0.5,
                    help="fracción de tiempo usando el chip mientras el narrador está activo (1 = sin pausas)")
    ap.add_argument("--hilos", type=int, default=2, help="hilos de CPU (solo motores CTranslate2)")
    ap.add_argument("--forzar-listo", action="store_true", help="marca texto-listo aunque el control de calidad avise")
    ap.add_argument("--revisar-antes", action="store_true",
                    help="no marca texto-listo (el narrador no lo recoge) hasta que lo apruebes con --forzar-listo")
    ap.add_argument("--titulo", help="título en español para libro.json si no existe")
    ap.add_argument("--autor")
    a = ap.parse_args()

    if not slug_valido(a.slug):
        sys.exit("slug inválido: minúsculas, números y guiones")
    entrada = a.entrada.expanduser().resolve()
    if not entrada.exists():
        sys.exit(f"no existe {entrada}")
    if not a.solo_extraer:
        baja_prioridad()

    trabajo = TRABAJO / a.slug
    trabajo.mkdir(parents=True, exist_ok=True)
    candado = open(trabajo / ".lock", "w")
    try:
        fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(f"ya hay un traductor corriendo para {a.slug}")

    dir_libro = a.salida.expanduser().resolve() / a.slug
    glos_ruta = a.glosario or (dir_libro / "glosario.md" if (dir_libro / "glosario.md").exists() else None)
    entradas = G.leer(glos_ruta)

    fuente = trabajo / "fuente.json"
    firma = f"extraccion-v6:{entrada}:{entrada.stat().st_size}:{a.capitulos}"
    caps = None
    if fuente.exists():
        f = json.loads(fuente.read_text())
        if f.get("firma") == firma:
            caps = f["capitulos"]
    if caps is None:
        caps = extraer(entrada, a.capitulos, "en")
        escribir_atomico(fuente, json.dumps({"firma": firma, "capitulos": caps}, ensure_ascii=False, indent=1))
    if not caps:
        sys.exit("no encontré capítulos: usa --capitulos spec.json")
    total = sum(_palabras(" ".join(c["parrafos"])) for c in caps)
    log(f"{a.slug}: {len(caps)} capítulos, {total:,} palabras · glosario: {len(entradas)} términos · motor {a.motor}")
    if a.solo_extraer:
        mostrar(caps)
        print(f"fuente completa para revisar: {fuente}")
        return 0

    (dir_libro / "texto").mkdir(parents=True, exist_ok=True)
    cache = Cache(trabajo / "cache.jsonl")
    tr = Traductor(a.motor, entradas, cache, a.ciclo, a.hilos)
    hechos = sum(1 for c in caps for p in c["parrafos"] for t in trocear(p)
                 if Cache.clave(a.motor, t, G.relevantes(entradas, t)) in cache.d)
    pend_total = sum(len(trocear(p)) for c in caps for p in c["parrafos"]) - hechos
    if hechos:
        log(f"reanudo: {hechos} trozos ya traducidos en caché, faltan {pend_total}")

    t0 = time.time()
    presentados: set[str] = set()       # glosario: términos ya presentados con su original (orden del libro)
    reporte_caps, sospechas = [], []
    limite = a.hasta or len(caps)
    for n, cap in enumerate(caps[:limite], 1):
        titulo = tr.traducir(cap["titulo"])["es"].strip().strip("#*«»\"").strip()
        pares, prev, n_trozos = [], None, 0
        for i, p in enumerate(cap["parrafos"]):
            partes = []
            for t in trocear(p):
                r = tr.traducir(t, contexto=[prev] if prev else None)
                es = re.sub(r"\s*\n+\s*", " ", r["es"]).strip()
                partes.append(es)
                prev = (t, es)
                n_trozos += 1
                falta = [e.en for e in G.verificar(entradas, t, es) if e.original]   # se recalcula: el glosario puede cambiar
                if r["problemas"] or falta:
                    sospechas.append({"cap": n, "parrafo": i + 1, "en": t, "es": es,
                                      "problemas": r["problemas"] + [f"glosario: «{g}» no aplicado" for g in falta]})
            pares.append((p, " ".join(partes)))
            if tr.pal_modelo and n_trozos % 20 == 0:
                log(f"  cap {n:02d}: {i + 1}/{len(cap['en'])} párrafos · {tr.pal_modelo / tr.t_modelo * 60:.0f} pal/min de modelo")
        cuerpo = [G.marcar_primera_vez(entradas, en, es, presentados) for en, es in pares]
        qc = calidad.revisar_capitulo(pares)
        qc.update({"n": n, "titulo": titulo, "titulo_en": cap["titulo"]})
        reporte_caps.append(qc)
        md = f"# {titulo}\n\n" + "\n\n".join(cuerpo) + "\n"
        escribir_atomico(dir_libro / "texto" / f"{n:02d}.md", md)
        vel = f" · {tr.pal_modelo / tr.t_modelo * 60:.0f} pal/min de modelo" if tr.t_modelo else ""
        log(f"cap {n:02d} «{titulo}» listo: {qc['palabras_en']}→{qc['palabras_es']} pal ({qc['proporcion']}) {qc['estado']}{vel}")

    completos = limite == len(caps)
    graves = [s for s in sospechas if any(k in " ".join(s["problemas"]) for k in ("sin traducir", "inglés", "vacío", "omisión", "repetición"))]
    malos = [c for c in reporte_caps if c["estado"] != "ok"]
    aprobado = completos and not graves and not malos

    # reporte de calidad
    lineas = [f"# Calidad de la traducción · {a.slug}", "",
              f"{datetime.now():%Y-%m-%d %H:%M} · motor `{a.motor}` · glosario `{glos_ruta or '—'}` · "
              f"{'aprobado' if aprobado else 'REVISAR'}", "",
              "| Cap | Título | EN | ES | ES/EN | Estado |", "|---|---|---|---|---|---|"]
    for c in reporte_caps:
        lineas.append(f"| {c['n']:02d} | {c['titulo']} | {c['palabras_en']} | {c['palabras_es']} | {c['proporcion']} | {c['estado']} |")
    lineas += ["", f"## Frases sospechosas ({len(sospechas)}; graves: {len(graves)})", ""]
    for s in sospechas[:300]:
        lineas += [f"- **cap {s['cap']:02d} ¶{s['parrafo']}** · {'; '.join(s['problemas'])}",
                   f"  - EN: {s['en'][:400]}", f"  - ES: {s['es'][:400]}"]
    no_pres = [e.en for e in entradas if e.original and e.en not in presentados]
    if no_pres:
        lineas += ["", "## Glosario sin presentar (no aparecieron o el motor no usó la decisión)", "",
                   ", ".join(no_pres)]
    escribir_atomico(dir_libro / "calidad-traduccion.md", "\n".join(lineas) + "\n")

    def fn(meta):
        meta.setdefault("slug", a.slug)
        if a.titulo or "titulo" not in meta:
            meta["titulo"] = a.titulo or meta.get("titulo") or titulo_libro(caps, entrada)
        if a.autor:
            meta["autor"] = a.autor
        meta["idioma_original"] = "en"
        meta["traducido"] = True
        meta["motor"] = f"{a.motor} (local, pipeline/traducir.py)"
        meta["fuente"] = entrada.name
        meta.setdefault("voz", config.VOZ_DEFECTO)
        if glos_ruta and Path(glos_ruta).resolve().parent == dir_libro:
            meta["glosario"] = "glosario.md"
        meta["capitulos"] = capitulos_en_meta(meta, [c["titulo"] for c in reporte_caps])
        meta["traduccion"] = {"fecha": datetime.now().isoformat(timespec="seconds"), "capitulos": len(caps),
                              "aprobada": aprobado, "reporte": "calidad-traduccion.md"}
        if meta.get("estado") not in ("narrando", "completo"):
            listo = (aprobado and not a.revisar_antes) or (completos and a.forzar_listo)
            meta["estado"] = "texto-listo" if listo else "revision-traduccion"
    meta = actualizar_libro(dir_libro, fn)

    dur = time.time() - t0
    vel = f"{tr.pal_modelo / tr.t_modelo * 60:.0f} pal/min de modelo" if tr.t_modelo else "todo desde caché"
    log(f"fin: {len(reporte_caps)}/{len(caps)} capítulos en {dur / 60:.1f} min ({vel}) · estado {meta['estado']} · "
        f"sospechosas {len(sospechas)} (graves {len(graves)}) · reporte {dir_libro / 'calidad-traduccion.md'}")
    return 0


def titulo_libro(caps, entrada: Path) -> str:
    return entrada.stem.replace("-", " ").title()


if __name__ == "__main__":
    sys.exit(main())
