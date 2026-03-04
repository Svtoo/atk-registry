#!/bin/bash
set -e

IMAGE="ghcr.io/github/github-mcp-server"

if ! command -v docker &>/dev/null; then
  echo "ERROR: Docker is required but not installed."
  echo "  https://docs.docker.com/get-docker/"
  exit 1
fi

if ! docker info &>/dev/null; then
  echo "ERROR: Docker is installed but not running."
  echo "  Please start Docker Desktop (or the Docker daemon) and try again."
  exit 1
fi

echo "Pulling ${IMAGE}..."
docker pull "$IMAGE"
echo "✓ Image ready: ${IMAGE}"

