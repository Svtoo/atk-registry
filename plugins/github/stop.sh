#!/bin/bash
set -e

CONTAINER_NAME="atk-github-mcp"

# Check if container exists
if ! docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Container ${CONTAINER_NAME} does not exist"
  exit 0
fi

# Check if container is running
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Stopping container ${CONTAINER_NAME}..."
  docker stop "$CONTAINER_NAME"
  echo "✓ Container stopped: ${CONTAINER_NAME}"
else
  echo "Container ${CONTAINER_NAME} is already stopped"
fi

