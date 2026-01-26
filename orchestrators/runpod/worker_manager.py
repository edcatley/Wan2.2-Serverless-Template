"""
Worker manager - spawns Docker containers to process jobs
"""
import docker
import redis
import json
import time
import os
import threading
from state_manager import StateManager


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
        
        self.state_manager = StateManager(self.redis_client)
        
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
        
        # Note: Don't set IN_PROGRESS here - the API does it when worker picks up the job
        # We just need to track started_at for our own timeout logic
        started_at = time.time()
        
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
                "RUNPOD_LOG_LEVEL": "DEBUG",  # DEBUG, INFO, WARN, ERROR
                # Increased timeouts for Rosetta/CPU mode (ComfyUI takes longer to start)
                "COMFY_API_AVAILABLE_MAX_RETRIES": "2400",  # 2400 * 50ms = 120 seconds
                "COMFY_API_AVAILABLE_INTERVAL_MS": "100",   # Check every 100ms
            }
            
            volumes = {}
            if self.models_path and os.path.exists(self.models_path):
                volumes[self.models_path] = {"bind": "/network-volume", "mode": "rw"}
                print(f"[Worker {job_id}] Mounting models from {self.models_path}")
            
            print(f"[Worker {job_id}] Starting container from {self.image_name}")
            
            # Try to use GPU if available
            device_requests = None  # None means don't request GPU at all
            use_gpu = False
            try:
                # Check if NVIDIA runtime is available
                self.docker_client.containers.run(
                    "nvidia/cuda:11.8.0-base-ubuntu22.04",
                    "nvidia-smi",
                    remove=True,
                    device_requests=[docker.types.DeviceRequest(count=-1, capabilities=[['gpu']])]
                )
                device_requests = [docker.types.DeviceRequest(count=-1, capabilities=[['gpu']])]
                use_gpu = True
                print(f"[Worker {job_id}] GPU support enabled")
            except Exception as e:
                print(f"[Worker {job_id}] No GPU support available, running CPU-only (Rosetta mode)")
            
            # Build container run kwargs
            run_kwargs = {
                "image": self.image_name,
                "environment": env_vars,
                "detach": True,
                "remove": False,
                "volumes": volumes if volumes else None,
                "mem_limit": "8g",
            }
            
            # Only add device_requests if GPU is available
            if use_gpu and device_requests:
                run_kwargs["device_requests"] = device_requests
            
            # For Mac/ARM with x86 images (like GHCR CUDA image), force Rosetta emulation
            # Skip this for local CPU images which are built for ARM natively
            import platform
            is_arm_mac = platform.machine() == 'arm64' or platform.system() == 'Darwin'
            is_remote_image = self.image_name.startswith('ghcr.io/') or 'cuda' in self.image_name.lower()
            
            if is_arm_mac and is_remote_image:
                run_kwargs["platform"] = "linux/amd64"
                print(f"[Worker {job_id}] Running with platform=linux/amd64 (Rosetta)")
            else:
                print(f"[Worker {job_id}] Running with native platform")
            
            container = self.docker_client.containers.run(**run_kwargs)
            
            print(f"[Worker {job_id}] Container {container.short_id} started, worker ID: {worker_id}")
            
            # Wait for the job to complete by polling Redis
            print(f"[Worker {job_id}] Waiting for job completion...")
            timeout = 600  # 10 minutes
            poll_interval = 1  # seconds (faster polling)
            elapsed = 0
            job_finished = False
            
            while elapsed < timeout:
                # Check if container is still running
                try:
                    container.reload()
                    if container.status not in ['running', 'created']:
                        print(f"[Worker {job_id}] Container stopped unexpectedly with status: {container.status}")
                        # Check if result was posted before container died
                        result_data = self.redis_client.get(f"runpod:result:{job_id}")
                        if not result_data:
                            # Set error result
                            self.redis_client.set(
                                f"runpod:result:{job_id}",
                                json.dumps({"error": f"Container stopped with status: {container.status}"}),
                                ex=3600
                            )
                            # Transition to FAILED state
                            self.state_manager.transition_state(
                                job_id,
                                "FAILED",
                                metadata={
                                    "created_at": job.get("created_at", started_at),
                                    "started_at": started_at,
                                    "completed_at": time.time()
                                }
                            )
                        break
                except Exception as e:
                    print(f"[Worker {job_id}] Error checking container status: {e}")
                
                # Check Redis for completion
                status_data = self.redis_client.get(f"runpod:status:{job_id}")
                if status_data:
                    status = json.loads(status_data)
                    job_status = status.get("status")
                    
                    # Check for any terminal status
                    if job_status in ["COMPLETED", "FAILED", "CANCELLED"]:
                        print(f"[Worker {job_id}] Job finished with status: {job_status}")
                        job_finished = True
                        break
                
                time.sleep(poll_interval)
                elapsed += poll_interval
            
            if not job_finished and elapsed >= timeout:
                print(f"[Worker {job_id}] Job timed out after {timeout} seconds")
                
                # Set error result
                self.redis_client.set(
                    f"runpod:result:{job_id}",
                    json.dumps({"error": f"Job timed out after {timeout} seconds"}),
                    ex=3600
                )
                
                # Transition to TIMED_OUT state
                self.state_manager.transition_state(
                    job_id,
                    "TIMED_OUT",
                    metadata={
                        "created_at": job.get("created_at", started_at),
                        "started_at": started_at,
                        "completed_at": time.time()
                    }
                )
            
            # Give worker a moment to finish any final operations
            if job_finished:
                print(f"[Worker {job_id}] Waiting 2 seconds for final cleanup...")
                time.sleep(2)
            else:
                # DEBUG: Keep container alive for inspection via Docker Desktop
                print(f"[Worker {job_id}] Job failed - keeping container alive for 5 minutes for debugging...")
                print(f"[Worker {job_id}] Check Docker Desktop logs, or run: docker logs <container_id>")
                time.sleep(300)  # 5 minutes
            
            # Stop the container
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
                # Transition to FAILED state
                self.state_manager.transition_state(
                    job_id,
                    "FAILED",
                    metadata={
                        "created_at": job.get("created_at", started_at),
                        "started_at": started_at,
                        "completed_at": time.time()
                    }
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
            self.state_manager.transition_state(
                job_id,
                "FAILED",
                metadata={
                    "created_at": job.get("created_at", time.time()),
                    "started_at": time.time(),
                    "completed_at": time.time()
                }
            )
        except Exception as e:
            error_msg = f"Failed to process job: {e}"
            print(f"[Worker {job_id}] ERROR: {error_msg}")
            self.redis_client.set(f"runpod:result:{job_id}", json.dumps({"error": error_msg}), ex=3600)
            self.state_manager.transition_state(
                job_id,
                "FAILED",
                metadata={
                    "created_at": job.get("created_at", time.time()),
                    "started_at": time.time(),
                    "completed_at": time.time()
                }
            )
            
            if container:
                try:
                    container.remove(force=True)
                except:
                    pass
        finally:
            with self.worker_lock:
                self.active_workers -= 1
            print(f"[Worker {job_id}] Finished (active: {self.active_workers}/{self.max_workers})")
