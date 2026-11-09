#!/bin/zsh
if command -v docker >/dev/null 2>&1; then
  DOCKER_BIN="$(command -v docker)"
else
  DOCKER_BIN="/Applications/Docker.app/Contents/Resources/bin/docker"
fi

"$DOCKER_BIN" rm -f ottava-ohif-app >/dev/null 2>&1 || true
"$DOCKER_BIN" rm -f ottava-ohif-proxy >/dev/null 2>&1 || true
"$DOCKER_BIN" network rm ottava-ohif-net >/dev/null 2>&1 || true

echo "OTTAVA OHIF detenido."
