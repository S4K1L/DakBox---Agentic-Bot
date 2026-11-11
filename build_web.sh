#!/usr/bin/env bash
# Build the Flutter web app. The backend then serves it at / (same origin as the API).
set -euo pipefail
cd "$(dirname "$0")/app"
flutter build web --release --no-tree-shake-icons
echo "Built app/build/web. Start the API:  cd backend && .venv/bin/uvicorn app.main:app --port 4000"
