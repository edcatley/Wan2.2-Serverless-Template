@echo off
echo ============================================================
echo RunPod Local Orchestrator - Shutdown Script
echo ============================================================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Docker is not running, nothing to stop
    pause
    exit /b 0
)

REM Kill any Python processes on port 8001 (orchestrator)
echo [INFO] Stopping orchestrator processes on port 8001...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8001 ^| findstr LISTENING') do (
    echo [INFO] Killing process %%a...
    taskkill /F /PID %%a >nul 2>&1
)
echo [OK] Orchestrator processes stopped

REM Stop and remove Redis container
echo [INFO] Stopping and removing Redis container...
docker stop redis >nul 2>&1
docker rm redis >nul 2>&1
if errorlevel 1 (
    echo [INFO] Redis container not found or already removed
) else (
    echo [OK] Redis container stopped and removed
)

REM Find and stop all RunPod worker containers
echo.
echo [INFO] Looking for RunPod worker containers...
for /f "tokens=*" %%i in ('docker ps --filter "ancestor=runpod-comfyui:latest" --format "{{.ID}}"') do (
    echo [INFO] Stopping container %%i...
    docker stop %%i
    docker rm %%i
    echo [OK] Container %%i stopped and removed
)

REM Also check for any containers using the base image
for /f "tokens=*" %%i in ('docker ps --filter "ancestor=comfyui-base:latest" --format "{{.ID}}"') do (
    echo [INFO] Stopping container %%i...
    docker stop %%i
    docker rm %%i
    echo [OK] Container %%i stopped and removed
)

echo.
echo ============================================================
echo Cleanup complete!
echo.
echo Orchestrator: stopped
echo Redis container: stopped and removed
echo Worker containers: stopped and removed
echo ============================================================
echo.
pause
