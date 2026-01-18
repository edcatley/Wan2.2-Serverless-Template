"""
RunPod Local Orchestrator - Main entry point

Starts API server and worker manager in the same process.
"""
import threading
import time
import sys
import os
import uvicorn
from pathlib import Path
from dotenv import load_dotenv
from worker_manager import WorkerManager
import api

# Load .env file from same directory as this script
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
    print(f"[Orchestrator] Loaded environment from {env_path}")
else:
    print(f"[Orchestrator] No .env file found at {env_path}, using system environment")


def start_api_server(host="0.0.0.0", port=8000):
    """Start FastAPI server in current thread"""
    print(f"[Orchestrator] Starting API server on {host}:{port}")
    api.init_redis(host=os.environ.get("REDIS_HOST", "localhost"))
    uvicorn.run(api.app, host=host, port=port, log_level="info")


def start_worker_manager():
    """Start worker manager in current thread"""
    print(f"[Orchestrator] Starting worker manager")
    manager = WorkerManager(
        image_name=os.environ.get("RUNPOD_IMAGE", "runpod-comfyui:latest"),
        max_workers=int(os.environ.get("MAX_WORKERS", "3")),
        redis_host=os.environ.get("REDIS_HOST", "localhost")
    )
    manager.start()


def main():
    print("=" * 60)
    print("RunPod Local Orchestrator")
    print("=" * 60)
    
    # Check Redis is available
    try:
        import redis
        r = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), decode_responses=True)
        r.ping()
        print("[Orchestrator] Redis connection OK")
    except Exception as e:
        print(f"[Orchestrator] ERROR: Cannot connect to Redis: {e}")
        print("[Orchestrator] Make sure Redis is running:")
        print("  - Windows: Download from https://github.com/microsoftarchive/redis/releases")
        print("  - Or use Docker: docker run -d -p 6379:6379 redis")
        sys.exit(1)
    
    # Start API server in background thread
    api_thread = threading.Thread(target=start_api_server, daemon=True)
    api_thread.start()
    
    # Give API server time to start
    time.sleep(2)
    
    # Start worker manager in background thread
    worker_thread = threading.Thread(target=start_worker_manager, daemon=True)
    worker_thread.start()
    
    print("\n" + "=" * 60)
    print("Orchestrator running!")
    print("API: http://localhost:8000")
    print("Health: http://localhost:8000/health")
    print("Press Ctrl+C to stop")
    print("=" * 60 + "\n")
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Orchestrator] Shutting down...")
        sys.exit(0)


if __name__ == "__main__":
    main()
