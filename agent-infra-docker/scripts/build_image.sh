#!/bin/bash

############################################################################
# Script to build the Docker image using Docker Buildx.
#
# Instructions:
# 1. Set the IMAGE_NAME and IMAGE_TAG variables to the desired values.
# 2. Ensure Docker Buildx is installed and configured.
# 3. Run 'docker buildx create --use' before executing this script.
#
# This script builds a multi-platform Docker image for linux/amd64 and linux/arm64.
# The image is tagged and pushed to the specified repository.
############################################################################

# Exit immediately if a command exits with a non-zero status.
set -e

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS_ROOT="$(dirname ${CURR_DIR})"
DOCKER_FILE="Dockerfile"
IMAGE_NAME="agent-os"
IMAGE_TAG="latest"

echo "Running: docker buildx build --platform=linux/amd64,linux/arm64 -t $IMAGE_NAME:$IMAGE_TAG -f $DOCKER_FILE $OS_ROOT --push"
docker buildx build --platform=linux/amd64,linux/arm64 -t $IMAGE_NAME:$IMAGE_TAG -f $DOCKER_FILE $OS_ROOT --push
