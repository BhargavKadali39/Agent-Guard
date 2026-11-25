#!/usr/bin/env bash
# AgentGuard - one-time local setup on macOS/Linux.  Usage: ./scripts/setup-local.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"

cd "$root/backend"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
if [ ! -f .env ]; then
  secret="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  sed "s|^JWT_SECRET=.*|JWT_SECRET=${secret}|" .env.example > .env
  echo "Created backend/.env with a random JWT_SECRET"
fi

cd "$root/frontend"
npm install

echo
echo "Setup complete. Next:"
echo "  Terminal 1: cd backend && .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
echo "  Terminal 2: cd frontend && npm run dev"
echo "  Then open http://localhost:3000"
