#!/usr/bin/env python3
"""Genera fabulas.epub y fabulas.pdf desde fabulas.txt, sin dependencias (solo la biblioteca estándar).

    python3 tests/fixtures/crear_fixtures.py

- EPUB: portada y página de copyright (el extractor debe saltarlas), cada fábula en su archivo con <h2>,
  párrafos en <div> (no <p>) y un <h3> metido a mitad de un <div> junto con texto suelto.
- PDF: una página de título y cada fábula partida en dos páginas, con cabecera repetida «Aesop's Fables»
  y número de página al pie (el extractor debe quitarlos) y renglones cortados como en un libro impreso.
"""
from __future__ import annotations

import re
import textwrap
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def fabulas() -> list[tuple[str, list[str]]]:
    bloques = [b.strip() for b in re.split(r"\n\s*\n", (AQUI / "fabulas.txt").read_text(encoding="utf-8")) if b.strip()]
    out: list[tuple[str, list[str]]] = []
    for b in bloques[2:]:                       # fuera título y traductor
        if b.isupper():
            out.append((b.title().replace("And The", "and the"), []))
        else:
            out[-1][1].append(" ".join(b.split()))
    return out


# ------------------------------------------------------------------ EPUB
def epub(destino: Path) -> None:
    fs = fabulas()
    docs = {
        "cover.xhtml": "<div class='cover'><h1>AESOP'S FABLES</h1><div>Translated by George Fyler Townsend</div></div>",
        "copyright.xhtml": "<h2>Copyright</h2><div>This text is in the public domain.</div>",
    }
    for k, (titulo, ps) in enumerate(fs, 1):
        cuerpo = [f"<h2 class='chapter'>{titulo}</h2>"]
        for i, p in enumerate(ps):
            if k == 2 and i == len(ps) - 1:      # moraleja: subtítulo dentro del mismo <div> que texto suelto
                cuerpo.append(f"<div class='body'><h3>Moral</h3>{p}</div>")
            else:
                cuerpo.append(f"<div class='body'><span>{p}</span></div>")
        docs[f"fable{k}.xhtml"] = "\n".join(cuerpo)
    xhtml = ("<?xml version='1.0' encoding='utf-8'?>\n<html xmlns='http://www.w3.org/1999/xhtml'><head><title>x</title>"
             "<style>.body{{text-indent:1em}}</style></head><body>{}</body></html>")
    manifest = "".join(f"<item id='{n[:-6]}' href='{n}' media-type='application/xhtml+xml'/>" for n in docs)
    spine = "".join(f"<itemref idref='{n[:-6]}'/>" for n in docs)
    opf = ("<?xml version='1.0' encoding='utf-8'?><package xmlns='http://www.idpf.org/2007/opf' version='3.0' unique-identifier='id'>"
           "<metadata xmlns:dc='http://purl.org/dc/elements/1.1/'><dc:identifier id='id'>audioteca-fixture-fabulas</dc:identifier>"
           "<dc:title>Aesop's Fables</dc:title><dc:creator>Aesop</dc:creator><dc:language>en</dc:language>"
           "<meta property='dcterms:modified'>2026-01-01T00:00:00Z</meta></metadata>"
           f"<manifest><item id='nav' href='nav.xhtml' media-type='application/xhtml+xml' properties='nav'/>{manifest}</manifest>"
           f"<spine>{spine}</spine></package>")
    nav = xhtml.format("<nav xmlns:epub='http://www.idpf.org/2007/ops' epub:type='toc'><ol>"
                       + "".join(f"<li><a href='fable{k}.xhtml'>{t}</a></li>" for k, (t, _) in enumerate(fs, 1)) + "</ol></nav>")
    contenedor = ("<?xml version='1.0'?><container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>"
                  "<rootfiles><rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/></rootfiles></container>")
    with zipfile.ZipFile(destino, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype", (2026, 1, 1, 0, 0, 0)), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for nombre, datos in [("META-INF/container.xml", contenedor), ("OEBPS/content.opf", opf), ("OEBPS/nav.xhtml", nav)] + \
                [(f"OEBPS/{n}", xhtml.format(c)) for n, c in docs.items()]:
            z.writestr(zipfile.ZipInfo(nombre, (2026, 1, 1, 0, 0, 0)), datos, compress_type=zipfile.ZIP_DEFLATED)


# ------------------------------------------------------------------ PDF
def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf(destino: Path) -> None:
    fs = fabulas()
    paginas: list[list[tuple[float, float, float, str]]] = []   # (x, y, tamaño, texto)
    paginas.append([(180, 600, 24, "AESOP'S FABLES"), (175, 560, 12, "Translated by George Fyler Townsend")])
    num = 2
    for titulo, ps in fs:
        mitad = (len(ps) + 1) // 2
        for j, parte in enumerate((ps[:mitad], ps[mitad:])):
            renglones: list[tuple[float, float, float, str]] = [(72, 760, 9, "Aesop's Fables")]
            y = 720.0
            if j == 0:
                renglones.append((72, y, 14, titulo.upper()))
                y -= 34
            for p in parte:
                for i, linea in enumerate(textwrap.wrap(p, 78)):
                    renglones.append((90 if i == 0 else 72, y, 11, linea))   # sangría de primera línea
                    y -= 15
                y -= 6
            renglones.append((300, 40, 9, str(num)))
            num += 1
            paginas.append(renglones)
    objetos: list[bytes] = []

    def obj(cuerpo: bytes) -> int:
        objetos.append(cuerpo)
        return len(objetos)
    catalogo = obj(b"")            # se rellena al final
    raiz_paginas = obj(b"")
    fuente = obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman /Encoding /WinAnsiEncoding >>")
    hijos = []
    for renglones in paginas:
        flujo = "BT\n" + "".join(f"/F1 {t} Tf 1 0 0 1 {x} {y} Tm ({_esc(s)}) Tj\n" for x, y, t, s in renglones) + "ET\n"
        datos = flujo.encode("cp1252")
        contenido = obj(b"<< /Length %d >>\nstream\n" % len(datos) + datos + b"endstream")
        hijos.append(obj(f"<< /Type /Page /Parent {raiz_paginas} 0 R /MediaBox [0 0 612 792] "
                         f"/Resources << /Font << /F1 {fuente} 0 R >> >> /Contents {contenido} 0 R >>".encode()))
    objetos[catalogo - 1] = f"<< /Type /Catalog /Pages {raiz_paginas} 0 R >>".encode()
    objetos[raiz_paginas - 1] = f"<< /Type /Pages /Kids [{' '.join(f'{h} 0 R' for h in hijos)}] /Count {len(hijos)} >>".encode()
    salida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objetos, 1):
        offsets.append(len(salida))
        salida += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    salida += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root {catalogo} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    destino.write_bytes(bytes(salida))


if __name__ == "__main__":
    epub(AQUI / "fabulas.epub")
    pdf(AQUI / "fabulas.pdf")
    print("listos:", AQUI / "fabulas.epub", AQUI / "fabulas.pdf")
