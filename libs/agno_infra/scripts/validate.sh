#!/bin/bash

############################################################################
# Validate the agno_aws library using ruff and mypy
# Usage: ./libs/infra/agno_aws/scripts/validate.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_INFRA_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Validating agno_infra"

print_heading "Running: ruff check ${AGNO_INFRA_DIR}"
ruff check ${AGNO_INFRA_DIR}

print_heading "Running: mypy ${AGNO_INFRA_DIR} --config-file ${AGNO_INFRA_DIR}/pyproject.toml"
mypy ${AGNO_INFRA_DIR} --config-file ${AGNO_INFRA_DIR}/pyproject.toml
