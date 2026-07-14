#!/bin/bash

############################################################################
# Format the agno_aws library using ruff
# Usage: ./libs/infra/agno_aws/scripts/format.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_INFRA_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Formatting agno_infra"

print_heading "Running: ruff format ${AGNO_INFRA_DIR}"
ruff format ${AGNO_INFRA_DIR}

print_heading "Running: ruff check --select I --fix ${AGNO_INFRA_DIR}"
ruff check --select I --fix ${AGNO_INFRA_DIR}
