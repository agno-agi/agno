#!/bin/bash

############################################################################
# Validate the agno library using ruff and mypy
# Usage: ./libs/agno/scripts/validate.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Validating agno"

print_heading "Running: ruff check ${AGNO_DIR}"
ruff check ${AGNO_DIR}

print_heading "Running: mypy ${AGNO_DIR} --config-file ${AGNO_DIR}/pyproject.toml"
mypy ${AGNO_DIR} --config-file ${AGNO_DIR}/pyproject.toml
