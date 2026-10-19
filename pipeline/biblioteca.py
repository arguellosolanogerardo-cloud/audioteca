#!/usr/bin/env python3
"""Estado de la biblioteca: cada libro con su estado, su voz y cuántos capítulos tiene narrados en cada voz.

    ./audioteca estado
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402


def main() -> int:
    libros = sorted(p.parent for p in config.LIBROS.glob("*/libro.json"))
    if not libros:
        print(f"La biblioteca está vacía ({config.LIBROS}).")
        print("Agrega un libro:  ./audioteca libro mi-libro.pdf --slug mi-libro --titulo \"…\" --autor \"…\"")
        return 0
    try:
        estado = json.loads((config.NARRADOR / "estado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        estado = {}
    for d in libros:
        try:
            m = json.loads((d / "libro.json").read_text(encoding="utf-8"))
        except ValueError:
            print(f"{d.name}: libro.json ilegible (¿se está escribiendo?)")
            continue
        caps = m.get("capitulos", [])
        voces = sorted(v.name for v in (d / "audio").glob("*") if v.is_dir() and not v.name.startswith("."))
        partes = [f"{v}: {len(list((d / 'audio' / v).glob('*.mp3')))}/{len(caps)}" for v in voces]
        print(f"{d.name:32} {m.get('estado', '?'):20} voz {m.get('voz', '?'):14} · {' · '.join(partes) or 'sin narrar'}"
              f" · «{m.get('titulo', '')}»")
    for k, t in sorted(estado.items()):
        if k.startswith("trabajador-") and t.get("estado") == "narrando":
            seg = t.get("segmentos") or [0, 0]
            print(f"  ahora: {t.get('libro')} cap {t.get('capitulo')} [{t.get('voz')}] {seg[0]}/{seg[1]} segmentos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
