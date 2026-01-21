"""
RunPod API endpoint handlers
"""
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Any, Optional
import redis
import json
import uuid
import asyncio
import time
import os

app = FastAPI(title="RunPod Local Orchestrator")
redis_client = None


@app.on_event("startup")
async def startup_event():
    """Initialize Redis connection on startup"""
    global redis_client
    redis_host = os.environ.get("REDIS_HOST", "localhost")
    redis_port = int(os.environ.get("REDIS_PORT", "6379"))
    redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
    print(f"[API] Connected to Redis at {redis_host}:{redis_port}")


def init_redis(host='localhost', port=6379):
    """Legacy function for manual initialization"""
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)


class RunRequest(BaseModel):
    input: Dict[str, Any]
    webhook: Optional[str] = None


@app.get("/health")
async def health():
    try:
        redis_client.ping()
        
        # Get actual queue stats
        queue_length = redis_client.llen("runpod:queue")
        
        # Count jobs by status
        in_progress = 0
        completed = 0
        failed = 0
        
        # Get all status keys
        status_keys = redis_client.keys("runpod:status:*")
        for key in status_keys:
            status_data = redis_client.get(key)
            if status_data:
                status = json.loads(status_data)
                job_status = status.get("status")
                if job_status == "IN_PROGRESS":
                    in_progress += 1
                elif job_status == "COMPLETED":
                    completed += 1
                elif job_status == "FAILED":
                    failed += 1
        
        return {
            "status": "running",
            "jobs": {
                "completed": completed,
                "failed": failed,
                "inProgress": in_progress,
                "inQueue": queue_length,
                "retried": 0
            },
            "workers": {
                "idle": 0,
                "running": in_progress,  # Approximate: 1 worker per in-progress job
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


# -------------------------------- Worker Webhook Endpoints -------------------------------- #

@app.get("/worker/{worker_id}/job")
async def get_job_for_worker(worker_id: str, job_in_progress: str = "0"):
    """
    Worker polls this endpoint to get a job.
    Mimics RunPod's RUNPOD_WEBHOOK_GET_JOB endpoint with long-polling.
    
    Query params:
    - job_in_progress: "0" or "1" indicating if worker has a job in progress
    """
    # Long-polling: wait up to 30 seconds for a job to become available
    max_wait = 30  # seconds
    poll_interval = 0.5  # seconds
    elapsed = 0
    
    while elapsed < max_wait:
        # Check if this worker has a job assigned
        job_data = redis_client.get(f"runpod:worker:{worker_id}:job")
        
        if job_data:
            job = json.loads(job_data)
            job_id = job["id"]
            
            # Delete the job assignment so worker doesn't get it again
            redis_client.delete(f"runpod:worker:{worker_id}:job")
            
            # Update status to IN_PROGRESS
            redis_client.set(
                f"runpod:status:{job_id}",
                json.dumps({
                    "status": "IN_PROGRESS",
                    "created_at": job.get("created_at", time.time()),
                    "started_at": time.time(),
                    "worker_id": worker_id
                }),
                ex=3600
            )
            
            print(f"[API] Worker {worker_id} picked up job {job_id}")
            
            # Return job in RunPod format
            return {
                "id": job_id,
                "input": job["input"]
            }
        
        # No job yet, wait a bit before checking again
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    
    # No job available after waiting - return 204 No Content
    from fastapi import Response
    return Response(status_code=204)


@app.post("/worker/{worker_id}/result")
async def receive_result_from_worker(worker_id: str, request: Request, isStream: str = "false"):
    """
    Worker posts results to this endpoint.
    Mimics RunPod's RUNPOD_WEBHOOK_POST_OUTPUT endpoint.
    
    Query params:
    - isStream: "true" or "false" indicating if this is a streaming update
    """
    print(f"\n{'='*80}")
    print(f"[API] *** INCOMING POST *** to /worker/{worker_id}/result")
    print(f"[API] Full URL: {request.url}")
    print(f"[API] Headers: {dict(request.headers)}")
    print(f"[API] isStream: {isStream}")
    print(f"{'='*80}\n")
    print(f"[API] Starting to read body...")
    
    # Get raw body to see what SDK is sending
    try:
        body = await request.body()
        body_str = body.decode('utf-8')
        print(f"[API] Body length: {len(body_str)} bytes")
        print(f"[API] Body preview: {body_str[:500]}")
    except Exception as e:
        print(f"[API] ERROR reading body: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to read body: {e}")
    
    try:
        result = json.loads(body_str)
        print(f"[API] Successfully parsed JSON")
    except Exception as e:
        print(f"[API] ERROR: Failed to parse result JSON: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    
    # The SDK might send different formats, be flexible
    # Could be: {"output": {...}} or {"id": "...", "output": {...}} or just the output directly
    job_id = result.get("id") or result.get("job_id")
    
    # If no job_id in result, try to find it from worker's current job
    if not job_id:
        # Check what job this worker was assigned
        status_keys = redis_client.keys(f"runpod:status:*")
        for key in status_keys:
            status_data = redis_client.get(key)
            if status_data:
                status = json.loads(status_data)
                if status.get("worker_id") == worker_id and status.get("status") == "IN_PROGRESS":
                    job_id = key.replace("runpod:status:", "")
                    print(f"[API] Inferred job_id {job_id} from worker {worker_id}")
                    break
    
    if not job_id:
        print(f"[API] ERROR: Could not determine job_id from result: {result}")
        raise HTTPException(status_code=400, detail="Missing job id in result")
    
    completed_at = time.time()
    
    # Get the job status to retrieve created_at and started_at
    status_data = redis_client.get(f"runpod:status:{job_id}")
    if status_data:
        status = json.loads(status_data)
    else:
        status = {"created_at": completed_at, "started_at": completed_at}
    
    # Extract output - could be nested or at root level
    output = result.get("output", result)
    
    # Check if this is an error result
    has_error = "error" in output or "errors" in output
    final_status = "FAILED" if has_error else "COMPLETED"
    
    # Store the result
    redis_client.set(
        f"runpod:result:{job_id}",
        json.dumps(output),
        ex=3600
    )
    
    # Update status to COMPLETED or FAILED
    redis_client.set(
        f"runpod:status:{job_id}",
        json.dumps({
            "status": final_status,
            "created_at": status.get("created_at", completed_at),
            "started_at": status.get("started_at", completed_at),
            "completed_at": completed_at,
            "worker_id": worker_id
        }),
        ex=3600
    )
    
    print(f"[API] Worker {worker_id} completed job {job_id} with status: {final_status}")
    
    return {"status": "success"}
