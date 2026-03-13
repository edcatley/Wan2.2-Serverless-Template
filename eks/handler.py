"""
EKS-specific handler.

Pulls jobs from an AWS SQS queue, runs them through the base ComfyUI
handler, and writes results back to Google Cloud Firestore (so the
Firebase app sees updates without any extra infrastructure).

Required environment variables:
  AWS_REGION              - AWS region (e.g. us-east-1)
  SQS_QUEUE_URL           - SQS queue URL to poll for jobs
  FIRESTORE_PROJECT_ID    - GCP project ID for Firestore
  GOOGLE_APPLICATION_CREDENTIALS - Path to Firebase Admin SDK service account JSON

Optional environment variables:
  FIRESTORE_COLLECTION    - Firestore collection for job results (default: "jobs")
  WORKER_ID               - Identifier for this worker pod (defaults to hostname)
  VISIBILITY_TIMEOUT      - SQS visibility timeout in seconds (default: 300)
"""
import json
import os
import socket
import sys
import time
import traceback

import boto3
from botocore.exceptions import ClientError
from google.cloud import firestore

# Add root to path so we can import from src/
sys.path.insert(0, "/")
from src.base_handler import handler

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_REGION = os.environ["AWS_REGION"]
SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
FIRESTORE_PROJECT_ID = os.environ["FIRESTORE_PROJECT_ID"]
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "jobs")
WORKER_ID = os.environ.get("WORKER_ID", socket.gethostname())
VISIBILITY_TIMEOUT = int(os.environ.get("VISIBILITY_TIMEOUT", 300))

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

sqs = boto3.client("sqs", region_name=AWS_REGION)
# Firestore authenticates via GOOGLE_APPLICATION_CREDENTIALS (service account JSON)
db = firestore.Client(project=FIRESTORE_PROJECT_ID)


# ---------------------------------------------------------------------------
# Firestore helpers
# ---------------------------------------------------------------------------

def _set_job_status(job_id: str, status: str, extra: dict = None):
    """Write job status to Firestore."""
    data = {"status": status, "worker_id": WORKER_ID, "updated_at": firestore.SERVER_TIMESTAMP}
    if extra:
        data.update(extra)
    db.collection(FIRESTORE_COLLECTION).document(job_id).set(data, merge=True)


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

def _process_message(message: dict):
    """
    Called for each SQS message. Parses the job, runs it through
    base_handler, and writes the result to Firestore.

    Message body should be JSON with shape:
      {
        "id": "<job_id>",
        "input": {
          "workflow": {...},
          "download_urls": [...],   # optional
          "upload_urls": [...],     # optional
          "images": [...]           # optional
        }
      }
    """
    job_id = None
    receipt_handle = message["ReceiptHandle"]

    try:
        payload = json.loads(message["Body"])
        job_id = payload.get("id")

        if not job_id:
            print(f"[eks-handler] ERROR: Message missing 'id' field, deleting.")
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
            return

        print(f"[eks-handler] Received job {job_id}")
        _set_job_status(job_id, "IN_PROGRESS", {"started_at": firestore.SERVER_TIMESTAMP})

        # Run through the base handler — same interface as RunPod/GKE
        result = handler(payload)

        if "error" in result:
            print(f"[eks-handler] Job {job_id} failed: {result['error']}")
            _set_job_status(job_id, "FAILED", {
                "error": result["error"],
                "details": result.get("details"),
                "completed_at": firestore.SERVER_TIMESTAMP,
            })
        else:
            print(f"[eks-handler] Job {job_id} completed successfully.")
            _set_job_status(job_id, "COMPLETED", {
                "output": result,
                "completed_at": firestore.SERVER_TIMESTAMP,
            })

        sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)

    except Exception as e:
        print(f"[eks-handler] Unexpected error processing job {job_id}: {e}")
        traceback.print_exc()
        if job_id:
            _set_job_status(job_id, "FAILED", {
                "error": f"Unexpected worker error: {e}",
                "completed_at": firestore.SERVER_TIMESTAMP,
            })
        # Don't delete — let visibility timeout expire so SQS can redeliver or send to DLQ


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"[eks-handler] Worker {WORKER_ID} starting...")
    print(f"[eks-handler] Polling queue: {SQS_QUEUE_URL}")

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
                continue

            for message in messages:
                _process_message(message)

        except KeyboardInterrupt:
            print(f"[eks-handler] Shutting down...")
            break
        except ClientError as e:
            print(f"[eks-handler] SQS error: {e}")
            time.sleep(5)
