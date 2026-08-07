#!/usr/bin/env sh
set -eu

PORT="${1:-8080}"
PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

echo "Demo sintetica: http://127.0.0.1:${PORT}/"
echo "Pressione Ctrl+C para encerrar."
python -m http.server "$PORT" --bind 127.0.0.1 --directory "$PROJECT_ROOT/apps/dashboard"
