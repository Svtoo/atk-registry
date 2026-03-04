#!/bin/bash

IMAGE="ghcr.io/github/github-mcp-server"

if docker image inspect "$IMAGE" &>/dev/null; then
  docker rmi "$IMAGE"
  echo "✓ Removed image: ${IMAGE}"
else
  echo "Image not present, nothing to remove."
fi

