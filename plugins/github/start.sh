#!/bin/bash
set -e

CONTAINER_NAME="atk-github-mcp"
IMAGE="ghcr.io/github/github-mcp-server"

# Check if container already exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  # Container exists - check if it's running
  if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Container ${CONTAINER_NAME} is already running"
    exit 0
  else
    # Container exists but stopped - start it
    echo "Starting existing container ${CONTAINER_NAME}..."
    docker start "$CONTAINER_NAME"
    echo "✓ Container started: ${CONTAINER_NAME}"
    exit 0
  fi
fi

# Container doesn't exist - create and start it
echo "Creating container ${CONTAINER_NAME}..."
docker create \
  --name "$CONTAINER_NAME" \
  -i \
  -e "GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_PERSONAL_ACCESS_TOKEN}" \
  -e "GITHUB_HOST=${GITHUB_HOST}" \
  "$IMAGE"

docker start "$CONTAINER_NAME"
echo "✓ Container created and started: ${CONTAINER_NAME}"

