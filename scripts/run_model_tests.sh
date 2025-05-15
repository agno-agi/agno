#!/bin/bash

############################################################################
# Agno Model Test Setup
# - Create a virtual environment and run model-specific tests
# - Usage: ./model_tests_setup.sh <model_name>
# - Example: ./model_tests_setup.sh openai
############################################################################

# Print functions
print_heading() {
    echo ""
    echo "=== $1 ==="
}

print_info() {
    echo "$1"
}

# Validate input
if [ -z "$1" ]; then
    print_heading "Error: Please provide a model name"
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
VENV_NAME=".venv"

# Create and activate virtual environment
print_heading "Creating test environment for ${MODEL_NAME}"
python3.12 -m venv ${VENV_NAME}
source ${VENV_NAME}/bin/activate

# Install minimal dependencies
print_heading "Installing core dependencies"
print_info "pip install --upgrade pip"
pip install --upgrade pip

print_info "Installing base packages..."
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
print_info "Installing pytest packages..."
pip install \
    pytest \
    pytest-asyncio \
    requests

# Change to agno directory
cd libs/agno

case $MODEL_NAME in
    "openai")
        if [ -z "${OPENAI_API_KEY}" ]; then
            print_heading "Error: OPENAI_API_KEY environment variable is not set"
            exit 1
        fi
        if [ -z "${EXA_API_KEY}" ]; then
            print_heading "Error: EXA_API_KEY environment variable is not set"
            exit 1
        fi
        ;;
    "google")
        if [ -z "${GOOGLE_API_KEY}" ]; then
            print_heading "Error: GOOGLE_API_KEY environment variable is not set"
            exit 1
        fi
        if [ -z "${GOOGLE_CLOUD_PROJECT}" ]; then
            print_heading "Error: GOOGLE_CLOUD_PROJECT environment variable is not set"
            exit 1
        fi
        ;;
    "anthropic")
        if [ -z "${ANTHROPIC_API_KEY}" ]; then
            print_heading "Error: ANTHROPIC_API_KEY environment variable is not set"
            exit 1
        fi
        ;;
    "aws")
        if [ -z "${AWS_ACCESS_KEY_ID}" ]; then
            print_heading "Error: AWS_ACCESS_KEY_ID environment variable is not set"
            exit 1
        fi
        if [ -z "${AWS_SECRET_ACCESS_KEY}" ]; then
            print_heading "Error: AWS_SECRET_ACCESS_KEY environment variable is not set"
            exit 1
        fi
        if [ -z "${AWS_REGION}" ]; then
            print_heading "Error: AWS_REGION environment variable is not set"
            exit 1
        fi
        ;;
    *)
        print_heading "Error: Unknown model ${MODEL_NAME}"
        exit 1
        ;;
esac

# Install agno with model and integration test dependencies
print_heading "Installing agno with ${MODEL_NAME} dependencies"
print_info "pip install -e .[${MODEL_NAME},integration-tests]"
pip install -e ".[${MODEL_NAME},integration-tests]"

# Run the tests
print_heading "Running ${MODEL_NAME} tests"
TEST_PATH="tests/integration/models/${MODEL_NAME}"
if [ -d "$TEST_PATH" ]; then
    print_info "Running tests in ${TEST_PATH}"
    python -m pytest ${TEST_PATH} -v
    TEST_EXIT_CODE=$?
else
    print_heading "Error: No tests found for ${MODEL_NAME} at ${TEST_PATH}"
    TEST_EXIT_CODE=1
fi

# Final status
print_heading "Test Results"
if [ $TEST_EXIT_CODE -eq 0 ]; then
    print_info "All ${MODEL_NAME} tests completed successfully!"
else
    print_info "Tests failed for ${MODEL_NAME}"
fi

exit $TEST_EXIT_CODE