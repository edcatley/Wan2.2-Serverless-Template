"""
RunPod API endpoint handlers
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
import redis
import json
import uuid
import asyncio
import time

app = FastAPI(title="RunPod Local Orchestrator")
redis_client = None


def init_redis(host='localhost', port=6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)


class RunRequest(BaseModel):
    input: Dict[str, Any]
    webhook: Optional[str] = None


@app.get("/health")
async def health():
    try:
        redis_client.ping()
        
        # Get queue stats
        queue_length = redis_client.llen("runpod:queue")
        
        return {
            "status": "running",
            "jobs": {
                "completed": 0,
                "failed": 0,
                "inProgress": 0,
                "inQueue": queue_length,
                "retried": 0
            },
            "workers": {
                "idle": 0,
                "running": 0,
                "throttled": 0
            }
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {e}")


@app.post("/run")
async def run_async(request: RunRequest):
    job_id = str(uuid.uuid4())
    
    job_data = {
        "id": job_id,
        "input": request.input,
        "webhook": request.webhook,
        "created_at": time.time()
    }
    
    redis_client.lpush("runpod:queue", json.dumps(job_data))
    redis_client.set(
        f"runpod:status:{job_id}",
        json.dumps({
            "status": "IN_QUEUE",
            "created_at": job_data["created_at"]
        }),
        ex=3600
    )
    
    print(f"[API] Queued job {job_id}")
    
    return {
        "id": job_id,
        "status": "IN_QUEUE"
    }


@app.post("/runsync")
async def run_sync(request: RunRequest):
    job_id = str(uuid.uuid4())
    
    job_data = {
        "id": job_id,
        "input": request.input,
        "created_at": time.time()
    }
    
    redis_client.lpush("runpod:queue", json.dumps(job_data))
    redis_client.set(
        f"runpod:status:{job_id}",
        json.dumps({
            "status": "IN_QUEUE",
            "created_at": job_data["created_at"]
        }),
        ex=3600
    )
    
    print(f"[API] Queued sync job {job_id}, waiting for result...")
    
    # Wait for result (default 60 seconds, max 300)
    timeout = 300
    for _ in range(timeout):
        result = redis_client.get(f"runpod:result:{job_id}")
        if result:
            result_data = json.loads(result)
            status_data = redis_client.get(f"runpod:status:{job_id}")
            status = json.loads(status_data) if status_data else {}
            
            print(f"[API] Job {job_id} completed")
            
            return {
                "delayTime": int((status.get("started_at", time.time()) - job_data["created_at"]) * 1000),
                "executionTime": int((status.get("completed_at", time.time()) - status.get("started_at", time.time())) * 1000),
                "id": job_id,
                "output": result_data,
                "status": "COMPLETED"
            }
        await asyncio.sleep(1)
    
    raise HTTPException(status_code=408, detail=f"Job {job_id} timed out after {timeout} seconds")


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    # Check if completed
    result = redis_client.get(f"runpod:result:{job_id}")
    status_data = redis_client.get(f"runpod:status:{job_id}")
    
    if not status_data:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    status = json.loads(status_data)
    
    if result:
        result_data = json.loads(result)
        return {
            "delayTime": int((status.get("started_at", time.time()) - status.get("created_at", time.time())) * 1000),
            "executionTime": int((status.get("completed_at", time.time()) - status.get("started_at", time.time())) * 1000),
            "id": job_id,
            "output": result_data,
            "status": "COMPLETED"
        }
    
    # Still in progress or queued
    response = {
        "id": job_id,
        "status": status.get("status", "IN_QUEUE")
    }
    
    if status.get("started_at"):
        response["delayTime"] = int((status["started_at"] - status.get("created_at", time.time())) * 1000)
    
    return response


@app.post("/cancel/{job_id}")
async def cancel_job(job_id: str):
    status_data = redis_client.get(f"runpod:status:{job_id}")
    if not status_data:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    redis_client.set(
        f"runpod:status:{job_id}",
        json.dumps({"status": "CANCELLED"}),
        ex=3600
    )
    
    print(f"[API] Cancelled job {job_id}")
    
    return {
        "id": job_id,
        "status": "CANCELLED"
    }


@app.post("/purge-queue")
async def purge_queue():
    removed = redis_client.delete("runpod:queue")
    
    print(f"[API] Purged queue, removed {removed} jobs")
    
    return {
        "removed": removed,
        "status": "completed"
    }
