"""Glosario determinista: término EN → decisión ES, leído de glosario.md (lista o tabla).

Formatos que entiende (biblioteca/<slug>/glosario.md o el que pases con --glosario):
  - **deep work** → «trabajo profundo» (*deep work*); ...      (varias entradas por línea)
  | Growth mindset | mentalidad de crecimiento (*growth mindset*) | nota |
«A / B» en ambos lados se expande en pares («Finite / infinite mindset» → «mentalidad finita / infinita»).

El motor recibe solo las entradas que aparecen en el párrafo. Después, de forma determinista:
  1. se verifica que la decisión ES esté en la salida (con flexión: plural y género);
  2. la primera aparición en el libro lleva «término (*original*)» (ver docs/FORMATO.md);
  3. lo que no se pudo aplicar va al reporte de calidad, nunca se inventa.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Entrada:
    en: str
    es: str
    original: str | None      # lo que va entre paréntesis la primera vez, si el glosario lo marca
    sensible: bool            # término con mayúsculas propias (Deep Work): se busca respetando caja

    def patron_en(self) -> re.Pattern:
        cuerpo = r"\s+".join(re.escape(p) for p in self.en.split())
        flags = 0 if self.sensible else re.IGNORECASE
        return re.compile(rf"(?<![\w-]){cuerpo}(?:s|es)?(?![\w-])", flags)

    def patron_es(self) -> re.Pattern:
        # cada palabra: raíz sin las dos últimas letras + cualquier terminación (rival digno ~ rivales dignos);
        # «movilizar / reunir» acepta cualquiera; las notas entre paréntesis no cuentan
        alternativas = []
        for alt in re.sub(r"\([^)]*\)", "", self.es).replace("*", "").split(" / "):
            partes = []
            palabras = sin_acentos(alt).split()
            if len(palabras) > 1 and palabras[0].lower() in ARTICULOS:     # «el juego infinito» ~ «un juego infinito»
                palabras = palabras[1:]
            for p in palabras:
                raiz = p if len(p) <= 4 else p[:max(4, len(p) - 2)]
                partes.append(re.escape(raiz) + r"\w*")
            if partes:
                alternativas.append(r"[\s,]+".join(partes))
        return re.compile(r"(?<!\w)(?:" + "|".join(alternativas) + ")", re.IGNORECASE)


ARTICULOS = {"el", "la", "los", "las", "un", "una", "unos", "unas", "lo"}


def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _limpia(s: str) -> str:
    s = re.sub(r"\(\*[^)]*\*\)", "", s)
    s = s.replace("**", "").replace("«", "").replace("»", "").replace("*", "").strip(" .;:")
    return re.sub(r"\s+", " ", s).strip()


def _expandir(en: str, es: str) -> list[tuple[str, str]]:
    a = [x.strip() for x in en.split(" / ")]
    b = [x.strip() for x in es.split(" / ")]
    if len(a) == 1 or len(a) != len(b):
        return [(en, es)]
    cola_en = a[-1].split()[1:]                 # «Finite / infinite mindset»: comparten «mindset»
    a = [x if len(x.split()) > 1 or not cola_en else " ".join([x] + cola_en) for x in a]
    cabeza_es = b[0].split()[:-1]               # «mentalidad finita / infinita»: comparten «mentalidad»
    b = [x if len(x.split()) > 1 or not cabeza_es else " ".join(cabeza_es + [x]) for x in b]
    return list(zip(a, b))


def leer(ruta: Path | str | None) -> list[Entrada]:
    if not ruta:
        return []
    texto = Path(ruta).read_text(encoding="utf-8")
    pares: list[tuple[str, str, str | None]] = []
    for linea in texto.splitlines():
        s = linea.strip()
        if s.startswith("|") and s.count("|") >= 3:
            cols = [c.strip() for c in s.strip("|").split("|")]
            if not cols[0] or set(cols[0]) <= set("-: ") or cols[0].lower() in ("original", "término", "termino"):
                continue
            m = re.search(r"\(\*([^)]*)\*\)", cols[1])
            pares.append((_limpia(cols[0]), _limpia(cols[1]), m.group(1) if m else None))
            continue
        for m in re.finditer(r"\*\*([^*]+)\*\*\s*→\s*«([^»]+)»\s*(\(\*([^)]*)\*\))?", s):
            pares.append((_limpia(m.group(1)), _limpia(m.group(2)), m.group(4)))
    entradas, vistos = [], set()
    for en, es, orig in pares:
        if not en or not es or "(" in en:
            continue
        for e1, s1 in _expandir(en, es):
            if e1.lower() in vistos:
                continue
            vistos.add(e1.lower())
            sensible = any(c.isupper() for c in e1) and e1 != e1.capitalize() or e1 in ("Why", "How", "What")
            o = orig if orig and len(_expandir(en, es)) == 1 else (e1 if orig else None)
            entradas.append(Entrada(e1, s1, o, sensible))
    # los términos largos primero: «deep work» antes que «work»
    return sorted(entradas, key=lambda e: -len(e.en))


def relevantes(entradas: list[Entrada], texto_en: str) -> list[Entrada]:
    return [e for e in entradas if e.patron_en().search(texto_en)]


def verificar(entradas: list[Entrada], texto_en: str, texto_es: str) -> list[Entrada]:
    """Entradas presentes en el original cuya decisión no aparece en la traducción."""
    plano = sin_acentos(texto_es)
    return [e for e in relevantes(entradas, texto_en) if not e.patron_es().search(plano)]


def marcar_primera_vez(entradas: list[Entrada], texto_en: str, texto_es: str, ya: set[str]) -> str:
    """Primera aparición en el libro: «decisión (*original*)». Modifica `ya` (términos ya presentados)."""
    for e in relevantes(entradas, texto_en):
        if e.en in ya or not e.original:
            continue
        # el original tal como lo escribe el autor en ESTE párrafo (caja y número), no como lo anotó el glosario
        orig = e.patron_en().search(texto_en).group(0) if e.original.lower() == e.en.lower() else e.original
        if f"(*{orig}*)" in texto_es or f"(*{e.original}*)" in texto_es:
            ya.add(e.en)
            continue
        plano = sin_acentos(texto_es)
        m = e.patron_es().search(plano)
        if not m:
            continue              # no se aplicó: lo reporta verificar(); se presenta en la siguiente aparición
        fin = m.end()             # sin_acentos conserva longitudes en texto precompuesto (NFC)
        texto_es = texto_es[:fin] + f" (*{orig}*)" + texto_es[fin:]
        ya.add(e.en)
    return texto_es
