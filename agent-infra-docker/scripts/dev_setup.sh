#!/bin/bash

############################################################################
# Development Setup
# - This script creates a virtual environment and installs libraries in editable mode.
# - Please install uv before running this script.
# - Please deactivate the existing virtual environment before running.
# Usage: ./scripts/dev_setup.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname $CURR_DIR)"
VENV_DIR="${REPO_ROOT}/.venv"
source ${CURR_DIR}/_utils.sh

print_heading "Development setup..."

print_heading "Removing virtual env"
print_info "rm -rf ${VENV_DIR}"
rm -rf ${VENV_DIR}

print_heading "Creating virtual env"
print_info "VIRTUAL_ENV=${VENV_DIR} uv venv --python 3.12"
VIRTUAL_ENV=${VENV_DIR} uv venv --python 3.12

print_heading "Installing requirements"
print_info "VIRTUAL_ENV=${VENV_DIR} uv pip install -r ${REPO_ROOT}/requirements.txt"
VIRTUAL_ENV=${VENV_DIR} uv pip install -r ${REPO_ROOT}/requirements.txt

print_heading "Installing project in editable mode with dev dependencies"
print_info "VIRTUAL_ENV=${VENV_DIR} uv pip install -e ${REPO_ROOT}[dev]"
VIRTUAL_ENV=${VENV_DIR} uv pip install -e ${REPO_ROOT}[dev]

print_heading "Development setup complete"
print_heading "Activate venv using: source .venv/bin/activate"
