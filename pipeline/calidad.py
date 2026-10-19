"""Control de calidad automático de una traducción EN→ES.

Por párrafo (decide si se reintenta): sin traducir, bucle/repetición, proporción fuera de rango,
comentario del modelo, cifras perdidas. Por capítulo: proporción de palabras ES/EN (se espera
1.0-1.25 con LLM; < 0.9 sugiere omisión). Lo que no se arregla con reintento queda en el reporte.
"""
from __future__ import annotations

import re
from collections import Counter

STOP_EN = set("the and of to that is was for with as his her they this have from but not are were be "
              "which you she he it its their by had has would could there what when who will been them "
              "than then into these those our we your".split())
STOP_ES = set("el la los las de que y en un una es por con para no se su sus al lo del como más pero "
              "le ya o este esta fue ha muy sin sobre también me hasta hay donde quien desde todo nos "
              "durante todos uno les ni contra otros ese eso ante ellos e esto mí antes algunos qué".split())
META = re.compile(r"^(aquí (está|tienes)|traducción:|translation:|nota:|claro[,.!]|por supuesto)|^(EN|ES):"
                  r"|(proporciona|comparte|incluye|envía)(me)? el texto|no (has|hay) (incluido |proporcionado )?(ningún |el )?texto"
                  r"|texto (en inglés )?que (deseas|quieres) (que )?tradu",
                  re.IGNORECASE | re.MULTILINE)
NUM = re.compile(r"\d[\d,.]*")


def palabras(s: str) -> list[str]:
    return re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+", s)


def proporcion_ingles(s: str) -> float:
    w = [x.lower() for x in palabras(s)]
    if not w:
        return 0.0
    en = sum(x in STOP_EN for x in w)
    es = sum(x in STOP_ES for x in w)
    return en / max(1, en + es)


def repeticion(s: str, n: int = 5) -> tuple[str, int] | None:
    w = [x.lower() for x in palabras(s)]
    if len(w) < n * 3:
        return None
    c = Counter(tuple(w[i:i + n]) for i in range(len(w) - n + 1))
    frase, veces = c.most_common(1)[0]
    return (" ".join(frase), veces) if veces >= 3 else None


def cifras(s: str) -> Counter:
    return Counter(re.sub(r"[,.]", "", x) for x in NUM.findall(s) if len(re.sub(r"[,.]", "", x)) >= 2)


def revisar_parrafo(en: str, es: str) -> list[str]:
    """Problemas graves (justifican reintento). Lista vacía = aceptable."""
    p = []
    ne, ns = len(palabras(en)), len(palabras(es))
    if not es.strip():
        return ["vacío"]
    if es.strip() == en.strip() and ne > 3:
        p.append("sin traducir (idéntico al original)")
    elif ne >= 8 and proporcion_ingles(es) > 0.35:
        p.append(f"parece inglés ({proporcion_ingles(es):.0%} de palabras funcionales en inglés)")
    if ne >= 12:
        r = ns / ne
        if r < 0.7:
            p.append(f"muy corto ({r:.2f}× el original): posible omisión")
        elif r > 1.7:
            p.append(f"muy largo ({r:.2f}× el original): posible agregado o alucinación")
    rep = repeticion(es)
    if rep and not repeticion(en):
        p.append(f"repetición: «{rep[0]}» ×{rep[1]}")
    if META.search(es) and not META.search(en):
        p.append("comentario del modelo en la salida")
    faltan = cifras(en) - cifras(es)
    if faltan:
        p.append("cifras que no aparecen: " + ", ".join(sorted(faltan)))
    return p


def revisar_capitulo(pares: list[tuple[str, str]]) -> dict:
    ne = sum(len(palabras(a)) for a, _ in pares)
    ns = sum(len(palabras(b)) for _, b in pares)
    r = ns / ne if ne else 0
    estado = "ok" if 0.9 <= r <= 1.4 else ("omisión probable" if r < 0.9 else "inflado")
    return {"palabras_en": ne, "palabras_es": ns, "proporcion": round(r, 3), "estado": estado}
