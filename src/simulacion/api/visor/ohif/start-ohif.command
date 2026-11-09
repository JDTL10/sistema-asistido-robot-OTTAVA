#!/bin/zsh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if command -v docker >/dev/null 2>&1; then
  DOCKER_BIN="$(command -v docker)"
else
  DOCKER_BIN="/Applications/Docker.app/Contents/Resources/bin/docker"
fi

if [ ! -x "$DOCKER_BIN" ]; then
  echo "ERROR: No se encontró Docker CLI."
  exit 1
fi

if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
  echo "ERROR: Docker Desktop no está iniciado."
  exit 1
fi

echo "=================================================="
echo "OTTAVA · OHIF VIEWER V2"
echo "=================================================="
echo "Docker: OK"
echo "Orthanc esperado: http://localhost:8042"
echo ""

# Clean previous version/containers.
"$DOCKER_BIN" rm -f ottava-ohif >/dev/null 2>&1 || true
"$DOCKER_BIN" rm -f ottava-ohif-app >/dev/null 2>&1 || true
"$DOCKER_BIN" rm -f ottava-ohif-proxy >/dev/null 2>&1 || true
"$DOCKER_BIN" network rm ottava-ohif-net >/dev/null 2>&1 || true

"$DOCKER_BIN" network create ottava-ohif-net >/dev/null

APP_CONFIG_CONTENT="$(cat "$SCRIPT_DIR/app-config.js")"

echo "1/2 Iniciando OHIF..."
"$DOCKER_BIN" run -d \
  --name ottava-ohif-app \
  --network ottava-ohif-net \
  --restart unless-stopped \
  -e APP_CONFIG="$APP_CONFIG_CONTENT" \
  ohif/app:v3.13.14 >/dev/null

echo "2/2 Iniciando proxy OTTAVA..."
"$DOCKER_BIN" run -d \
  --name ottava-ohif-proxy \
  --network ottava-ohif-net \
  --restart unless-stopped \
  -p 3000:80 \
  -v "$SCRIPT_DIR/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginx:alpine >/dev/null

echo ""
echo "OHIF listo."
echo ""
echo "Abrir:"
echo "  http://localhost:3000"
echo ""
echo "Prueba DICOMweb:"
echo "  http://localhost:3000/dicom-web/studies"
echo ""
echo "=================================================="
