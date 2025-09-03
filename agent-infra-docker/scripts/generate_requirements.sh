#!/bin/bash

############################################################################
# Generate requirements.txt from pyproject.toml
# Usage:
# ./scripts/generate_requirements.sh: Generate requirements.txt
# ./scripts/generate_requirements.sh upgrade: Upgrade requirements.txt
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname $CURR_DIR)"
source ${CURR_DIR}/_utils.sh

print_heading "Generating requirements.txt..."

if [[ "$#" -eq 1 ]] && [[ "$1" = "upgrade" ]];
then
  print_heading "Generating requirements.txt with upgrade"
  UV_CUSTOM_COMPILE_COMMAND="./scripts/generate_requirements.sh upgrade" \
    uv pip compile ${REPO_ROOT}/pyproject.toml --no-cache --upgrade -o ${REPO_ROOT}/requirements.txt
else
  print_heading "Generating requirements.txt"
  UV_CUSTOM_COMPILE_COMMAND="./scripts/generate_requirements.sh" \
    uv pip compile ${REPO_ROOT}/pyproject.toml --no-cache -o ${REPO_ROOT}/requirements.txt
fi
