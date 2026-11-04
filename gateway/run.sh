#!/bin/bash
# Launcher for the PythonAnywhere always-on task: loads gateway/.env (ATLAS_URL=...), finds the nvm Node, starts the gateway.
cd "$(dirname "$0")" || exit 1
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
NODE_BIN_DIR="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | tail -1)"
[ -n "$NODE_BIN_DIR" ] && export PATH="$NODE_BIN_DIR:$PATH"
exec node index.js
