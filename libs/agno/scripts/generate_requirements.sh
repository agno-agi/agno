#!/bin/bash

############################################################################
# Generate requirements.txt from pyproject.toml
# Usage:
# ./libs/agno/scripts/generate_requirements.sh: Generate requirements.txt
# ./libs/agno/scripts/generate_requirements.sh upgrade: Upgrade requirements.txt
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Generating requirements.txt"

if [[ "$#" -eq 1 ]] && [[ "$1" = "upgrade" ]];
then
  print_heading "Generating requirements.txt with upgrade"
  UV_CUSTOM_COMPILE_COMMAND="./scripts/generate_requirements.sh upgrade" \
    uv pip compile ${AGNO_DIR}/pyproject.toml --no-cache --upgrade -o ${AGNO_DIR}/requirements.txt
else
  print_heading "Generating requirements.txt"
  UV_CUSTOM_COMPILE_COMMAND="./scripts/generate_requirements.sh" \
    uv pip compile ${AGNO_DIR}/pyproject.toml --no-cache -o ${AGNO_DIR}/requirements.txt
fi
