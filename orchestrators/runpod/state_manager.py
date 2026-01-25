"""
Centralized state management and webhook notifications for jobs
"""
import redis
import json
import time
import requests
import threading
from typing import Optional, Dict, Any


class StateManager:
    """Manages job state transitions and webhook notifications"""
    
    # Valid job states
    STATES = {
        "IN_QUEUE",
        "IN_PROGRESS", 
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT"
    }
    
    # Terminal states (job is finished)
    TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}
    
    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client
    
    def transition_state(
        self,
        job_id: str,
        new_state: str,
        metadata: Optional[Dict[str, Any]] = None,
        webhook_url: Optional[str] = None
    ) -> bool:
        """
        Transition a job to a new state and trigger webhook notification.
        
        Args:
            job_id: The job ID
            new_state: The new state (must be in STATES)
            metadata: Additional metadata to store with the state (timestamps, etc.)
            webhook_url: Optional webhook URL to notify (if not provided, will check job data)
        
        Returns:
            bool: True if transition was successful
        """
        if new_state not in self.STATES:
            print(f"[StateManager] ERROR: Invalid state '{new_state}'")
            return False
        
        print(f"[StateManager] ===== STATE TRANSITION START =====")
        print(f"[StateManager] Job ID: {job_id}")
        print(f"[StateManager] New State: {new_state}")
        print(f"[StateManager] Metadata: {metadata}")
        print(f"[StateManager] Webhook URL (provided): {webhook_url}")
        
        # Get current state
        status_key = f"runpod:status:{job_id}"
        current_status_data = self.redis_client.get(status_key)
        current_state = None
        
        if current_status_data:
            current_status = json.loads(current_status_data)
            current_state = current_status.get("status")
            print(f"[StateManager] Current State: {current_state}")
        else:
            print(f"[StateManager] Current State: None (new job)")
        
        # Build new status data
        status_data = metadata or {}
        status_data["status"] = new_state
        
        # Preserve timestamps from previous state
        if current_status_data:
            current_status = json.loads(current_status_data)
            for key in ["created_at", "started_at"]:
                if key in current_status and key not in status_data:
                    status_data[key] = current_status[key]
        
        # Add completion timestamp for terminal states
        if new_state in self.TERMINAL_STATES and "completed_at" not in status_data:
            status_data["completed_at"] = time.time()
        
        # Update Redis
        self.redis_client.set(status_key, json.dumps(status_data), ex=3600)
        
        print(f"[StateManager] Job {job_id}: {current_state or 'UNKNOWN'} -> {new_state}")
        print(f"[StateManager] Status data saved to Redis: {status_data}")
        
        # Get webhook URL if not provided
        if not webhook_url:
            print(f"[StateManager] No webhook URL provided, checking job data...")
            # Try to get from job data
            job_data_str = self.redis_client.get(f"runpod:job:{job_id}")
            if job_data_str:
                job_data = json.loads(job_data_str)
                webhook_url = job_data.get("webhook") or job_data.get("webhookV2")
                print(f"[StateManager] Webhook URL from job data: {webhook_url}")
            else:
                print(f"[StateManager] No job data found in Redis for key: runpod:job:{job_id}")
        
        # Trigger webhook notification in background
        if webhook_url:
            print(f"[StateManager] Starting webhook notification thread...")
            thread = threading.Thread(
                target=self._notify_webhook,
                args=(job_id, new_state, status_data, webhook_url),
                daemon=True
            )
            thread.start()
            print(f"[StateManager] Webhook thread started")
        else:
            print(f"[StateManager] No webhook URL available, skipping notification")
        
        print(f"[StateManager] ===== STATE TRANSITION END =====\n")
        
        return True
    
    def _notify_webhook(
        self,
        job_id: str,
        state: str,
        status_data: Dict[str, Any],
        webhook_url: str
    ):
        """
        Send webhook notification with retry logic.
        
        Retries up to 3 times with 10 second delays between attempts.
        """
        print(f"\n[StateManager/Webhook] ===== WEBHOOK NOTIFICATION START =====")
        print(f"[StateManager/Webhook] Job ID: {job_id}")
        print(f"[StateManager/Webhook] State: {state}")
        print(f"[StateManager/Webhook] Webhook URL: {webhook_url}")
        
        # Get result data if job is in terminal state
        result_data = None
        if state in self.TERMINAL_STATES:
            result_str = self.redis_client.get(f"runpod:result:{job_id}")
            if result_str:
                result_data = json.loads(result_str)
                print(f"[StateManager/Webhook] Result data found: {len(str(result_data))} chars")
            else:
                print(f"[StateManager/Webhook] No result data found for terminal state")
        
        # Build webhook payload (matches RunPod's /status endpoint format)
        payload = {
            "id": job_id,
            "status": state
        }
        
        # Add timing information
        if "created_at" in status_data and "started_at" in status_data:
            payload["delayTime"] = int((status_data["started_at"] - status_data["created_at"]) * 1000)
            print(f"[StateManager/Webhook] Delay time: {payload['delayTime']}ms")
        
        if "started_at" in status_data and "completed_at" in status_data:
            payload["executionTime"] = int((status_data["completed_at"] - status_data["started_at"]) * 1000)
            print(f"[StateManager/Webhook] Execution time: {payload['executionTime']}ms")
        
        # Add output for completed jobs
        if result_data:
            payload["output"] = result_data
        
        print(f"[StateManager/Webhook] Payload size: {len(json.dumps(payload))} bytes")
        print(f"[StateManager/Webhook] Payload preview: {json.dumps(payload, indent=2)[:500]}...")
        
        # Retry logic: 3 attempts with 10 second delays
        max_attempts = 3
        delay_seconds = 10
        
        for attempt in range(1, max_attempts + 1):
            try:
                print(f"\n[StateManager/Webhook] --- Attempt {attempt}/{max_attempts} ---")
                print(f"[StateManager/Webhook] Sending POST to: {webhook_url}")
                print(f"[StateManager/Webhook] Payload: {json.dumps(payload)[:500]}...")
                
                # Explicitly serialize and set headers to ensure proper Content-Type
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": "RunPod-Orchestrator/1.0"
                }
                
                response = requests.post(
                    webhook_url,
                    data=json.dumps(payload),
                    headers=headers,
                    timeout=30
                )
                
                print(f"[StateManager/Webhook] Request headers sent: {headers}")
                print(f"[StateManager/Webhook] Response status: {response.status_code}")
                print(f"[StateManager/Webhook] Response headers: {dict(response.headers)}")
                print(f"[StateManager/Webhook] Response body: {response.text[:200]}")
                
                if response.status_code == 200:
                    print(f"[StateManager/Webhook] ✓ Webhook delivered successfully!")
                    print(f"[StateManager/Webhook] ===== WEBHOOK NOTIFICATION END =====\n")
                    return
                else:
                    print(f"[StateManager/Webhook] ✗ Webhook returned non-200 status: {response.status_code}")
                    
            except requests.Timeout:
                print(f"[StateManager/Webhook] ✗ Webhook timeout (30s)")
            except requests.ConnectionError as e:
                print(f"[StateManager/Webhook] ✗ Connection error: {e}")
            except requests.RequestException as e:
                print(f"[StateManager/Webhook] ✗ Request error: {e}")
            except Exception as e:
                print(f"[StateManager/Webhook] ✗ Unexpected error: {e}")
                import traceback
                print(f"[StateManager/Webhook] Traceback: {traceback.format_exc()}")
            
            # Wait before retry (except on last attempt)
            if attempt < max_attempts:
                print(f"[StateManager/Webhook] Waiting {delay_seconds}s before retry...")
                time.sleep(delay_seconds)
        
        print(f"[StateManager/Webhook] ✗ Failed to deliver webhook after {max_attempts} attempts")
        print(f"[StateManager/Webhook] ===== WEBHOOK NOTIFICATION END =====\n")
    
    def get_state(self, job_id: str) -> Optional[str]:
        """Get current state of a job"""
        status_data = self.redis_client.get(f"runpod:status:{job_id}")
        if status_data:
            status = json.loads(status_data)
            return status.get("status")
        return None
    
    def is_terminal_state(self, state: str) -> bool:
        """Check if a state is terminal (job finished)"""
        return state in self.TERMINAL_STATES
