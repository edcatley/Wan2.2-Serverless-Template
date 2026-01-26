#!/bin/bash
echo "============================================================"
echo "RunPod Local Orchestrator - Startup Script (Mac)"
echo "============================================================"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "[ERROR] Docker is not running!"
    echo "Please start Docker Desktop and try again."
    exit 1
fi
echo "[OK] Docker is running"

# Try to start Redis (will create if doesn't exist, or start if stopped)
echo "[INFO] Starting Redis container..."
if ! docker start redis > /dev/null 2>&1; then
    echo "[INFO] Redis container doesn't exist, creating..."
    if ! docker run -d -p 6379:6379 --name redis redis:7-alpine > /dev/null 2>&1; then
        echo "[ERROR] Failed to create Redis container"
        exit 1
    fi
    echo "[OK] Redis container created and started"
else
    echo "[OK] Redis container started"
fi

# Wait a moment for Redis to be ready
sleep 2

# Check if .env file exists
if [ ! -f .env ]; then
    echo "[WARNING] No .env file found!"
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "[INFO] Please edit .env with your configuration"
    read -p "Press Enter to continue anyway, or Ctrl+C to exit and configure first..."
fi

# Create/activate virtual environment
echo ""
if [ ! -d venv ]; then
    echo "[INFO] Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create virtual environment"
        exit 1
    fi
    echo "[OK] Virtual environment created"
fi

echo "[INFO] Activating virtual environment..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to activate virtual environment"
    exit 1
fi

# Install Python dependencies
echo "[INFO] Installing Python dependencies..."
pip install -q -r requirements.txt
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to install dependencies"
    exit 1
fi
echo "[OK] Dependencies installed"

# Start the orchestrator
echo ""
echo "============================================================"
echo "Starting RunPod Local Orchestrator"
echo "API will be available at: http://localhost:8001"
echo "Health check: http://localhost:8001/health"
echo ""
echo "Press Ctrl+C to stop"
echo "============================================================"
echo ""

python orchestrator.py
