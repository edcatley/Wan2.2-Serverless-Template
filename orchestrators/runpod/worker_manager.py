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
            env_vars = {
                "JOB_ID": job_id,
                "JOB_INPUT": json.dumps(job["input"]),
                "RUNPOD_POD_ID": "local-pod-001",
                "RUNPOD_ENDPOINT_ID": "local-endpoint",
            }
            
            volumes = {}
            if self.models_path and os.path.exists(self.models_path):
                volumes[self.models_path] = {"bind": "/network-volume", "mode": "rw"}
                print(f"[Worker {job_id}] Mounting models from {self.models_path}")
            
            print(f"[Worker {job_id}] Starting container from {self.image_name}")
            container = self.docker_client.containers.run(
                self.image_name,
                environment=env_vars,
                detach=True,
                remove=False,
                volumes=volumes,
                mem_limit="8g",
            )
            
            print(f"[Worker {job_id}] Container {container.short_id} started")
            
            result = container.wait()
            exit_code = result.get("StatusCode", -1)
            logs = container.logs().decode('utf-8', errors='replace')
            
            completed_at = time.time()
            
            if exit_code == 0:
                print(f"[Worker {job_id}] Container completed successfully")
                
                # Extract result from logs between markers
                if "=== RESULT START ===" in logs and "=== RESULT END ===" in logs:
                    start = logs.index("=== RESULT START ===") + len("=== RESULT START ===")
                    end = logs.index("=== RESULT END ===")
                    result_json = logs[start:end].strip()
                    
                    self.redis_client.set(f"runpod:result:{job_id}", result_json, ex=3600)
                    self.redis_client.set(
                        f"runpod:status:{job_id}",
                        json.dumps({
                            "status": "COMPLETED",
                            "created_at": job.get("created_at", started_at),
                            "started_at": started_at,
                            "completed_at": completed_at
                        }),
                        ex=3600
                    )
                else:
                    print(f"[Worker {job_id}] WARNING: No result markers found in logs")
                    self.redis_client.set(
                        f"runpod:result:{job_id}",
                        json.dumps({"error": "No result found in container output"}),
                        ex=3600
                    )
            else:
                print(f"[Worker {job_id}] Container failed with exit code {exit_code}")
                self.redis_client.set(
                    f"runpod:result:{job_id}",
                    json.dumps({"error": f"Container exited with code {exit_code}", "logs": logs[-1000:]}),
                    ex=3600
                )
                self.redis_client.set(
                    f"runpod:status:{job_id}",
                    json.dumps({
                        "status": "FAILED",
                        "created_at": job.get("created_at", started_at),
                        "started_at": started_at,
                        "completed_at": completed_at
                    }),
                    ex=3600
                )
            
            try:
                container.remove()
            except:
                pass
                
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
