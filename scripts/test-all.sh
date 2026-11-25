#!/usr/bin/env bash
# Run the backend and frontend test suites.  Usage: ./scripts/test-all.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root/backend"
.venv/bin/ruff check app tests
.venv/bin/pytest
cd "$root/frontend"
npm run lint
npm test
npm run build
echo "All checks passed."
