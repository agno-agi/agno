#!/bin/bash

############################################################################
# Performance Testing Setup
# - Create a virtual environment and install libraries in editable mode.
# - Please install uv before running this script.
# - Please deactivate the existing virtual environment before running.
# Usage: ./scripts/perf_setup.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
AGNO_DIR="${REPO_ROOT}/libs/agno"
source "${CURR_DIR}/_utils.sh"

VENV_DIR="${REPO_ROOT}/.venvs/perfenv"
PYTHON_VERSION=$(python3 --version)

print_heading "Performance Testing setup..."

print_heading "Removing virtual env"
print_info "rm -rf ${VENV_DIR}"
rm -rf ${VENV_DIR}

print_heading "Creating virtual env"
print_info "uv venv --python 3.12 ${VENV_DIR}"
uv venv --python 3.12 ${VENV_DIR}

print_heading "Installing libraries"
VIRTUAL_ENV=${VENV_DIR} uv pip install -U agno langgraph langchain_openai crewai pydantic_ai smolagents

print_heading "uv pip list"
VIRTUAL_ENV=${VENV_DIR} uv pip list

print_heading "Performance Testing setup complete"
print_heading "Activate venv using: source ${VENV_DIR}/bin/activate"
