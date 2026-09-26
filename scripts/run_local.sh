#!/usr/bin/env bash
# ==============================================================================
# Local Execution Script with Google Application Default Credentials (ADC)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

echo "Checking Application Default Credentials (ADC)..."
if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
    echo "ADC not found. Running: gcloud auth application-default login"
    gcloud auth application-default login
fi

export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
export GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
export PORT="${PORT:-8080}"
export LOG_LEVEL="DEBUG"

echo "Starting A2A Server locally on http://0.0.0.0:${PORT}"
python3 -m uvicorn agents.orchestrator.a2a_server:app --host 0.0.0.0 --port "${PORT}" --reload
