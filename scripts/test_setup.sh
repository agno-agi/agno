#!/bin/bash

############################################################################
# Agno Development Setup
# - Create a virtual environment and install libraries in editable mode.
# - Please install uv before running this script.
# - Please deactivate the existing virtual environment before running.
# Usage: ./scripts/dev_setup.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
AGNO_DIR="${REPO_ROOT}/libs/agno"
AGNO_INFRA_DIR="${REPO_ROOT}/libs/agno_infra"
source "${CURR_DIR}/_utils.sh"

VENV_DIR="${REPO_ROOT}/.venv"
PYTHON_VERSION=$(python3 --version)

print_heading "Development setup..."

print_heading "Removing virtual env"
print_info "rm -rf ${VENV_DIR}"
rm -rf ${VENV_DIR}

print_heading "Creating virtual env"
print_info "VIRTUAL_ENV=${VENV_DIR} uv venv --python 3.12"
VIRTUAL_ENV=${VENV_DIR} uv venv --python 3.12

print_heading "Installing agno"
print_info "VIRTUAL_ENV=${VENV_DIR} uv pip install -r ${AGNO_DIR}/requirements.txt"
VIRTUAL_ENV=${VENV_DIR} uv pip install -r ${AGNO_DIR}/requirements.txt

print_heading "Installing agno in editable mode with tests dependencies"
VIRTUAL_ENV=${VENV_DIR} uv pip install -U -e "${AGNO_DIR}[tests]"
VIRTUAL_ENV=${VENV_DIR} uv pip install brave-search


print_heading "Installing agno-infra"
print_info "VIRTUAL_ENV=${VENV_DIR} uv pip install -r ${AGNO_INFRA_DIR}/requirements.txt"
VIRTUAL_ENV=${VENV_DIR} uv pip install -r ${AGNO_INFRA_DIR}/requirements.txt

print_heading "Installing agno-infra in editable mode with dev dependencies"
VIRTUAL_ENV=${VENV_DIR} uv pip install -e ${AGNO_INFRA_DIR}[dev]

print_heading "Development setup complete"
print_heading "Activate venv using: source .venv/bin/activate"