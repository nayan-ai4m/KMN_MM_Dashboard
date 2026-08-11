#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
uvicorn main:app --host 0.0.0.0 --port 7075 --reload
