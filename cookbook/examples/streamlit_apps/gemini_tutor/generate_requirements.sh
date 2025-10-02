#!/bin/bash

############################################################################
# Generate requirements.txt from requirements.in
############################################################################

echo "Generating requirements.txt"

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

UV_CUSTOM_COMPILE_COMMAND="./generate_requirements.sh" \
  uv pip compile ${CURR_DIR}/requirements.in --no-cache --upgrade -o ${CURR_DIR}/requirements.txt
