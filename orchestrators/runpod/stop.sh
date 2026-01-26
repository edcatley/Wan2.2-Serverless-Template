#!/bin/bash
echo "============================================================"
echo "RunPod Local Orchestrator - Shutdown Script (Mac)"
echo "============================================================"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "[WARNING] Docker is not running, nothing to stop"
    exit 0
fi

# Kill any processes on port 8001 (orchestrator)
echo "[INFO] Stopping orchestrator processes on port 8001..."
lsof -ti:8001 | xargs kill -9 2>/dev/null
echo "[OK] Orchestrator processes stopped"

# Stop and remove Redis container
echo "[INFO] Stopping and removing Redis container..."
docker stop redis > /dev/null 2>&1
docker rm redis > /dev/null 2>&1
echo "[OK] Redis container stopped and removed"

# Find and stop all RunPod worker containers
echo ""
echo "[INFO] Looking for RunPod worker containers..."

# Stop containers using the ghcr image
for container in $(docker ps --filter "ancestor=ghcr.io/edcatley/wan2.2-serverless-template:runpod-latest" --format "{{.ID}}" 2>/dev/null); do
    echo "[INFO] Stopping container $container..."
    docker stop "$container" > /dev/null 2>&1
    docker rm "$container" > /dev/null 2>&1
    echo "[OK] Container $container stopped and removed"
done

# Also check for local image name
for container in $(docker ps --filter "ancestor=runpod-comfyui:latest" --format "{{.ID}}" 2>/dev/null); do
    echo "[INFO] Stopping container $container..."
    docker stop "$container" > /dev/null 2>&1
    docker rm "$container" > /dev/null 2>&1
    echo "[OK] Container $container stopped and removed"
done

echo ""
echo "============================================================"
echo "Cleanup complete!"
echo ""
echo "Orchestrator: stopped"
echo "Redis container: stopped and removed"
echo "Worker containers: stopped and removed"
echo "============================================================"
