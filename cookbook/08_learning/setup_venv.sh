#!/bin/bash

############################################################################
#
#    Learning Machines Environment Setup
#
#    Usage: ./cookbook/08_learning/venv_setup.sh
#    Run:   python cookbook/08_learning/01_basics/1_user_profile_always.py
#
############################################################################

set -e

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "${CURR_DIR}")")"
VENV_DIR="${REPO_ROOT}/.venvs/learning"
REQUIREMENTS_FILE="${CURR_DIR}/requirements.txt"

# Colors
ORANGE='\033[38;5;208m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${ORANGE}"
cat << 'BANNER'
     █████╗  ██████╗ ███╗   ██╗ ██████╗
    ██╔══██╗██╔════╝ ████╗  ██║██╔═══██╗
    ███████║██║  ███╗██╔██╗ ██║██║   ██║
    ██╔══██║██║   ██║██║╚██╗██║██║   ██║
    ██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝
    ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝
BANNER
echo -e "${NC}"
echo -e "    ${DIM}LearningMachine Cookbook Setup${NC}"
echo ""

# Preflight
if [[ -n "$VIRTUAL_ENV" ]]; then
    echo "    Deactivate your current venv first."
    exit 1
fi

if ! command -v uv &> /dev/null; then
    echo "    uv not found. Install: https://docs.astral.sh/uv/"
    exit 1
fi

# Setup
echo -e "    ${DIM}Removing old environment...${NC}"
echo -e "    ${DIM}> rm -rf ${VENV_DIR}${NC}"
rm -rf ${VENV_DIR}

echo ""
echo -e "    ${DIM}Creating Python 3.12 venv...${NC}"
echo -e "    ${DIM}> uv venv ${VENV_DIR} --python 3.12${NC}"
uv venv ${VENV_DIR} --python 3.12 --quiet

echo ""
echo -e "    ${DIM}Installing requirements...${NC}"
echo -e "    ${DIM}> VIRTUAL_ENV=${VENV_DIR} uv uv pip install -r ${REQUIREMENTS_FILE}${NC}"
VIRTUAL_ENV=${VENV_DIR} uv uv pip install -r ${REQUIREMENTS_FILE} --quiet

# Copy activation command to clipboard
ACTIVATE_CMD="source .venvs/learning/bin/activate"
echo -n "${ACTIVATE_CMD}" | pbcopy

echo ""
echo -e "    ${BOLD}Done.${NC}"
echo ""
echo -e "    ${DIM}Activate:${NC}  ${ACTIVATE_CMD}"
echo -e "    ${DIM}Run:${NC}       python cookbook/08_learning/01_basics/1_user_profile_always.py"
echo ""
echo -e "    ${DIM}(Activation command copied to clipboard. Just paste and hit enter.)${NC}"
echo ""
