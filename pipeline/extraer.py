#!/usr/bin/env python3
"""Extractor de libros (PDF, EPUB, TXT o Markdown) a capítulos limpios.

    python extraer.py <libro.pdf|epub|txt|md> --slug mi-libro --ver          # solo mostrar capítulos
    python extraer.py <libro.pdf|epub|txt|md> --slug mi-libro --titulo "…" --autor "…"

Sin --ver escribe el libro en español directamente en la biblioteca (`texto/NN.md` + `libro.json`
con `estado: texto-listo`) y el narrador lo toma solo. Para libros en inglés usa `traducir.py`, que
llama a este mismo extractor y traduce cada capítulo.

- PDF: `pdftotext -layout`; quita cabeceras/pies repetidos y números de página, une palabras partidas,
  repara capitulares («I t’s» → «It’s») y rehace párrafos. Capítulos por el índice del PDF (outline),
  por encabezados del texto o por un spec manual (`--capitulos spec.json`: [["Título", pág_ini, pág_fin], …]).
- EPUB: recorre cada documento del spine y cada bloque (p, div, li, blockquote, h1-h3) es un párrafo,
  aunque el EPUB use <div> en vez de <p> o mezcle texto suelto con subtítulos dentro del mismo <div>.
  Abre capítulo el nivel de encabezado que da más capítulos reales.
- TXT/MD: párrafos separados por línea en blanco; capítulos por «# Título», «CAPÍTULO 3», «Chapter 3»
  o encabezados en MAYÚSCULAS. Respeta el inicio/fin de los textos de Project Gutenberg.
Fuera: portada, copyright, índice, notas, «Sobre el autor» y similares (en inglés y en español).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

PRELIMINARES = re.compile(
    r"^(cover|title page|title|copyright|dedication|contents|table of contents|epigraph|also by|"
    r"books by|praise|about the (author|publisher)|notes|index|endnotes|bibliography|newsletter|"
    r"sign up|newsletter sign-?up|credits|permissions|photo credits|footnotes|imprint|half title|"
    r"portada|portadilla|créditos|índice|contenido|tabla de contenido|dedicatoria|epígrafe|"
    r"(sobre|acerca de)l? (el )?autor|notas|bibliografía|otros libros|agradecimientos)\b",
    re.IGNORECASE)
GUTENBERG = re.compile(r"project gutenberg|gutenberg™|full license|before you distribute", re.IGNORECASE)
ENCABEZADO = re.compile(r"(chapter|part|book|cap[ií]tulo|parte|libro)\s+([\divxlc]+|[a-záéíóú]+)\b", re.IGNORECASE)
URL = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def palabras(s: str) -> int:
    return len(re.findall(r"\w+", s))


# ============================================================ limpieza de párrafos
_DICC: set[str] | None = None
COMUNES_ES = set("a al de del el en es la las le les lo los me mi mis no nos se si sí su sus te tu tú un una uno y ya yo "
                 "o u e ha he hay que qué con por sin ser ver vez fue era más muy dos".split())


def _capitular(p: str, idioma: str) -> str:
    """Letra capitular separada por el PDF: «I t’s», «O n the morning», «E l día» → «It’s», «On…», «El día».
    Solo se une si no es una palabra de una letra legítima («I think», «A man», «Y luego», «O sea»)."""
    global _DICC
    m = re.match(r"^([“\"‘«]?)([A-ZÁÉÍÓÚÑ]) ([a-záéíóúñ’']+)(.*)$", p, re.S)
    if not m:
        return p
    letra = m.group(2)
    if idioma == "es":
        # en español «A», «E», «O», «U», «Y» son palabras: se une solo si lo que sigue no es palabra corta común
        # («E l día» → «El día», «E ra» → «Era»; «Y luego», «A veces» se quedan)
        resto = m.group(3).lower()
        unir = letra not in "AEOUYÉÓ" or (len(resto) <= 3 and resto not in COMUNES_ES)
    elif letra not in "AI":                              # «W hat», «S am», «O ur»: una letra sola no es palabra
        unir = True
    else:                                                # «I f» sí, «I am» / «A man» no
        if _DICC is None:
            try:
                _DICC = {w.strip().lower() for w in open("/usr/share/dict/words", encoding="utf-8")}
            except OSError:
                _DICC = set()
        palabra = (letra + m.group(3)).lower()
        base = re.sub(r"[’'].*$", "", palabra)
        resto = re.sub(r"[’'].*$", "", m.group(3).lower())
        unir = base in _DICC and not (len(resto) >= 2 and resto in _DICC)
    return m.group(1) + letra + m.group(3) + m.group(4) if unir else p


def limpiar_parrafo(p: str, idioma: str = "en") -> str:
    p = nfc(p).replace("\xad", "")
    p = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", p)               # _cursiva_ de Gutenberg
    p = re.sub(r"\[\d+\]|(?<!\d[.,])(?<=[a-záéíóúñ.,;”\"])\d{1,3}(?=\s|$)", "", p)  # llamadas a notas («50,000» y «1.5» no)
    p = re.sub(r"--", "—", p)
    p = re.sub(r"\s+", " ", p).strip()
    # primera palabra en versalitas («THIS little volume», «EN un lugar»): caja normal
    p = re.sub(r"^([«“\"]?)([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ’']+)(?=\s+[a-záéíóúñ])", lambda m: m.group(1) + m.group(2).capitalize(), p)
    return _capitular(p, idioma)


def _sin_titulo(ps: list[str], titulo: str) -> list[str]:
    """Quita los párrafos iniciales que solo repiten el título del capítulo («CHAPTER 1», «Capítulo uno»)."""
    t = set(re.findall(r"\w+", titulo.lower())) | {"chapter", "part", "capítulo", "capitulo", "parte"}
    while ps:
        w = set(re.findall(r"\w+", ps[0].lower()))
        if w and (w <= t or all(x.isdigit() or x in t for x in w)):
            ps = ps[1:]
            continue
        break
    return ps


def _quitar_promo(ps: list[str]) -> list[str]:
    """URLs sueltas y notas del traductor/editor no se leen en voz alta."""
    out = []
    for p in ps:
        if re.search(r"\(N\. de(l| la) [TE]\.\)\s*$", p):
            continue
        p = URL.sub("", p).strip()
        if p:
            out.append(p)
    return out


# ============================================================ PDF
def _parrafos_de_lineas(lineas: list[str], subtitulos: set[str]) -> list[str]:
    """Rehace párrafos desde líneas de `pdftotext -layout` (conservan la sangría)."""
    llenas = [l for l in lineas if l.strip()]
    if not llenas:
        return []
    sangrias = Counter(len(l) - len(l.lstrip()) for l in llenas)
    margen = sangrias.most_common(1)[0][0]
    anchos = sorted(len(l.strip()) for l in llenas)
    ancho = anchos[int(len(anchos) * 0.9)]
    out, cur, prev = [], "", ""
    for l in lineas:
        s = l.strip()
        if not s:
            if cur:
                out.append(cur)
                cur = ""
            prev = ""
            continue
        sangria = len(l) - len(l.lstrip())
        norm = re.sub(r"\s+", " ", s).lower()
        letras = [c for c in s if c.isalpha()]
        if norm in subtitulos or (len(letras) >= 4 and all(c.isupper() for c in letras) and len(s.split()) <= 12):
            if cur:
                out.append(cur)
            out.append(s)
            cur, prev = "", ""
            continue
        nuevo = bool(cur) and (sangria >= margen + 2 or
                               (len(prev) < ancho * 0.75 and re.search(r"[.!?:”\"’)»]$", prev)))
        if nuevo:
            out.append(cur)
            cur = ""
        if cur.endswith("-") and s[:1].islower() and not cur.endswith("--"):
            cur = cur[:-1] + s
        else:
            cur = f"{cur} {s}".strip()
        prev = s
    if cur:
        out.append(cur)
    # párrafo partido (capitular, salto de página): sin puntuación final y el siguiente empieza en minúscula
    unidos: list[str] = []
    for p in out:
        if unidos and p[:1].islower() and not re.search(r"[.!?:”\"’)…»]$", unidos[-1]):
            unidos[-1] = (unidos[-1][:-1] + p) if unidos[-1].endswith("-") else f"{unidos[-1]} {p}"
        else:
            unidos.append(p)
    return unidos


def _paginas_pdf(pdf: Path) -> list[list[str]]:
    out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"],
                         capture_output=True, text=True, check=True).stdout
    return [p.splitlines() for p in out.split("\f")]


def _quitar_cabeceras(paginas: list[list[str]]) -> list[list[str]]:
    """Cabeceras/pies repetidos (título del libro, autor) y números de página."""
    def clave(l):
        return re.sub(r"\d+", "#", re.sub(r"\s+", " ", l.strip().lower()))
    extremos: Counter = Counter()
    for p in paginas:
        llenas = [l for l in p if l.strip()]
        for l in llenas[:2] + llenas[-2:]:
            extremos[clave(l)] += 1
    repetidas = {k for k, v in extremos.items() if v >= 4 and len(k) < 90}
    limpias = []
    for p in paginas:
        llenas_idx = [i for i, l in enumerate(p) if l.strip()]
        extremos_idx = set(llenas_idx[:2] + llenas_idx[-2:])
        nueva = []
        for i, l in enumerate(p):
            s = l.strip()
            if i in extremos_idx and (clave(l) in repetidas or re.fullmatch(r"[\divxlcIVXLC]{1,6}", s)):
                continue
            if re.fullmatch(r"\d{1,4}", s):
                continue
            if re.search(r"\.{5,}\s*\d+\s*$", s):          # renglón de índice con puntos
                continue
            nueva.append(l)
        limpias.append(nueva)
    return limpias


def _outline(pdf: Path):
    try:
        from pypdf import PdfReader
        r = PdfReader(str(pdf))
        tops, subs = [], {}
        for x in r.outline:
            if isinstance(x, list):
                for y in x:
                    if not isinstance(y, list) and tops:
                        subs.setdefault(tops[-1][0], []).append(y.title.strip())
                continue
            tops.append((x.title.strip(), r.get_destination_page_number(x)))
        return tops, subs, len(r.pages)
    except Exception:  # noqa: BLE001  (PDF sin índice o pypdf ausente)
        return [], {}, 0


def _capitulos_por_encabezados(ps: list[str], minimo: int = 80) -> list[dict]:
    """Texto sin índice: un encabezado es un párrafo corto sin puntuación final, en MAYÚSCULAS,
    «Chapter N» / «Capítulo N» o «# Título». Encabezados sin cuerpo (el índice del libro) se descartan."""
    def es_enc(p):
        if p.startswith("# "):
            return True
        letras = [c for c in p if c.isalpha()]
        return (palabras(p) <= 12 and not re.search(r"[.,;:]$", p) and letras and
                (all(c.isupper() for c in letras) or ENCABEZADO.match(p)))
    caps, actual = [], None
    for p in ps:
        if es_enc(p):
            if actual and palabras(" ".join(actual["parrafos"])) >= minimo:
                caps.append(actual)
            t = p[2:].strip() if p.startswith("# ") else p.strip()
            actual = {"titulo": t.title() if t.isupper() else t, "parrafos": []}
        elif actual is not None:
            actual["parrafos"].append(p)
    if actual and palabras(" ".join(actual["parrafos"])) >= minimo:
        caps.append(actual)
    return [c for c in caps if not GUTENBERG.search(c["titulo"]) and not PRELIMINARES.match(c["titulo"])]


def _extraer_pdf(ruta: Path, spec: Path | None, idioma: str) -> list[dict]:
    paginas = _quitar_cabeceras(_paginas_pdf(ruta))
    planas = ["\n".join(p) for p in paginas]
    ini = next((k for k, p in enumerate(planas) if "*** START OF" in p), None)
    fin = next((k for k, p in enumerate(planas) if "*** END OF" in p), None)
    if ini is not None and fin is not None:           # Project Gutenberg impreso a PDF
        paginas = [paginas[ini][[i for i, l in enumerate(paginas[ini]) if "*** START OF" in l][0] + 1:]] + \
            paginas[ini + 1:fin] + [paginas[fin][:[i for i, l in enumerate(paginas[fin]) if "*** END OF" in l][0]]]
    limpiar = lambda ps: [x for x in (limpiar_parrafo(p, idioma) for p in ps) if x]  # noqa: E731
    if spec:
        plan = json.loads(spec.read_text(encoding="utf-8"))
        return [{"titulo": t, "parrafos": _sin_titulo(limpiar(_parrafos_de_lineas(sum(paginas[a - 1:b], []), set())), t)}
                for t, a, b in plan]
    tops, subs, n = _outline(ruta)
    if tops:
        caps = []
        for k, (titulo, ini) in enumerate(tops):
            fin = tops[k + 1][1] if k + 1 < len(tops) else n
            if PRELIMINARES.match(titulo):
                continue
            st = {re.sub(r"\s+", " ", s).lower() for s in subs.get(titulo, [])}
            ps = _sin_titulo(limpiar(_parrafos_de_lineas(sum(paginas[ini:fin], []), st)), titulo)
            if palabras(" ".join(ps)) >= 40:
                caps.append({"titulo": titulo, "parrafos": ps})
        if caps:
            return caps
    return _capitulos_por_encabezados(limpiar(_parrafos_de_lineas(sum(paginas, []), set())))


# ============================================================ EPUB
BLOQUES = {"p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "ul", "ol",
           "table", "tr", "td", "th", "figure", "figcaption", "aside", "header", "footer", "dd", "dt", "pre", "body",
           "hr", "nav"}
TITULOS = {"h1", "h2", "h3"}


def bloques_html(html: bytes | str, idioma: str = "en") -> list[tuple[str, str]]:
    """[(etiqueta, texto)] en orden de lectura. Recorre el árbol: el texto suelto se junta hasta el siguiente
    límite de bloque, así un <div> sin <p>, un <li> o un subtítulo metido a mitad de un <div> salen como
    párrafos propios. Etiqueta = h1/h2/h3 para títulos, «p» para todo lo demás."""
    from bs4 import BeautifulSoup, Comment, NavigableString, Tag
    sopa = BeautifulSoup(html, "html.parser")
    for x in sopa(["script", "style", "head", "title"]):
        x.decompose()
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def soltar(etiqueta: str) -> None:
        t = limpiar_parrafo(" ".join(buf), idioma)
        buf.clear()
        if t:
            out.append((etiqueta, t))

    def andar(nodo, etiqueta: str) -> None:
        for hijo in nodo.children:
            if isinstance(hijo, Comment):
                continue
            if isinstance(hijo, NavigableString):
                buf.append(str(hijo))
            elif isinstance(hijo, Tag):
                if hijo.name == "br":
                    buf.append(" ")
                elif hijo.name in BLOQUES:
                    soltar(etiqueta)                     # lo que venía antes es del bloque padre
                    propia = hijo.name if hijo.name in TITULOS else ("h3" if hijo.name in ("h4", "h5", "h6") else "p")
                    andar(hijo, propia)
                    soltar(propia)
                else:
                    andar(hijo, etiqueta)               # em, span, a, strong…: texto en línea
    cuerpo = sopa.body or sopa
    andar(cuerpo, "p")
    soltar("p")
    return out


def _extraer_epub(ruta: Path, idioma: str) -> list[dict]:
    """Capítulos por encabezados: el nivel más alto que se repite (h1, si no h2, si no h3) abre capítulo,
    aunque el EPUB guarde varios capítulos en un archivo o uno partido en varios."""
    import ebooklib
    from ebooklib import epub
    libro = epub.read_epub(str(ruta), options={"ignore_ncx": True})
    seq: list[tuple[str, str]] = []
    for idref, _ in libro.spine:
        item = libro.get_item_with_id(idref)
        if not item or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        seq += bloques_html(item.get_content(), idioma)

    def partir(nivel):
        caps, actual = [], None
        for tag, t in seq:
            if tag == nivel:
                actual = {"titulo": t.title() if t.isupper() else t, "parrafos": []}
                caps.append(actual)
            elif actual is not None and not (tag.startswith("h") and tag < nivel):
                actual["parrafos"].append(t)          # subtítulos de nivel menor: párrafo propio
        return [c for c in caps if palabras(" ".join(c["parrafos"])) >= 80 and not PRELIMINARES.match(c["titulo"])
                and not GUTENBERG.search(c["titulo"])]
    opciones = [partir(h) for h in ("h1", "h2", "h3")]
    mejor = max(opciones, key=len)               # el nivel que da más capítulos reales; empate → el más alto
    return mejor or [{"titulo": ruta.stem, "parrafos": [t for _, t in seq]}]


# ============================================================ TXT / MD
def _extraer_texto(ruta: Path, idioma: str) -> list[dict]:
    texto = ruta.read_text(encoding="utf-8-sig")
    if "*** START OF" in texto:                      # Project Gutenberg: fuera licencia y pie
        texto = texto.split("*** START OF", 1)[1].split("\n", 1)[1].split("*** END OF", 1)[0]
    bloques = [b for b in re.split(r"\n\s*\n", texto) if b.strip()]
    ps = []
    for b in bloques:
        b = b.strip()
        if b.startswith("# "):                       # Markdown: el título se queda tal cual
            ps.append("# " + re.sub(r"\s+", " ", b[2:]).strip())
        else:
            ps.append(limpiar_parrafo(b, idioma))
    ps = [p for p in ps if p]
    minimo = 20 if any(p.startswith("# ") for p in ps) else 80
    return _capitulos_por_encabezados(ps, minimo)


def extraer(ruta: Path, spec: Path | None = None, idioma: str = "en") -> list[dict]:
    """[{titulo, parrafos: [str]}] en orden. No modifica el archivo de entrada."""
    suf = ruta.suffix.lower()
    if suf == ".pdf":
        caps = _extraer_pdf(ruta, spec, idioma)
    elif suf == ".epub":
        caps = _extraer_epub(ruta, idioma)
    elif suf in (".txt", ".md", ".markdown"):
        caps = _extraer_texto(ruta, idioma)
    else:
        raise SystemExit(f"formato no soportado: {suf} (usa pdf, epub, txt o md)")
    for c in caps:
        c["parrafos"] = _quitar_promo(c["parrafos"])
    return [c for c in caps if c["parrafos"]]


# ============================================================ escribir el libro
def escribir_atomico(ruta: Path, texto: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(f".{ruta.name}.{os.getpid()}.tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, ruta)


def actualizar_libro(dir_libro: Path, fn) -> dict:
    """libro.json con candado (el narrador y el traductor también lo editan) y escritura atómica."""
    dir_libro.mkdir(parents=True, exist_ok=True)
    meta_path = dir_libro / "libro.json"
    with open(dir_libro / ".libro.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        fn(meta)
        tmp = meta_path.with_name(f".libro.json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, meta_path)
        return meta


def capitulos_en_meta(meta: dict, titulos: list[str]) -> list[dict]:
    """Lista de capítulos para libro.json conservando el audio ya narrado de un capítulo que no cambió."""
    viejos = {c.get("n"): c for c in meta.get("capitulos", [])}
    nuevos = []
    for n, t in enumerate(titulos, 1):
        d = {"n": n, "titulo": t, "archivo_texto": f"texto/{n:02d}.md"}
        v = viejos.get(n)
        if v and v.get("titulo") == t:
            d.update({k: v[k] for k in v if k not in d})
        nuevos.append(d)
    return nuevos


def slug_valido(slug: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,120}", slug))


def mostrar(caps: list[dict]) -> None:
    for n, c in enumerate(caps, 1):
        print(f"  {n:02d} {c['titulo'][:60]:60s} {palabras(' '.join(c['parrafos'])):6,d} pal · «{(c['parrafos'] or [''])[0][:70]}»")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("entrada", type=Path, help="libro en pdf, epub, txt o md (no se modifica)")
    ap.add_argument("--slug", required=True, help="nombre de carpeta: minúsculas, números y guiones")
    ap.add_argument("--titulo")
    ap.add_argument("--autor", default="")
    ap.add_argument("--idioma", default="es", help="idioma del texto (es por defecto; para inglés usa traducir.py)")
    ap.add_argument("--capitulos", type=Path, help="PDF sin índice: spec [[título, pág_ini, pág_fin], …]")
    ap.add_argument("--ver", action="store_true", help="solo muestra los capítulos detectados; no escribe nada")
    ap.add_argument("--salida", type=Path, default=config.LIBROS, help="carpeta de libros")
    ap.add_argument("--voz", default=config.VOZ_DEFECTO, help="voz principal del libro (macos, qwen-clon, mi-voz-clon…)")
    a = ap.parse_args()
    if not slug_valido(a.slug):
        sys.exit("slug inválido: minúsculas, números y guiones")
    entrada = a.entrada.expanduser().resolve()
    if not entrada.exists():
        sys.exit(f"no existe {entrada}")
    caps = extraer(entrada, a.capitulos, a.idioma)
    if not caps:
        sys.exit("no encontré capítulos: revisa el archivo o usa --capitulos spec.json (PDF)")
    total = sum(palabras(" ".join(c["parrafos"])) for c in caps)
    print(f"{a.slug}: {len(caps)} capítulos, {total:,} palabras")
    mostrar(caps)
    if a.ver:
        return 0
    dir_libro = a.salida.expanduser().resolve() / a.slug
    for n, c in enumerate(caps, 1):
        escribir_atomico(dir_libro / "texto" / f"{n:02d}.md", f"# {c['titulo']}\n\n" + "\n\n".join(c["parrafos"]) + "\n")

    def fn(meta):
        meta["slug"] = a.slug
        meta["titulo"] = a.titulo or meta.get("titulo") or entrada.stem.replace("-", " ").replace("_", " ").title()
        if a.autor or "autor" not in meta:
            meta["autor"] = a.autor
        meta.setdefault("idioma_original", a.idioma)
        meta.setdefault("traducido", False)
        meta["fuente"] = entrada.name
        meta.setdefault("voz", a.voz)
        meta["capitulos"] = capitulos_en_meta(meta, [c["titulo"] for c in caps])
        if meta.get("estado") not in ("narrando", "completo"):
            meta["estado"] = "texto-listo"
    meta = actualizar_libro(dir_libro, fn)
    print(f"listo: {dir_libro} · estado {meta['estado']} · voz {meta['voz']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
