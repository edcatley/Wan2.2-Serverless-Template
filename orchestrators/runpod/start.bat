@echo off
echo ============================================================
echo RunPod Local Orchestrator - Startup Script
echo ============================================================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running!
    echo Please start Docker Desktop and try again.
    pause
    exit /b 1
)
echo [OK] Docker is running

REM Try to start Redis (will create if doesn't exist, or start if stopped)
echo [INFO] Starting Redis container...
docker start redis >nul 2>&1
if errorlevel 1 (
    echo [INFO] Redis container doesn't exist, creating...
    docker run -d -p 6379:6379 --name redis redis:7-alpine >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Failed to create Redis container
        pause
        exit /b 1
    )
    echo [OK] Redis container created and started
) else (
    echo [OK] Redis container started
)

REM Wait a moment for Redis to be ready
timeout /t 2 /nobreak >nul

REM Check if .env file exists
if not exist .env (
    echo [WARNING] No .env file found!
    echo Creating .env from .env.example...
    copy .env.example .env >nul
    echo [INFO] Please edit .env with your configuration
    echo Press any key to continue anyway, or Ctrl+C to exit and configure first
    pause
)

REM Create/activate virtual environment
echo.
if not exist venv (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
)

echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment
    pause
    exit /b 1
)

REM Install Python dependencies
echo [INFO] Installing Python dependencies...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo [OK] Dependencies installed

REM Start the orchestrator
echo.
echo ============================================================
echo Starting RunPod Local Orchestrator
echo API will be available at: http://localhost:8001
echo Health check: http://localhost:8001/health
echo.
echo Press Ctrl+C to stop
echo ============================================================
echo.

python orchestrator.py


