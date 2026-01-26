#!/bin/bash
echo "========================================"
echo "Setting up test environment"
echo "========================================"

# Change to script directory
cd "$(dirname "$0")"

# Check if venv exists, create if not
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create virtual environment"
        exit 1
    fi
    echo "Virtual environment created."
else
    echo "Virtual environment already exists."
fi

# Activate venv
echo "Activating virtual environment..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to activate virtual environment"
    exit 1
fi

# Install/upgrade requirements
echo "Installing requirements..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install requirements"
    exit 1
fi

echo ""
echo "========================================"
echo "Running test_preprocessing_workflow.py"
echo "========================================"
echo ""

# Run the test (start with preprocessing, not action)
python test_action_workflow.py

echo ""
echo "========================================"
echo "Test complete"
echo "========================================"
