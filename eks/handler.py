"""
EKS-specific handler.

Pulls jobs from an AWS SQS queue, runs them through the base ComfyUI
handler, and reports results via a per-job webhook URL.

Required environment variables:
  AWS_REGION              - AWS region (e.g. us-east-1)
  SQS_QUEUE_URL           - SQS queue URL to poll for jobs

Optional environment variables:
  WORKER_ID               - Identifier for this worker pod (defaults to hostname)
  VISIBILITY_TIMEOUT      - SQS visibility timeout in seconds (default: 1200)
  MAX_EMPTY_POLLS         - Consecutive empty polls before worker exits (default: 1)
  CALLBACK_SECRET         - Bearer token sent in Authorization header for webhook auth (required)

Message body fields:
  jobId       - (required) Job ID
  webhookUrl  - (required) HTTPS endpoint to POST status updates to
  input       - (required) Job input payload (workflow, download_urls, etc.)

Webhook payload (POST to webhookUrl):
  {
    "jobId":    "<job_id>",
    "status":   "IN_PROGRESS" | "COMPLETED" | "FAILED",
    "workerId": "<worker_id>",
    "output":   {...},          # present on COMPLETED
    "error":    "...",          # present on FAILED
    "details":  "..."           # present on FAILED
  }
"""
import json
import os
import signal
import socket
import sys
import time
import traceback

import boto3
import requests
from botocore.exceptions import ClientError

# Add root to path so we can import from src/
sys.path.insert(0, "/")
from src.base_handler import handler

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_REGION = os.environ["AWS_REGION"]
SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
WORKER_ID = os.environ.get("WORKER_ID", socket.gethostname())
VISIBILITY_TIMEOUT = int(os.environ.get("VISIBILITY_TIMEOUT", 1200))
MAX_EMPTY_POLLS = int(os.environ.get("MAX_EMPTY_POLLS", 1))
CALLBACK_SECRET = os.environ["CALLBACK_SECRET"]

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

sqs = boto3.client("sqs", region_name=AWS_REGION)

# ---------------------------------------------------------------------------
# Callback helper
# ---------------------------------------------------------------------------

def _post_status(webhook_url: str, job_id: str, status: str, extra: dict = None):
    """POST job status to the per-job webhook URL."""
    payload = {"jobId": job_id, "status": status, "workerId": WORKER_ID}
    if extra:
        payload.update(extra)

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {CALLBACK_SECRET}"}

    try:
        resp = requests.post(webhook_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"[eks-handler] WARNING: Webhook failed for job {job_id} (status={status}): {e}")


# ---------------------------------------------------------------------------
# Spot instance / SIGTERM handling
# ---------------------------------------------------------------------------

_current_message = None

def _handle_sigterm(signum, frame):
    print("[eks-handler] SIGTERM received — spot instance being reclaimed.")
    if _current_message:
        try:
            payload = json.loads(_current_message["Body"])
            job_id = payload.get("jobId")
            webhook_url = payload.get("webhookUrl")
            sqs.change_message_visibility(
                QueueUrl=SQS_QUEUE_URL,
                ReceiptHandle=_current_message["ReceiptHandle"],
                VisibilityTimeout=0,
            )
            print("[eks-handler] Released message back to queue.")
            if job_id and webhook_url:
                _post_status(webhook_url, job_id, "QUEUED")
                print(f"[eks-handler] Job {job_id} reset to QUEUED.")
        except Exception as e:
            print(f"[eks-handler] Error during SIGTERM cleanup: {e}")
    sys.exit(0)

signal.signal(signal.SIGTERM, _handle_sigterm)


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

def _process_message(message: dict):
    job_id = None
    webhook_url = None
    receipt_handle = message["ReceiptHandle"]
    aws_message_id = message["MessageId"]

    try:
        try:
            payload = json.loads(message["Body"])
        except json.JSONDecodeError:
            print(f"[eks-handler] ERROR: Invalid JSON in message {aws_message_id}, deleting.")
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
            return

        job_id = payload.get("jobId")
        webhook_url = payload.get("webhookUrl")

        if not job_id:
            print(f"[eks-handler] ERROR: Message {aws_message_id} missing 'jobId' field, deleting.")
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
            return

        if not webhook_url:
            print(f"[eks-handler] ERROR: Message {aws_message_id} (job {job_id}) missing 'webhookUrl' field, deleting.")
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
            return

        if "input" not in payload:
            print(f"[eks-handler] ERROR: Message {aws_message_id} (job {job_id}) missing 'input' field, deleting.")
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
            return

        print(f"[eks-handler] Received job {job_id}")
        _post_status(webhook_url, job_id, "IN_PROGRESS")

        # base_handler expects {"id": ..., "input": {...}}
        result = handler({"id": job_id, "input": payload["input"]})

        if "error" in result:
            print(f"[eks-handler] Job {job_id} failed: {result['error']}")
            _post_status(webhook_url, job_id, "FAILED", {
                "error": result["error"],
                "details": result.get("details"),
            })
        else:
            print(f"[eks-handler] Job {job_id} completed successfully.")
            _post_status(webhook_url, job_id, "COMPLETED", {"output": result})

        sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)

    except Exception as e:
        print(f"[eks-handler] Unexpected error processing job {job_id}: {e}")
        traceback.print_exc()
        if job_id and webhook_url:
            _post_status(webhook_url, job_id, "FAILED", {"error": f"Unexpected worker error: {e}"})
        # Don't delete — let visibility timeout expire so SQS can redeliver or send to DLQ


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"[eks-handler] Worker {WORKER_ID} starting...")
    print(f"[eks-handler] Polling queue: {SQS_QUEUE_URL}")

    empty_polls = 0

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,  # long polling
                VisibilityTimeout=VISIBILITY_TIMEOUT,
            )

            messages = response.get("Messages", [])
            if not messages:
                empty_polls += 1
                print(f"[eks-handler] Queue empty ({empty_polls}/{MAX_EMPTY_POLLS}). Exiting.")
                if empty_polls >= MAX_EMPTY_POLLS:
                    break
                continue

            empty_polls = 0
            for message in messages:
                _current_message = message
                _process_message(message)
                _current_message = None

        except KeyboardInterrupt:
            print("[eks-handler] Shutting down...")
            break
        except ClientError as e:
            print(f"[eks-handler] SQS error: {e}")
            time.sleep(5)
