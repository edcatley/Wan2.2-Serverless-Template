"""
Worker manager - spawns Docker containers to process jobs
"""
import docker
import redis
import json
import time
import os
import threading


class WorkerManager:
    def __init__(self, image_name="runpod-comfyui:latest", max_workers=3, redis_host="localhost", redis_port=6379):
        self.image_name = image_name
        self.max_workers = max_workers
        self.active_workers = 0
        self.worker_lock = threading.Lock()
        self.running = True
        
        self.docker_client = docker.from_env()
        print(f"[Worker Manager] Connected to Docker")
        
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.redis_client.ping()
        print(f"[Worker Manager] Connected to Redis at {redis_host}:{redis_port}")
        
        self.models_path = os.environ.get("MODELS_PATH", "")
        print(f"[Worker Manager] Image: {self.image_name}, Max workers: {self.max_workers}")
    
    def start(self):
        print(f"[Worker Manager] Starting job queue polling...")
        
        while self.running:
            try:
                with self.worker_lock:
                    can_process = self.active_workers < self.max_workers
                
                if can_process:
                    job_data = self.redis_client.brpop("runpod:queue", timeout=1)
                    
                    if job_data:
                        job = json.loads(job_data[1])
                        print(f"[Worker Manager] Picked up job {job['id']}")
                        
                        thread = threading.Thread(target=self._process_job, args=(job,), daemon=True)
                        thread.start()
                else:
                    time.sleep(0.5)
                    
            except KeyboardInterrupt:
                print(f"[Worker Manager] Shutting down...")
                self.running = False
                break
            except Exception as e:
                print(f"[Worker Manager] ERROR: {e}")
                time.sleep(1)
    
    def stop(self):
        self.running = False
    
    def _process_job(self, job):
        job_id = job["id"]
        
        with self.worker_lock:
            self.active_workers += 1
        
        print(f"[Worker {job_id}] Starting (active: {self.active_workers}/{self.max_workers})")
        
        started_at = time.time()
        self.redis_client.set(
            f"runpod:status:{job_id}",
            json.dumps({
                "status": "IN_PROGRESS",
                "created_at": job.get("created_at", started_at),
                "started_at": started_at
            }),
            ex=3600
        )
        
        container = None
        try:
            worker_id = f"local-worker-{job_id}"
            
            # Store job for this specific worker (don't put back in queue!)
            self.redis_client.set(
                f"runpod:worker:{worker_id}:job",
                json.dumps(job),
                ex=3600
            )
            
            # Set environment variables for RunPod SDK
            # These are the ONLY env vars the SDK actually uses (verified from SDK source code)
            env_vars = {
                "RUNPOD_POD_ID": worker_id,
                "RUNPOD_WEBHOOK_GET_JOB": f"http://host.docker.internal:8001/worker/{worker_id}/job?",
                "RUNPOD_WEBHOOK_POST_OUTPUT": f"http://host.docker.internal:8001/worker/{worker_id}/result?",
                "RUNPOD_AI_API_KEY": "local-test-key",
                "RUNPOD_PING_INTERVAL": "60000",  # Heartbeat interval in ms
                "RUNPOD_LOG_LEVEL": "INFO",  # DEBUG, INFO, WARN, ERROR
            }
            
            volumes = {}
            if self.models_path and os.path.exists(self.models_path):
                volumes[self.models_path] = {"bind": "/network-volume", "mode": "rw"}
                print(f"[Worker {job_id}] Mounting models from {self.models_path}")
            
            print(f"[Worker {job_id}] Starting container from {self.image_name}")
            
            # Try to use GPU if available
            device_requests = []
            try:
                # Check if NVIDIA runtime is available
                self.docker_client.containers.run(
                    "nvidia/cuda:11.8.0-base-ubuntu22.04",
                    "nvidia-smi",
                    remove=True,
                    device_requests=[docker.types.DeviceRequest(count=-1, capabilities=[['gpu']])]
                )
                device_requests = [docker.types.DeviceRequest(count=-1, capabilities=[['gpu']])]
                print(f"[Worker {job_id}] GPU support enabled")
            except Exception as e:
                print(f"[Worker {job_id}] No GPU support available, running CPU-only: {e}")
            
            container = self.docker_client.containers.run(
                self.image_name,
                environment=env_vars,
                detach=True,
                remove=False,
                volumes=volumes,
                mem_limit="8g",
                device_requests=device_requests,
            )
            
            print(f"[Worker {job_id}] Container {container.short_id} started, worker ID: {worker_id}")
            
            # Wait for the job to complete by polling Redis
            print(f"[Worker {job_id}] Waiting for job completion...")
            timeout = 300  # 5 minutes
            poll_interval = 2  # seconds
            elapsed = 0
            
            while elapsed < timeout:
                status_data = self.redis_client.get(f"runpod:status:{job_id}")
                if status_data:
                    status = json.loads(status_data)
                    if status.get("status") == "COMPLETED":
                        print(f"[Worker {job_id}] Job completed successfully")
                        break
                
                time.sleep(poll_interval)
                elapsed += poll_interval
            else:
                print(f"[Worker {job_id}] Job timed out after {timeout} seconds")
                self.redis_client.set(
                    f"runpod:result:{job_id}",
                    json.dumps({"error": f"Job timed out after {timeout} seconds"}),
                    ex=3600
                )
            
            # Give worker a few seconds to finish posting result and polling once more
            print(f"[Worker {job_id}] Waiting 5 seconds before stopping container...")
            time.sleep(5)
            
            # Now forcibly stop the container
            print(f"[Worker {job_id}] Stopping container...")
            try:
                container.stop(timeout=5)
            except:
                pass
            
            # Get container logs for debugging
            try:
                logs = container.logs().decode('utf-8', errors='replace')
                print(f"[Worker {job_id}] Container logs (last 500 chars):\n{logs[-500:]}")
            except:
                pass
            
            # Result should already be in Redis from the webhook
            # Just verify it's there
            result_data = self.redis_client.get(f"runpod:result:{job_id}")
            if not result_data:
                print(f"[Worker {job_id}] WARNING: No result found in Redis")
                self.redis_client.set(
                    f"runpod:result:{job_id}",
                    json.dumps({"error": "Worker did not post result"}),
                    ex=3600
                )
            
            # Clean up container
            try:
                container.remove(force=True)
                print(f"[Worker {job_id}] Container removed")
            except Exception as e:
                print(f"[Worker {job_id}] Failed to remove container: {e}")
                
        except docker.errors.ImageNotFound:
            error_msg = f"Docker image '{self.image_name}' not found"
            print(f"[Worker {job_id}] ERROR: {error_msg}")
            self.redis_client.set(f"runpod:result:{job_id}", json.dumps({"error": error_msg}), ex=3600)
        except Exception as e:
            error_msg = f"Failed to process job: {e}"
            print(f"[Worker {job_id}] ERROR: {error_msg}")
            self.redis_client.set(f"runpod:result:{job_id}", json.dumps({"error": error_msg}), ex=3600)
            
            if container:
                try:
                    container.remove(force=True)
                except:
                    pass
        finally:
            with self.worker_lock:
                self.active_workers -= 1
            print(f"[Worker {job_id}] Finished (active: {self.active_workers}/{self.max_workers})")
