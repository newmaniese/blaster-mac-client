#!/usr/bin/env bash
# Blaster Mac Client — one-step run: create venv if needed, install deps, run app.
# Usage: ./run.sh   (from the blaster-mac-client directory)

set -e
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "Creating virtualenv and installing dependencies..."
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

exec .venv/bin/python -m blaster
