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

REM Check if Redis container exists
docker ps -a --filter "name=redis" --format "{{.Names}}" | findstr /x "redis" >nul
if errorlevel 1 (
    echo [INFO] Creating Redis container...
    docker run -d -p 6379:6379 --name redis redis:7-alpine
    if errorlevel 1 (
        echo [ERROR] Failed to create Redis container
        pause
        exit /b 1
    )
    echo [OK] Redis container created
) else (
    REM Container exists, check if it's running
    docker ps --filter "name=redis" --format "{{.Names}}" | findstr /x "redis" >nul
    if errorlevel 1 (
        echo [INFO] Starting existing Redis container...
        docker start redis
        if errorlevel 1 (
            echo [ERROR] Failed to start Redis container
            pause
            exit /b 1
        )
        echo [OK] Redis container started
    ) else (
        echo [OK] Redis container already running
    )
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

REM Install Python dependencies
echo.
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
echo API will be available at: http://localhost:8000
echo Health check: http://localhost:8000/health
echo.
echo Press Ctrl+C to stop
echo ============================================================
echo.

python orchestrator.py

REM If orchestrator exits, ask if user wants to stop Redis
echo.
echo Orchestrator stopped.
set /p STOP_REDIS="Stop Redis container? (y/n): "
if /i "%STOP_REDIS%"=="y" (
    echo Stopping Redis...
    docker stop redis
    echo Redis stopped. Container still exists, will restart next time.
)
