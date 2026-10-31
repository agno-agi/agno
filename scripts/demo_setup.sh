#!/bin/bash

############################################################################
#
#    Agno Demo Environment Setup
#
#    Creates .venvs/demo with local editable agnoctl and agno[demo],
#    separate from the day-to-day development environment in .venv.
#
#    Usage: ./scripts/demo_setup.sh
#    Run:   python cookbook/01_demo/run.py
#
############################################################################

set -euo pipefail

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
AGNO_DIR="${REPO_ROOT}/libs/agno"
AGNOCTL_DIR="${REPO_ROOT}/libs/agnoctl"
VENV_DIR="${REPO_ROOT}/.venvs/demo"

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
echo -e "    ${DIM}Demo Setup${NC}"
echo ""

# Preflight
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
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
rm -rf "${VENV_DIR}"

echo ""
echo -e "    ${DIM}Creating Python 3.12 venv...${NC}"
echo -e "    ${DIM}> uv venv ${VENV_DIR} --python 3.12${NC}"
uv venv "${VENV_DIR}" --python 3.12 --quiet

# One resolve for both editables: the local agnoctl satisfies agno's
# agnoctl dependency, so nothing is pulled from PyPI for it.
echo ""
echo -e "    ${DIM}Installing agnoctl[dev] and agno[demo] in editable mode...${NC}"
echo -e "    ${DIM}> uv pip install -e libs/agnoctl[dev] -e libs/agno[demo]${NC}"
uv pip install --python "${VENV_DIR}/bin/python" -e "${AGNOCTL_DIR}[dev]" -e "${AGNO_DIR}[demo]" --quiet

ACTIVATE_CMD="source .venvs/demo/bin/activate"
CLIPBOARD_MSG=""
if command -v pbcopy &> /dev/null; then
    if printf '%s' "${ACTIVATE_CMD}" | pbcopy 2>/dev/null; then
        CLIPBOARD_MSG="(Copied to clipboard. Just paste and hit enter.)"
    fi
elif command -v xclip &> /dev/null; then
    if printf '%s' "${ACTIVATE_CMD}" | xclip -selection clipboard 2>/dev/null; then
        CLIPBOARD_MSG="(Copied to clipboard. Just paste and hit enter.)"
    fi
fi

echo ""
echo -e "    ${BOLD}Done.${NC}"
echo ""
echo -e "    ${DIM}Activate:${NC}  ${ACTIVATE_CMD}"
echo -e "    ${DIM}Run Demo:${NC}  python cookbook/01_demo/run.py"
echo ""
if [[ -n "$CLIPBOARD_MSG" ]]; then
    echo -e "    ${DIM}${CLIPBOARD_MSG}${NC}"
    echo ""
fi
