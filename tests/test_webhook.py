"""
Test script for webhook notifications

This script:
1. Starts a simple webhook receiver on port 9000
2. Sends a job to the orchestrator with a webhook URL
3. Receives and displays webhook notifications as the job progresses

Prerequisites:
- Start orchestrator: cd orchestrators/runpod && python orchestrator.py
"""
import requests
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time

# Configuration
RUNPOD_ENDPOINT_URL = "http://localhost:8001/run"
RUNPOD_API_KEY = "fake key"
WEBHOOK_PORT = 9000
WEBHOOK_URL = f"http://host.docker.internal:{WEBHOOK_PORT}/webhook"

# Store received notifications
notifications = []


class WebhookHandler(BaseHTTPRequestHandler):
    """Simple webhook receiver"""
    
    def do_POST(self):
        """Handle POST requests"""
        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length)
        
        try:
            data = json.loads(body.decode('utf-8'))
            notifications.append(data)
            
            print(f"\n{'='*60}")
            print(f"WEBHOOK RECEIVED - {time.strftime('%H:%M:%S')}")
            print(f"{'='*60}")
            print(json.dumps(data, indent=2))
            print(f"{'='*60}\n")
            
            # Return 200 OK
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "received"}')
            
        except Exception as e:
            print(f"Error processing webhook: {e}")
            self.send_response(500)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Suppress default logging"""
        pass


def start_webhook_server():
    """Start webhook receiver in background"""
    server = HTTPServer(('0.0.0.0', WEBHOOK_PORT), WebhookHandler)
    print(f"[Webhook Server] Listening on port {WEBHOOK_PORT}")
    server.serve_forever()


def main():
    """Main function"""
    print("=" * 60)
    print("Webhook Notification Test")
    print("=" * 60)
    
    # Start webhook server in background
    webhook_thread = threading.Thread(target=start_webhook_server, daemon=True)
    webhook_thread.start()
    
    print(f"\n[Test] Webhook server started on port {WEBHOOK_PORT}")
    time.sleep(1)
    
    # Create a simple test workflow
    workflow = {
        "2": {
            "inputs": {
                "filename_prefix": "test",
                "images": ["3", 0]
            },
            "class_type": "SaveImage"
        },
        "3": {
            "inputs": {
                "image": "/comfyui/input/test.png",
                "custom_width": 0,
                "custom_height": 0
            },
            "class_type": "VHS_LoadImagePath"
        }
    }
    
    # Send job with webhook
    payload = {
        "input": {
            "workflow": workflow
        },
        "webhookv2": WEBHOOK_URL
    }
    
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }
    
    print(f"\n[Test] Sending job to orchestrator with webhook URL: {WEBHOOK_URL}")
    
    try:
        response = requests.post(RUNPOD_ENDPOINT_URL, headers=headers, json=payload, timeout=10)
        response_data = response.json()
        job_id = response_data.get("id")
        
        print(f"[Test] Job queued: {job_id}")
        print(f"[Test] Initial status: {response_data.get('status')}")
        
        # Wait for notifications
        print(f"\n[Test] Waiting for webhook notifications...")
        print(f"[Test] Expected states: IN_QUEUE -> IN_PROGRESS -> COMPLETED/FAILED")
        print(f"\n{'='*60}\n")
        
        # Wait up to 60 seconds for job to complete
        timeout = 60
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check if we received a terminal state notification
            if notifications:
                last_notification = notifications[-1]
                status = last_notification.get("status")
                if status in ["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"]:
                    print(f"\n[Test] Job finished with status: {status}")
                    break
            
            time.sleep(1)
        
        # Summary
        print(f"\n{'='*60}")
        print(f"WEBHOOK NOTIFICATION SUMMARY")
        print(f"{'='*60}")
        print(f"Total notifications received: {len(notifications)}")
        
        for i, notif in enumerate(notifications, 1):
            status = notif.get("status")
            delay = notif.get("delayTime", "N/A")
            exec_time = notif.get("executionTime", "N/A")
            print(f"\n{i}. Status: {status}")
            if delay != "N/A":
                print(f"   Delay Time: {delay}ms")
            if exec_time != "N/A":
                print(f"   Execution Time: {exec_time}ms")
        
        print(f"\n{'='*60}\n")
        
    except requests.exceptions.RequestException as e:
        print(f"[Test] ERROR: Request failed: {e}")
        return


if __name__ == "__main__":
    main()
    
    # Keep server running to receive any late notifications
    print("[Test] Keeping webhook server running for 10 more seconds...")
    time.sleep(10)
    print("[Test] Test complete!")
