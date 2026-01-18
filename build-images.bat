@echo off
echo ============================================================
echo Docker Image Build Script
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
echo.

REM Build base image
echo ============================================================
echo Building base image: comfyui-base:latest
echo ============================================================
echo.
docker build -t comfyui-base:latest .
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to build base image
    pause
    exit /b 1
)
echo.
echo [OK] Base image built successfully
echo.

REM Build RunPod image
echo ============================================================
echo Building RunPod image: runpod-comfyui:latest
echo ============================================================
echo.
docker build -t runpod-comfyui:latest -f runpod/Dockerfile --build-arg BASE_IMAGE_NAME=comfyui-base:latest runpod/
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to build RunPod image
    pause
    exit /b 1
)
echo.
echo [OK] RunPod image built successfully
echo.

REM Show built images
echo ============================================================
echo Build Complete! Images created:
echo ============================================================
docker images | findstr "comfyui-base\|runpod-comfyui"
echo.
echo You can now run the orchestrator:
echo   cd orchestrators\runpod
echo   start.bat
echo.
pause
