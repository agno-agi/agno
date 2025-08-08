#!/bin/bash

############################################################################
# Validate the agno_aws library using ruff and mypy
# Usage: ./libs/infra/agno_aws/scripts/validate.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_OS_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Validating agno_os"

print_heading "Running: ruff check ${AGNO_OS_DIR}"
ruff check ${AGNO_OS_DIR}

print_heading "Running: mypy ${AGNO_OS_DIR} --config-file ${AGNO_OS_DIR}/pyproject.toml"
mypy ${AGNO_OS_DIR} --config-file ${AGNO_OS_DIR}/pyproject.toml
