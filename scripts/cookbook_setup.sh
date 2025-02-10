#!/bin/bash

############################################################################
# Agno Setup for running cookbooks
# - Create a virtual environment and install libraries in editable mode.
# - Please deactivate the existing virtual environment before running.
# Usage: ./scripts/cookbook_setup.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
AGNO_DIR="${REPO_ROOT}/libs/agno"
source "${CURR_DIR}/_utils.sh"

VENV_DIR="${REPO_ROOT}/agnoenv"
PYTHON_VERSION=$(python3 --version)

print_heading "Development setup..."

print_heading "Removing virtual env"
print_info "rm -rf ${VENV_DIR}"
rm -rf ${VENV_DIR}

print_heading "Creating virtual env"
print_info "Creating python3 venv: ${VENV_DIR}"
python3 -m venv "${VENV_DIR}"

# Activate the venv
source "${VENV_DIR}/bin/activate"

print_info "Installing base python packages"
pip3 install --upgrade pip pip-tools twine build

print_heading "Installing requirements.txt"
pip install --no-deps \
  -r ${AGNO_DIR}/requirements.txt

print_heading "Installing agno with [dev] extras"
pip install --editable "${AGNO_DIR}[dev]"

print_heading "pip list"
pip list

print_heading "Development setup complete"
print_heading "Activate venv using: source ${VENV_DIR}/bin/activate"
