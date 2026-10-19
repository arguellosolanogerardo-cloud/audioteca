#!/usr/bin/env bash
# Instalación de la Audioteca en un Mac con Apple Silicon. Se puede correr las veces que quieras.
#
#   ./setup.sh                 todo: herramientas, Python + IA local (MLX), voz genérica de Qwen y .env
#   ./setup.sh --sin-ia        sin modelos de IA: extraer libros y narrar con la voz de macOS (también en Intel)
#   ./setup.sh --sin-modelos   instala la IA pero no descarga nada todavía (se baja al primer uso)
#   ./setup.sh --dev           además, lo necesario para `./audioteca check` (Playwright + WebKit)
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
IA=1; MODELOS=1; DEV=0
for a in "$@"; do
  case "$a" in
    --sin-ia) IA=0 ;;
    --sin-modelos) MODELOS=0 ;;
    --dev) DEV=1 ;;
    -h|--help) sed -n 2,8p "$0"; exit 0 ;;
    *) echo "opción desconocida: $a" >&2; exit 2 ;;
  esac
done

paso() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
aviso() { printf '\033[33m  ! %s\033[0m\n' "$*"; }

paso "Revisando el Mac"
[[ "$(uname -s)" == "Darwin" ]] || { echo "La Audioteca necesita macOS (usa say, MLX y Metal)." >&2; exit 1; }
if [[ "$(uname -m)" != "arm64" && $IA -eq 1 ]]; then
  aviso "Este Mac no es Apple Silicon: MLX no corre aquí. Sigo con --sin-ia (voz de macOS, sin traductor)."
  IA=0
fi
echo "  macOS $(sw_vers -productVersion) · $(uname -m)"

paso "Herramientas (Homebrew): node, ffmpeg, poppler (pdftotext), uv"
faltan=()
command -v node >/dev/null || faltan+=(node)
command -v ffmpeg >/dev/null || faltan+=(ffmpeg)
command -v pdftotext >/dev/null || faltan+=(poppler)
command -v uv >/dev/null || faltan+=(uv)
if ((${#faltan[@]})); then
  if ! command -v brew >/dev/null; then
    echo "Falta Homebrew para instalar: ${faltan[*]}" >&2
    echo 'Instálalo con: /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' >&2
    exit 1
  fi
  brew install "${faltan[@]}"
fi
node_mayor="$(node -p 'process.versions.node.split(".")[0]')"
if ((node_mayor < 20)); then echo "Necesitas Node 20 o más nuevo (tienes $(node -v)): brew upgrade node" >&2; exit 1; fi
echo "  node $(node -v) · $(ffmpeg -version | head -1 | cut -d' ' -f1-3) · $(pdftotext -v 2>&1 | head -1) · $(uv --version)"

paso "Entorno de Python (.venv)"
[[ -x .venv/bin/python ]] || uv venv --python 3.12 .venv
if ((IA)); then
  uv pip install --python .venv/bin/python -r requirements-ia.txt
else
  uv pip install --python .venv/bin/python -r requirements.txt
fi

if ((DEV)); then
  paso "Pruebas: Playwright + WebKit"
  npm install --no-audit --no-fund
  npx playwright install webkit
fi

paso "Configuración y carpetas"
mkdir -p biblioteca voces .trabajo
nuevo_env=0
if [[ ! -f .env ]]; then
  cp .env.example .env
  nuevo_env=1
  echo "  .env creado desde .env.example (edítalo cuando quieras)"
else
  echo "  .env ya existe: no lo toco"
fi
if ! say -v '?' | grep -qE 'es_(MX|US|419|ES)'; then
  aviso "No hay voces de macOS en español. Agrega una en Ajustes del Sistema → Accesibilidad → Contenido leído → Voz del sistema."
fi

if ((IA && MODELOS)); then
  paso "Voz genérica de Qwen (descarga ~1 GB la primera vez)"
  if [[ -f voces/qwen.wav && -f voces/qwen.txt ]]; then
    echo "  voces/qwen.wav ya existe"
  elif ./audioteca voz base; then
    if ((nuevo_env)); then
      sed -i '' 's/^AUDIOTECA_VOZ=macos$/AUDIOTECA_VOZ=qwen-clon/' .env
      echo "  los libros nuevos se narrarán con qwen-clon (AUDIOTECA_VOZ en .env)"
    fi
  else
    aviso "No pude crear la voz de Qwen; puedes reintentar con ./audioteca voz base. Mientras tanto se usa la voz de macOS."
  fi
fi

ip="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo '<ip-de-tu-mac>')"
puerto="$(grep -E '^AUDIOTECA_PUERTO=' .env | cut -d= -f2 || true)"
cat <<EOF

$(printf '\033[1m')Audioteca instalada.$(printf '\033[0m')

  1. Prueba rápida (Quijote, voz de macOS):   ./audioteca demo
  2. Abre la app:                              ./audioteca servir
     En el iPhone (misma red Wi-Fi):           http://$ip:${puerto:-3410}/
     Safari → Compartir → «Agregar a inicio».
  3. Tus libros:                               ./audioteca libro mi-libro.epub --slug mi-libro --titulo "…" --autor "…"
                                               ./audioteca traducir book.pdf --slug mi-libro      (inglés → español)
                                               ./audioteca narrar
  Ayuda:                                       ./audioteca ayuda   ·   README.md
EOF
