#!/bin/zsh
# Purpose: Start My Bulter Enterprise on loopback. Inputs: process environment.
# Outputs: local web app. Author: Carter Tan. Assumes Python dependencies installed.
set -eu
cd "$(dirname "$0")/.."
umask 077
bulter_python=python3
if [[ -x src/.venv/bin/python3 ]]; then
  bulter_python=src/.venv/bin/python3
fi
exec "$bulter_python" -m uvicorn src.app:create_app --factory --host 127.0.0.1 --port 8765 --no-access-log
