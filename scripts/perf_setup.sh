#!/bin/bash

############################################################################
#
#    Agno Performance Environment Setup
#
#    Usage: ./scripts/perf_setup.sh
#    Run:   python cookbook/performance/run_all.py
#
############################################################################

set -e

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
AGNO_DIR="${REPO_ROOT}/libs/agno"
VENV_DIR="${REPO_ROOT}/.venvs/perfenv"

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
echo -e "    ${DIM}Performance Setup${NC}"
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
rm -rf "${VENV_DIR}"

echo ""
echo -e "    ${DIM}Creating Python 3.12 venv...${NC}"
echo -e "    ${DIM}> uv venv ${VENV_DIR} --python 3.12${NC}"
uv venv "${VENV_DIR}" --python 3.12 --quiet

# agno installs editable from this checkout so benchmarks measure the local
# tree, not the last release. The os extra is required because agno.workflow
# imports fastapi. The other frameworks are the comparison set for
# cookbook/performance/comparison and cookbook/09_evals/performance/comparison.
# pydantic-ai is installed as pydantic-ai-slim: the full pydantic-ai bundle
# hard-requires the logfire SDK, whose pydantic plugin loads at the first
# BaseModel definition and inflates the measured cold import of every
# framework in the shared environment.
echo ""
echo -e "    ${DIM}Installing agno[os] (editable) and the comparison frameworks...${NC}"
echo -e "    ${DIM}> uv pip install -e libs/agno[os] langgraph langgraph-checkpoint-sqlite langchain_openai crewai pydantic-ai-slim[openai] openai-agents smolagents autogen-agentchat autogen-ext[openai]${NC}"
VIRTUAL_ENV="${VENV_DIR}" uv pip install -e "${AGNO_DIR}[os]" langgraph langgraph-checkpoint-sqlite langchain_openai openai-agents crewai "pydantic-ai-slim[openai]" smolagents autogen-agentchat "autogen-ext[openai]" --quiet

# Copy activation command to clipboard
ACTIVATE_CMD="source .venvs/perfenv/bin/activate"
if command -v pbcopy &> /dev/null; then
    echo -n "${ACTIVATE_CMD}" | pbcopy
    CLIPBOARD_MSG="(Copied to clipboard. Just paste and hit enter.)"
elif command -v xclip &> /dev/null; then
    echo -n "${ACTIVATE_CMD}" | xclip -selection clipboard
    CLIPBOARD_MSG="(Copied to clipboard. Just paste and hit enter.)"
else
    CLIPBOARD_MSG=""
fi

echo ""
echo -e "    ${BOLD}Done.${NC}"
echo ""
echo -e "    ${DIM}Activate:${NC}            ${ACTIVATE_CMD}"
echo -e "    ${DIM}Agno benchmarks:${NC}     python cookbook/performance/run_all.py"
echo -e "    ${DIM}Framework comparison:${NC} python cookbook/performance/comparison/run_all.py"
echo -e "    ${DIM}HTML report:${NC}         python cookbook/performance/report.py"
echo ""
if [[ -n "$CLIPBOARD_MSG" ]]; then
    echo -e "    ${DIM}${CLIPBOARD_MSG}${NC}"
    echo ""
fi
