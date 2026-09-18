#!/usr/bin/env bash
# One-command local run.
#   ./run.sh          -> mock provider (no LLM, instant)
#   ./run.sh ollama   -> local Ollama (ollama pull llama3.1:8b first)
#   ./run.sh groq     -> Groq API (needs GROQ_API_KEY in the environment)
set -e

PROVIDER="${1:-mock}"
export LLM_PROVIDER="$PROVIDER"
echo ">> SkyAssist starting with LLM_PROVIDER=$PROVIDER"

# Python deps (reuse venv if present)
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r backend/requirements.txt

# Frontend build (reuse if present)
if [ ! -f frontend/dist/index.html ]; then
  echo ">> Building frontend (one-time)..."
  (cd frontend && npm install && npm run build)
fi

echo ">> App: http://localhost:8000  (Ctrl+C to stop)"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
