#!/usr/bin/env bash
# The release gate for hosting more than one business. Run from backend/ before every release:
#   1. the isolation suite (no business can see or change another) — nothing ships if this is red;
#   2. the whole test suite;
#   3. the hosted-mode start-up check with the settings you intend to use (pass them as env vars).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"
echo "== 1/3 isolation suite"
$PY -m pytest -m isolation -q
echo "== 2/3 full suite"
$PY -m pytest -q
echo "== 3/3 hosted start-up check"
DAKBOX_HOSTED=1 $PY -c "from app import hosting; p = hosting.problems(); print('\n'.join(p) if p else 'hosted settings OK'); raise SystemExit(1 if p else 0)"
echo "Release gate passed."
