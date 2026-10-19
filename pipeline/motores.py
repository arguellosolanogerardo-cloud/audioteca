"""Motores de traducción EN→ES 100 % locales (tu Mac con Apple Silicon, sin costo por uso).

Dos familias:
- NMT clásico en CTranslate2 (CPU, int8/float16): Opus-MT tc-big, NLLB-200, MADLAD-400.
  Traducen oración por oración; no aceptan glosario ni contexto. Opcionales: `uv pip install ctranslate2 transformers`.
- LLM en MLX (GPU de Apple): TranslateGemma y Gemma 4. Traducen el párrafo entero, reciben el párrafo
  anterior como contexto y el glosario como instrucción.

Uso: `m = cargar("gemma4-12b"); m.traducir(parrafo, contexto=[(en, es)], glosario=[(en, es)])`.
Los modelos viven en ~/.cache/huggingface (fuera del repo). Se descargan la primera vez que se usan
(`./audioteca modelos` los baja por adelantado). En pruebas ciegas EN→ES de libros de no ficción, Gemma 4 12B
fue el mejor equilibrio entre fidelidad, español natural y velocidad; el QAT es algo mejor y pesa más.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

CATALOGO = {
    # nombre corto: (familia, repo, extra)
    "opus-mt": ("ct2", "ooeoeo/opus-mt-tc-big-en-es-ct2-float16", {}),
    "nllb-1.3b": ("ct2", "OpenNMT/nllb-200-distilled-1.3B-ct2-int8", {"src": "eng_Latn", "tgt": "spa_Latn"}),
    "madlad-3b": ("ct2", "Nextcloud-AI/madlad400-3b-mt-ct2-int8", {"prefijo": "<2es> "}),
    "tgemma-4b": ("mlx-tg", "mlx-community/translategemma-4b-it-4bit", {}),
    "tgemma-12b": ("mlx-tg", "mlx-community/translategemma-12b-it-4bit", {}),
    "gemma4-12b": ("mlx-chat", "mlx-community/gemma-4-12B-it-4bit", {}),          # 4 bit puro, 6.8 GB
    "gemma4-12b-qat": ("mlx-chat", "mlx-community/gemma-4-12B-it-qat-4bit", {}),  # QAT 4/8 bit, 11 GB
}

_ORACION = re.compile(r"(?<=[.!?;:…])[”\"’)]*\s+(?=[“\"‘(A-Z0-9])")


def oraciones(p: str) -> list[str]:
    return [o for o in _ORACION.split(p) if o.strip()]


def ruta_local(repo: str) -> str:
    """Carpeta local del modelo; si aún no está en caché, lo descarga una sola vez."""
    from huggingface_hub import snapshot_download
    try:
        return snapshot_download(repo, local_files_only=True)
    except Exception:  # noqa: BLE001  (no está en caché)
        print(f"descargando {repo} (solo la primera vez; puede tardar varios minutos)…", flush=True)
        return snapshot_download(repo)


@dataclass
class Motor:
    nombre: str
    repo: str
    familia: str
    extra: dict = field(default_factory=dict)
    acepta_glosario: bool = False

    def traducir(self, texto: str, contexto=None, glosario=None, nota: str = "") -> str:
        raise NotImplementedError


class MotorCT2(Motor):
    def __init__(self, nombre, repo, extra, hilos: int):
        super().__init__(nombre, repo, "ct2", extra)
        import ctranslate2
        from transformers import AutoTokenizer
        d = ruta_local(repo)
        self.tok = AutoTokenizer.from_pretrained(d, src_lang=extra.get("src")) if "src" in extra \
            else AutoTokenizer.from_pretrained(d)
        self.tr = ctranslate2.Translator(d, device="cpu", compute_type="int8", inter_threads=1, intra_threads=hilos)

    def traducir(self, texto, contexto=None, glosario=None, nota=""):
        ors = oraciones(texto)
        pref = self.extra.get("prefijo", "")
        fuentes = [self.tok.convert_ids_to_tokens(self.tok.encode(pref + o)) for o in ors]
        tp = [[self.extra["tgt"]]] * len(ors) if "tgt" in self.extra else None
        res = self.tr.translate_batch(fuentes, target_prefix=tp, beam_size=4, max_batch_size=16,
                                      max_decoding_length=400, repetition_penalty=1.1,
                                      no_repeat_ngram_size=0)
        salida = []
        for r in res:
            toks = r.hypotheses[0]
            if "tgt" in self.extra and toks and toks[0] == self.extra["tgt"]:
                toks = toks[1:]
            salida.append(self.tok.decode(self.tok.convert_tokens_to_ids(toks), skip_special_tokens=True).strip())
        return " ".join(salida)


SISTEMA = (
    "Eres traductor literario profesional de inglés a español latinoamericano neutro (registro de México, "
    "sin vosotros ni modismos de España). Traduce el texto COMPLETO, oración por oración: no resumas, no omitas, "
    "no agregues ni expliques. Conserva la voz y el tono del autor, las cifras, los nombres propios y los saltos "
    "de párrafo. Los diálogos van entre comillas latinas «». Responde solo con la traducción."
)


class MotorMLX(Motor):
    def __init__(self, nombre, repo, familia, extra):
        super().__init__(nombre, repo, familia, extra, acepta_glosario=(familia == "mlx-chat"))
        import mlx.core as mx
        from mlx_lm import load
        self.mx = mx
        mx.set_cache_limit(512 * 1024 ** 2)     # no acaparar memoria unificada: el narrador puede compartir el chip
        self.modelo, self.tok = load(ruta_local(repo))

    def _prompt(self, texto, contexto, glosario, nota):
        if self.familia == "mlx-tg":
            msgs = [{"role": "user", "content": [{"type": "text", "source_lang_code": "en",
                                                   "target_lang_code": "es-MX", "text": texto}]}]
            return self.tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
        partes = []
        if glosario:
            partes.append("Glosario obligatorio (usa exactamente estas decisiones):\n" +
                          "\n".join(f"- {en} → {es}" for en, es in glosario))
        if contexto:
            partes.append("Contexto previo (ya traducido; NO lo vuelvas a traducir):\n" +
                          "\n".join(f"EN: {en}\nES: {es}" for en, es in contexto))
        if nota:
            partes.append(nota)
        partes.append("Traduce al español:\n\n" + texto)
        msgs = [{"role": "system", "content": SISTEMA}, {"role": "user", "content": "\n\n".join(partes)}]
        try:
            return self.tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False,
                                                enable_thinking=False)
        except TypeError:
            return self.tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)

    def traducir(self, texto, contexto=None, glosario=None, nota=""):
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler
        prompt = self._prompt(texto, contexto, glosario, nota)
        n_in = len(self.tok.encode(texto))
        out = generate(self.modelo, self.tok, prompt=prompt, max_tokens=int(n_in * 2.2) + 40,
                       sampler=make_sampler(temp=0.0), verbose=False)
        # Sin repetition_penalty: castiga el token de espacio y pega palabras («serpronto»).
        # Los bucles se detectan en calidad.py y se reintenta.
        out = re.sub(r"<[^>]{1,30}>", "", out).strip()          # restos de tokens de turno
        self.mx.clear_cache()
        return out


def cargar(nombre: str, hilos: int = 2) -> Motor:
    familia, repo, extra = CATALOGO[nombre]
    if familia == "ct2":
        return MotorCT2(nombre, repo, extra, hilos)
    return MotorMLX(nombre, repo, familia, extra)
