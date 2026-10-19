#!/usr/bin/env python3
"""Servidor local compatible con LibreTranslate, para reusar el traductor desde otras apps.

    ./audioteca servidor-traduccion [--puerto 5055] [--motor gemma4-12b]

Solo escucha en 127.0.0.1. No es un servicio: se enciende a mano y se apaga con Ctrl-C.
Endpoints (forma de LibreTranslate):
  POST /translate   {"q": "texto" | ["a", "b"], "source": "en", "target": "es", "format": "text"}
                    → {"translatedText": "..."}  (o lista si q es lista)
                    extra opcional: "glosario": {"growth mindset": "mentalidad de crecimiento", ...}
  GET  /languages   → [{"code": "en", ...}, {"code": "es", ...}]
  GET  /salud       → {"ok": true, "motor": "...", "cargado": bool}
El modelo se carga al primer pedido y atiende uno a la vez (la GPU no gana nada en paralelo).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calidad  # noqa: E402
import config  # noqa: E402
import motores  # noqa: E402

ESTADO = {"motor": None, "nombre": config.MOTOR_TRADUCCION, "lock": threading.Lock()}


def traducir_uno(texto: str, glosario: dict | None) -> str:
    if not texto.strip():
        return texto
    if ESTADO["motor"] is None:
        ESTADO["motor"] = motores.cargar(ESTADO["nombre"])
    m = ESTADO["motor"]
    pares = [(k, v) for k, v in (glosario or {}).items() if k.lower() in texto.lower()]
    salida = []
    for p in texto.split("\n\n"):                    # respeta párrafos
        if not p.strip():
            salida.append(p)
            continue
        es = m.traducir(p, glosario=pares)
        if calidad.revisar_parrafo(p, es):
            es2 = m.traducir(p, glosario=pares, nota="Traduce TODO el texto, fiel y completo.")
            if len(calidad.revisar_parrafo(p, es2)) < len(calidad.revisar_parrafo(p, es)):
                es = es2
        salida.append(es)
    return "\n\n".join(salida)


class Manejador(BaseHTTPRequestHandler):
    def _json(self, codigo: int, cuerpo) -> None:
        datos = json.dumps(cuerpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        if self.path.startswith("/languages"):
            return self._json(200, [{"code": "en", "name": "English", "targets": ["es"]},
                                    {"code": "es", "name": "Spanish", "targets": []}])
        if self.path.startswith("/salud"):
            return self._json(200, {"ok": True, "motor": ESTADO["nombre"], "cargado": ESTADO["motor"] is not None})
        self._json(404, {"error": "no existe"})

    def do_POST(self):
        if not self.path.startswith("/translate"):
            return self._json(404, {"error": "no existe"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            crudo = self.rfile.read(n).decode()
            if "json" in (self.headers.get("Content-Type") or ""):
                d = json.loads(crudo or "{}")
            else:                                    # LibreTranslate también acepta formulario
                from urllib.parse import parse_qs
                d = {k: v[0] for k, v in parse_qs(crudo).items()}
        except Exception as e:
            return self._json(400, {"error": f"cuerpo inválido: {e}"})
        if d.get("source", "en") not in ("en", "auto") or d.get("target", "es") != "es":
            return self._json(400, {"error": "este traductor solo hace en → es"})
        if d.get("format", "text") != "text":
            return self._json(400, {"error": "solo format=text"})
        q = d.get("q")
        if q is None:
            return self._json(400, {"error": "falta q"})
        with ESTADO["lock"]:
            try:
                if isinstance(q, list):
                    res = [traducir_uno(str(x), d.get("glosario")) for x in q]
                else:
                    res = traducir_uno(str(q), d.get("glosario"))
            except Exception as e:
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        self._json(200, {"translatedText": res})

    def log_message(self, fmt, *args):
        sys.stderr.write("servidor: " + fmt % args + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=5055)
    ap.add_argument("--motor", default=config.MOTOR_TRADUCCION, choices=sorted(motores.CATALOGO))
    a = ap.parse_args()
    ESTADO["nombre"] = a.motor
    os.nice(10)
    srv = ThreadingHTTPServer(("127.0.0.1", a.puerto), Manejador)
    print(f"traductor local en http://127.0.0.1:{a.puerto}/translate · motor {a.motor}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
