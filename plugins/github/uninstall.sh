#!/bin/bash

CONTAINER_NAME="atk-github-mcp"
IMAGE="ghcr.io/github/github-mcp-server"

# Remove container if it exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Removing container ${CONTAINER_NAME}..."
  docker rm -f "$CONTAINER_NAME"
  echo "✓ Removed container: ${CONTAINER_NAME}"
fi

# Remove image if it exists
if docker image inspect "$IMAGE" &>/dev/null; then
  docker rmi "$IMAGE"
  echo "✓ Removed image: ${IMAGE}"
else
  echo "Image not present, nothing to remove."
fi

