#!/usr/bin/env python3
"""Procesador universal de libros (PDF, TXT, EPUB) para Audioteca.
Extrae capítulos limpios, portada y genera la narración con sincronización por oraciones
utilizando Edge-TTS para Windows, macOS y Linux.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

# Importar configuración de Audioteca
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import config
    DIR_LIBROS = Path(config.LIBROS)
    DIR_TRABAJO = Path(config.TRABAJO)
except Exception:
    DIR_LIBROS = Path("biblioteca")
    DIR_TRABAJO = Path(".trabajo")

VOCES_EDGE = {
    "edge-co-salome": ("es-CO-SalomeNeural", "Salomé (Colombia - Femenina)"),
    "edge-co-gonzalo": ("es-CO-GonzaloNeural", "Gonzalo (Colombia - Masculina)"),
    "edge-es-alvaro": ("es-ES-AlvaroNeural", "Álvaro (España - Masculina)"),
    "edge-es-elvira": ("es-ES-ElviraNeural", "Elvira (España - Femenina)"),
    "edge-mx-dalia": ("es-MX-DaliaNeural", "Dalia (México - Femenina)"),
    "edge-mx-jorge": ("es-MX-JorgeNeural", "Jorge (México - Masculina)"),
    "edge-ar-elena": ("es-AR-ElenaNeural", "Elena (Argentina - Femenina)"),
    "edge-ar-tomas": ("es-AR-TomasNeural", "Tomás (Argentina - Masculina)"),
    "edge-cl-catalina": ("es-CL-CatalinaNeural", "Catalina (Chile - Femenina)"),
    "edge-cl-lorenzo": ("es-CL-LorenzoNeural", "Lorenzo (Chile - Masculina)"),
    "edge-pe-camila": ("es-PE-CamilaNeural", "Camila (Perú - Femenina)"),
    "edge-pe-alex": ("es-PE-AlexNeural", "Alex (Perú - Masculina)"),
    "edge-ve-paola": ("es-VE-PaolaNeural", "Paola (Venezuela - Femenina)"),
    "edge-ve-sebastian": ("es-VE-SebastianNeural", "Sebastián (Venezuela - Masculina)"),
    "edge-us-paloma": ("es-US-PalomaNeural", "Paloma (EE. UU. - Femenina)"),
    "edge-us-alonso": ("es-US-AlonsoNeural", "Alonso (EE. UU. - Masculina)"),
}

VOZ_DEFECTO = "edge-co-salome"


def reportar_progreso(
    tarea_id: str | None,
    etapa: str,
    pct: float,
    mensaje: str,
    extra: dict[str, Any] | None = None,
):
    datos = {
        "id": tarea_id or "",
        "etapa": etapa,
        "porcentaje": round(pct, 1),
        "mensaje": mensaje,
        **(extra or {}),
    }
    # Imprimir en stdout como línea JSON para procesos padre
    print(f"__PROGRESS__{json.dumps(datos, ensure_ascii=False)}", flush=True)

    # Si hay tarea_id, persistir en archivo de estado
    if tarea_id:
        dir_tareas = DIR_TRABAJO / "tareas"
        dir_tareas.mkdir(parents=True, exist_ok=True)
        ruta_tarea = dir_tareas / f"{tarea_id}.json"
        tmp_tarea = dir_tareas / f".{tarea_id}.json.tmp"
        try:
            contenido_json = json.dumps(datos, ensure_ascii=False, indent=2)
            tmp_tarea.write_text(contenido_json, encoding="utf-8")
            for _ in range(5):
                try:
                    os.replace(tmp_tarea, ruta_tarea)
                    break
                except OSError:
                    import time
                    time.sleep(0.04)
            else:
                ruta_tarea.write_text(contenido_json, encoding="utf-8")
        except Exception as e:
            pass


def limpiar_slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    s = re.sub(r"[-\s]+", "-", s)
    return s[:80] or "libro"


def extraer_portada(ruta_pdf: Path, destino_portada: Path):
    """Extrae la primera página como portada.jpg usando pypdfium2 y pillow si están disponibles."""
    try:
        import pypdfium2
        from PIL import Image

        doc = pypdfium2.PdfDocument(str(ruta_pdf))
        if len(doc) > 0:
            page = doc[0]
            pil_img = page.render(scale=1.5).to_pil()
            # Redimensionar si es muy grande manteniendo proporción
            max_w, max_h = 800, 1200
            pil_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            destino_portada.parent.mkdir(parents=True, exist_ok=True)
            pil_img.convert("RGB").save(str(destino_portada), "JPEG", quality=85)
            return True
    except Exception as e:
        print(f"No se pudo generar portada automática: {e}", file=sys.stderr)
    return False


def extraer_texto_pdf(ruta_pdf: Path) -> list[str]:
    """Extrae texto página por página."""
    paginas: list[str] = []

    # Intento 1: pypdf
    try:
        import pypdf

        reader = pypdf.PdfReader(str(ruta_pdf))
        for p in reader.pages:
            t = p.extract_text() or ""
            paginas.append(t)
        if any(len(p.strip()) > 50 for p in paginas):
            return paginas
    except Exception as e:
        print(f"Aviso pypdf: {e}", file=sys.stderr)

    # Intento 2: pdfplumber si pypdf falló
    try:
        import pdfplumber

        with pdfplumber.open(str(ruta_pdf)) as pdf:
            paginas = [p.extract_text() or "" for p in pdf.pages]
            if any(len(p.strip()) > 50 for p in paginas):
                return paginas
    except Exception as e:
        print(f"Aviso pdfplumber: {e}", file=sys.stderr)

    return paginas


def limpiar_parrafos(texto: str) -> list[str]:
    """Normaliza texto, une saltos de línea artificiales y separa párrafos."""
    # Quitar palabras partidas por guion al final de línea
    texto = re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", texto)
    # Reemplazar retornos de carro
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    # Separar en bloques
    bloques = [b.strip() for b in re.split(r"\n\s*\n+", texto) if b.strip()]
    parrafos_limpios = []
    for b in bloques:
        # Unir líneas dentro del mismo párrafo
        lineas = [l.strip() for l in b.split("\n") if l.strip()]
        # Filtrar números de página sueltos
        if len(lineas) == 1 and re.match(r"^(\d+|-\s*\d+\s*-|p[aá]g\.?\s*\d+)$", lineas[0], re.I):
            continue
        p = " ".join(lineas)
        # Normalizar espacios
        p = re.sub(r"[ \t]+", " ", p)
        if p:
            parrafos_limpios.append(p)
    return parrafos_limpios


PATRON_CAPITULO = re.compile(
    r"^(?:#+\s*)?(?:cap[ií]tulo|chapter|parte|secci[oó]n|libro|acto)\s+([0-9ivxlcdm]+|[a-záéíóú]+)[\s:.-]*(.*)$",
    re.IGNORECASE,
)


def detectar_capitulos(paginas: list[str]) -> list[dict[str, Any]]:
    """Segmenta el texto de las páginas en capítulos con título y párrafos."""
    todos_parrafos: list[str] = []
    for pag in paginas:
        ps = limpiar_parrafos(pag)
        todos_parrafos.extend(ps)

    if not todos_parrafos:
        return []

    capitulos: list[dict[str, Any]] = []
    cap_actual: dict[str, Any] | None = None

    for p in todos_parrafos:
        m = PATRON_CAPITULO.match(p)
        es_encabezado_corto = len(p) <= 60 and (
            m or re.match(r"^[0-9IVXLCDM]+[\.:\s]+[A-ZÁÉÍÓÚ]", p) or (p.isupper() and len(p.split()) <= 6)
        )

        if es_encabezado_corto:
            # Nuevo capítulo detectado
            if cap_actual and cap_actual["parrafos"]:
                capitulos.append(cap_actual)
            titulo = p.lstrip("#").strip()
            cap_actual = {"titulo": titulo, "parrafos": []}
        else:
            if cap_actual is None:
                cap_actual = {"titulo": "Inicio", "parrafos": []}
            cap_actual["parrafos"].append(p)

    if cap_actual and cap_actual["parrafos"]:
        capitulos.append(cap_actual)

    # Si no se detectaron encabezados o es un solo capítulo gigante, agrupar por bloques de ~1200 palabras
    if len(capitulos) <= 1:
        parrafos_totales = todos_parrafos
        capitulos = []
        acum_p: list[str] = []
        palabras_acum = 0
        num_cap = 1

        for p in parrafos_totales:
            acum_p.append(p)
            palabras_acum += len(p.split())
            if palabras_acum >= 1500:
                capitulos.append({
                    "titulo": f"Capítulo {num_cap}",
                    "parrafos": acum_p,
                })
                num_cap += 1
                acum_p = []
                palabras_acum = 0

        if acum_p:
            if capitulos and palabras_acum < 300:
                capitulos[-1]["parrafos"].extend(acum_p)
            else:
                capitulos.append({
                    "titulo": f"Capítulo {num_cap}",
                    "parrafos": acum_p,
                })

    return capitulos


async def sintetizar_capitulo(
    texto_capitulo: str,
    voice_name: str,
    salida_mp3: Path,
    salida_json: Path,
    voz_id: str,
) -> float:
    """Sintetiza el texto de un capítulo completo con Edge-TTS y calcula segmentos de sincronización."""
    import edge_tts

    # Dividir texto si es excesivamente largo para no saturar una sola petición (límite seguro ~15,000 caracteres)
    bloques = []
    caracteres = 0
    actual = []
    for parrafo in texto_capitulo.split("\n\n"):
        if caracteres + len(parrafo) > 8000 and actual:
            bloques.append("\n\n".join(actual))
            actual = [parrafo]
            caracteres = len(parrafo)
        else:
            actual.append(parrafo)
            caracteres += len(parrafo)
    if actual:
        bloques.append("\n\n".join(actual))

    todos_segmentos: list[dict[str, Any]] = []
    todos_audio: list[bytes] = []
    tiempo_acumulado = 0.0
    seg_idx = 0

    for bloque in bloques:
        comm = edge_tts.Communicate(bloque, voice_name)
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                todos_audio.append(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                inicio = round(tiempo_acumulado + (chunk["offset"] / 1e7), 2)
                fin = round(tiempo_acumulado + ((chunk["offset"] + chunk["duration"]) / 1e7), 2)
                t_seg = chunk["text"].strip()
                if t_seg:
                    todos_segmentos.append({
                        "i": seg_idx,
                        "texto": t_seg,
                        "inicio": inicio,
                        "fin": fin,
                    })
                    seg_idx += 1
        if todos_segmentos:
            tiempo_acumulado = todos_segmentos[-1]["fin"]

    duracion = round(tiempo_acumulado, 2)
    salida_mp3.parent.mkdir(parents=True, exist_ok=True)
    salida_mp3.write_bytes(b"".join(todos_audio))

    salida_json.write_text(
        json.dumps({
            "duracion_s": duracion,
            "voz": voz_id,
            "segmentos": todos_segmentos,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return duracion


async def procesar_libro(
    ruta_archivo: Path,
    slug: str,
    titulo: str,
    autor: str,
    voz_id: str,
    tarea_id: str | None,
):
    try:
        reportar_progreso(tarea_id, "inicio", 5, "Iniciando análisis del documento...")

        voice_name, voice_desc = VOCES_EDGE.get(
            voz_id, (VOCES_EDGE[VOZ_DEFECTO][0], VOCES_EDGE[VOZ_DEFECTO][1])
        )

        dir_libro = DIR_LIBROS / slug
        dir_texto = dir_libro / "texto"
        dir_audio = dir_libro / "audio" / voz_id
        dir_texto.mkdir(parents=True, exist_ok=True)
        dir_audio.mkdir(parents=True, exist_ok=True)

        # 1. Extraer portada si es PDF
        portada_nombre = None
        if ruta_archivo.suffix.lower() == ".pdf":
            reportar_progreso(tarea_id, "portada", 10, "Extrayendo portada del libro...")
            if extraer_portada(ruta_archivo, dir_libro / "portada.jpg"):
                portada_nombre = "portada.jpg"

        # 2. Extraer texto y estructurar capítulos
        reportar_progreso(tarea_id, "extraccion", 15, "Analizando texto y capítulos...")
        if ruta_archivo.suffix.lower() == ".pdf":
            paginas = extraer_texto_pdf(ruta_archivo)
            capitulos = detectar_capitulos(paginas)
        else:
            contenido = ruta_archivo.read_text(encoding="utf-8", errors="replace")
            capitulos = detectar_capitulos([contenido])

        if not capitulos:
            raise ValueError("No se pudo extraer texto legible del archivo seleccionado.")

        total_capitulos = len(capitulos)
        reportar_progreso(
            tarea_id,
            "capitulos_listos",
            20,
            f"Se estructuraron {total_capitulos} capítulos. Iniciando narración...",
            {"total_capitulos": total_capitulos},
        )

        # 3. Guardar textos en markdown y preparar libro.json
        capitulos_meta = []
        for i, cap in enumerate(capitulos, 1):
            nn = f"{i:02d}"
            archivo_md = dir_texto / f"{nn}.md"
            texto_completo = f"# {cap['titulo']}\n\n" + "\n\n".join(cap["parrafos"]) + "\n"
            archivo_md.write_text(texto_completo, encoding="utf-8")
            capitulos_meta.append({
                "n": i,
                "titulo": cap["titulo"],
                "archivo_texto": f"texto/{nn}.md",
                "archivo_audio": f"audio/{voz_id}/{nn}.mp3",
                "duracion_s": 0.0,
            })

        libro_meta = {
            "slug": slug,
            "titulo": titulo,
            "autor": autor,
            "idioma_original": "es",
            "traducido": False,
            "voz": voz_id,
            "estado": "narrando",
            "capitulos": capitulos_meta,
        }
        if portada_nombre:
            libro_meta["portada"] = portada_nombre

        (dir_libro / "libro.json").write_text(
            json.dumps(libro_meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 4. Narrar cada capítulo con Edge-TTS
        duracion_total = 0.0
        for i, cap in enumerate(capitulos, 1):
            nn = f"{i:02d}"
            pct = 20 + int(75 * ((i - 1) / total_capitulos))
            reportar_progreso(
                tarea_id,
                "narrando",
                pct,
                f"Narrando capítulo {i} de {total_capitulos}: «{cap['titulo']}» ({voice_desc})...",
                {"capitulo_actual": i, "total_capitulos": total_capitulos},
            )

            texto_narrar = f"{cap['titulo']}.\n\n" + "\n\n".join(cap["parrafos"])
            salida_mp3 = dir_audio / f"{nn}.mp3"
            salida_json = dir_audio / f"{nn}.json"

            dur_cap = await sintetizar_capitulo(
                texto_narrar, voice_name, salida_mp3, salida_json, voz_id
            )
            capitulos_meta[i - 1]["duracion_s"] = dur_cap
            duracion_total += dur_cap

            # Actualizar libro.json gradualmente para que la app ya pueda ir reproduciendo
            libro_meta["capitulos"] = capitulos_meta
            (dir_libro / "libro.json").write_text(
                json.dumps(libro_meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        # 5. Marcar como completado
        libro_meta["estado"] = "completo"
        (dir_libro / "libro.json").write_text(
            json.dumps(libro_meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        reportar_progreso(
            tarea_id,
            "completado",
            100,
            f"¡Audiolibro «{titulo}» generado con éxito! ({len(capitulos)} capítulos)",
            {
                "slug": slug,
                "titulo": titulo,
                "duracion_total": round(duracion_total, 1),
                "url": f"#/libro/{slug}",
            },
        )
        print(f"Éxito: Audiolibro {slug} listo en {duracion_total:.1f}s.")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        reportar_progreso(
            tarea_id,
            "error",
            0,
            f"Error al procesar: {str(e)}",
            {"error": str(e), "detalle": tb},
        )
        sys.exit(1)


async def narrar_libro_existente(slug: str, voz_id: str, tarea_id: str | None = None):
    try:
        dir_libro = DIR_LIBROS / slug
        if not dir_libro.exists():
            raise FileNotFoundError(f"No existe el libro con slug '{slug}'")

        ruta_libro_json = dir_libro / "libro.json"
        if not ruta_libro_json.exists():
            raise FileNotFoundError(f"No se encontró libro.json en '{dir_libro}'")

        libro_meta = json.loads(ruta_libro_json.read_text(encoding="utf-8"))
        titulo = libro_meta.get("titulo", slug)

        voice_info = VOCES_EDGE.get(voz_id, VOCES_EDGE.get(VOZ_DEFECTO))
        voice_name, voice_desc = voice_info

        dir_texto = dir_libro / "texto"
        dir_audio = dir_libro / "audio" / voz_id
        dir_audio.mkdir(parents=True, exist_ok=True)

        archivos_md = sorted(dir_texto.glob("*.md"))
        if not archivos_md:
            raise ValueError(f"No se encontraron capítulos en formato markdown en '{dir_texto}'")

        total_capitulos = len(archivos_md)
        reportar_progreso(
            tarea_id,
            "iniciado",
            10,
            f"Iniciando narración de «{titulo}» ({total_capitulos} capítulos) con voz de {voice_desc}...",
            {"total_capitulos": total_capitulos, "voz": voz_id},
        )

        duracion_total = 0.0
        for i, archivo_md in enumerate(archivos_md, 1):
            nn = archivo_md.stem
            pct = 10 + int(85 * ((i - 1) / total_capitulos))
            reportar_progreso(
                tarea_id,
                "narrando",
                pct,
                f"Narrando capítulo {i} de {total_capitulos} ({voice_desc})...",
                {"capitulo_actual": i, "total_capitulos": total_capitulos},
            )
            texto = archivo_md.read_text(encoding="utf-8")
            salida_mp3 = dir_audio / f"{nn}.mp3"
            salida_json = dir_audio / f"{nn}.json"

            dur_cap = await sintetizar_capitulo(
                texto, voice_name, salida_mp3, salida_json, voz_id
            )
            duracion_total += dur_cap

        # Limpiar de pedidos.json si estaba anotado
        try:
            ruta_pedidos = DIR_TRABAJO / "narrador" / "pedidos.json"
            if ruta_pedidos.exists():
                datos_p = json.loads(ruta_pedidos.read_text(encoding="utf-8"))
                pedidos_filtrados = [p for p in datos_p.get("pedidos", []) if not (p.get("slug") == slug and p.get("voz") == voz_id)]
                datos_p["pedidos"] = pedidos_filtrados
                ruta_pedidos.write_text(json.dumps(datos_p, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

        reportar_progreso(
            tarea_id,
            "completado",
            100,
            f"¡Narración completada con éxito en voz de {voice_desc}!",
            {
                "slug": slug,
                "titulo": titulo,
                "voz": voz_id,
                "duracion_total": round(duracion_total, 1),
                "url": f"#/libro/{slug}",
            },
        )
        print(f"Éxito: Narración completada para {slug} en voz {voz_id}.")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        reportar_progreso(
            tarea_id,
            "error",
            0,
            f"Error al narrar: {str(e)}",
            {"error": str(e), "detalle": tb},
        )
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Procesar y sintetizar audiolibro")
    parser.add_argument("archivo", nargs="?", default=None, help="Ruta al archivo PDF o texto")
    parser.add_argument("--re-narrar", help="Slug del libro existente para narrar en otra voz")
    parser.add_argument("--slug", help="Slug único para el libro")
    parser.add_argument("--titulo", help="Título del libro")
    parser.add_argument("--autor", default="Desconocido", help="Autor del libro")
    parser.add_argument("--voz", default=VOZ_DEFECTO, help="Voz Edge-TTS a utilizar")
    parser.add_argument("--tarea-id", help="Identificador único de la tarea")

    args = parser.parse_args()

    if args.re_narrar:
        asyncio.run(
            narrar_libro_existente(
                slug=args.re_narrar,
                voz_id=args.voz,
                tarea_id=args.tarea_id,
            )
        )
        return

    if not args.archivo:
        print("Error: Se requiere una ruta de archivo o el parámetro --re-narrar", file=sys.stderr)
        sys.exit(1)

    ruta_archivo = Path(args.archivo).resolve()
    if not ruta_archivo.exists():
        print(f"Error: No existe el archivo {ruta_archivo}", file=sys.stderr)
        sys.exit(1)

    titulo = args.titulo or ruta_archivo.stem.replace("-", " ").replace("_", " ").title()
    slug = args.slug or limpiar_slug(titulo)

    asyncio.run(
        procesar_libro(
            ruta_archivo=ruta_archivo,
            slug=slug,
            titulo=titulo,
            autor=args.autor,
            voz_id=args.voz,
            tarea_id=args.tarea_id,
        )
    )


if __name__ == "__main__":
    main()
