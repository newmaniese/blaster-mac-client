#!/usr/bin/env bash
# Blaster Mac Client — one-step run: create venv if needed, install deps, run app.
# Usage: ./run.sh   (from the blaster-mac-client directory)

set -e
cd "$(dirname "$0")"

# Recreate if missing or if the interpreter symlink is broken (e.g. after a Homebrew Python upgrade).
if [[ ! -x .venv/bin/python ]]; then
  echo "Creating virtualenv and installing dependencies..."
  rm -rf .venv
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

exec .venv/bin/python -m blaster
