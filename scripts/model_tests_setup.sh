#!/bin/bash

############################################################################
# Agno Model Test Setup
# - Create a virtual environment and run model-specific tests
# - Usage: ./model_tests_setup.sh <model_name>
# - Example: ./model_tests_setup.sh openai
############################################################################

# Color codes for pretty printing
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
print_heading() {
    echo "${BLUE}=== $1 ===${NC}"
}

print_success() {
    echo "${GREEN}✓ $1${NC}"
}

print_error() {
    echo "${RED}✗ $1${NC}"
}

# Validate input
if [ -z "$1" ]; then
    print_error "Please provide a model name (e.g. openai, anthropic, google)"
    echo "Available models:"
    echo "- anthropic"
    echo "- aws"
    echo "- cerebras"
    echo "- cohere"
    echo "- deepinfra"
    echo "- deepseek"
    echo "- google"
    echo "- groq"
    echo "- ibm-watsonx"
    echo "- mistral"
    echo "- nvidia"
    echo "- openai"
    echo "- openrouter"
    echo "- perplexity"
    echo "- sambanova"
    echo "- together"
    echo "- xai"
    exit 1
fi

MODEL_NAME=$1
VENV_NAME=".venv-test-${MODEL_NAME}"

# Create and activate virtual environment
print_heading "Creating test environment for ${MODEL_NAME}"
python3.12 -m venv ${VENV_NAME}
source ${VENV_NAME}/bin/activate

# Install minimal dependencies
print_heading "Installing core dependencies"
pip install --upgrade pip

pip install \
    docstring-parser \
    gitpython \
    httpx \
    pydantic-settings \
    pydantic \
    python-dotenv \
    python-multipart \
    pyyaml \
    rich \
    tomli \
    typer \
    typing-extensions

print_heading "Installing test dependencies"
pip install \
    pytest \
    pytest-asyncio \
    requests

# Change to agno directory
cd libs/agno

# Determine additional dependencies based on model
ADDITIONAL_DEPS=""
case $MODEL_NAME in
    "openai")
        ADDITIONAL_DEPS="openai,exa,sqlite,ddg,yfinance"
        if [ -z "${OPENAI_API_KEY}" ]; then
            print_error "OPENAI_API_KEY environment variable is not set"
            exit 1
        fi
        if [ -z "${EXA_API_KEY}" ]; then
            print_error "EXA_API_KEY environment variable is not set"
            exit 1
        fi
        ;;
    "google")
        ADDITIONAL_DEPS="google,sqlite,ddg,yfinance"
        if [ -z "${GOOGLE_API_KEY}" ]; then
            print_error "GOOGLE_API_KEY environment variable is not set"
            exit 1
        fi
        if [ -z "${GOOGLE_CLOUD_PROJECT}" ]; then
            print_error "GOOGLE_CLOUD_PROJECT environment variable is not set"
            exit 1
        fi
        ;;
    "anthropic")
        ADDITIONAL_DEPS="anthropic,sqlite,yfinance,ddg,exa"
        if [ -z "${ANTHROPIC_API_KEY}" ]; then
            print_error "ANTHROPIC_API_KEY environment variable is not set"
            exit 1
        fi
        ;;
    "aws")
        ADDITIONAL_DEPS="aws,sqlite,yfinance,ddg,exa,anthropic"
        if [ -z "${AWS_ACCESS_KEY_ID}" ]; then
            print_error "AWS_ACCESS_KEY_ID environment variable is not set"
            exit 1
        fi
        if [ -z "${AWS_SECRET_ACCESS_KEY}" ]; then
            print_error "AWS_SECRET_ACCESS_KEY environment variable is not set"
            exit 1
        fi
        if [ -z "${AWS_REGION}" ]; then
            print_error "AWS_REGION environment variable is not set"
            exit 1
        fi
        if [ -z "${ANTHROPIC_API_KEY}" ]; then
            print_error "ANTHROPIC_API_KEY environment variable is not set"
            exit 1
        fi
        ;;
    *)
        print_error "Unknown model: ${MODEL_NAME}"
        exit 1
        ;;
esac

# Install the package with model-specific dependencies
print_heading "Installing agno with ${MODEL_NAME} dependencies"
if [ -n "$ADDITIONAL_DEPS" ]; then
    pip install ".[${MODEL_NAME},${ADDITIONAL_DEPS}]"
else
    pip install ".[${MODEL_NAME}]"
fi

"""
Run the tests- I used this to test locally, but we already run test in test_on_release.yml so this should not be needed.

Uncomment to test locally
"""
# print_heading "Running ${MODEL_NAME} tests"
# TEST_PATH="tests/integration/models/${MODEL_NAME}"
# if [ -d "$TEST_PATH" ]; then
#     python -m pytest ${TEST_PATH} -v
#     TEST_EXIT_CODE=$?
# else
#     print_error "No tests found for ${MODEL_NAME} at ${TEST_PATH}"
#     TEST_EXIT_CODE=1
# fi

# Cleanup
print_heading "Cleaning up"
deactivate
cd ../..
rm -rf ${VENV_NAME}

# Final status
if [ $TEST_EXIT_CODE -eq 0 ]; then
    print_success "All ${MODEL_NAME} tests completed successfully!"
else
    print_error "Tests failed for ${MODEL_NAME}"
fi

exit $TEST_EXIT_CODE