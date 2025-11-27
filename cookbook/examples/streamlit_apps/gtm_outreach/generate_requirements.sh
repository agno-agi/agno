#!/bin/bash
# Generate pinned requirements.txt from requirements.in
# Requires pip-tools (pip-compile)

set -e

if ! command -v pip-compile &> /dev/null; then
  echo "⚠️ pip-tools not found. Installing..."
  pip install pip-tools
fi

echo "📦 Compiling requirements..."
pip-compile requirements.in --output-file requirements.txt

echo "✅ requirements.txt generated from requirements.in"
