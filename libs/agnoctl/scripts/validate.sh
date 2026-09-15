#!/bin/bash

############################################################################
# Validate the agnoctl library using ruff and mypy
# Usage: ./libs/agnoctl/scripts/validate.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNOCTL_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Validating agnoctl"

print_heading "Running: ruff check ${AGNOCTL_DIR}"
ruff check ${AGNOCTL_DIR}

print_heading "Running: mypy ${AGNOCTL_DIR}/agnoctl --config-file ${AGNOCTL_DIR}/pyproject.toml"
mypy ${AGNOCTL_DIR}/agnoctl --config-file ${AGNOCTL_DIR}/pyproject.toml
