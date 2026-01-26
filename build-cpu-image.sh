#!/bin/bash
echo "============================================================"
echo "Building CPU-only ComfyUI image for local Mac testing"
echo "============================================================"
echo ""

# Build the image
docker build -f Dockerfile.cpu -t runpod-comfyui-cpu:latest .

if [ $? -eq 0 ]; then
    echo ""
    echo "============================================================"
    echo "Build successful!"
    echo ""
    echo "Image: runpod-comfyui-cpu:latest"
    echo ""
    echo "To use with orchestrator, update .env:"
    echo "  RUNPOD_IMAGE=runpod-comfyui-cpu:latest"
    echo "============================================================"
else
    echo ""
    echo "Build failed!"
    exit 1
fi
