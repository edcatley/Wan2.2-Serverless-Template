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
  WORKER_ID               - Identifier for this worker pod (defaults to hostname)
  VISIBILITY_TIMEOUT      - SQS visibility timeout in seconds (default: 1200)
  MAX_EMPTY_POLLS         - Consecutive empty polls before worker exits (default: 1)

Message body fields:
  id         - (required) Job ID, used as the Firestore document ID
  collection - (required) Firestore collection to write status updates to
  input      - (required) Job input payload (workflow, download_urls, etc.)
"""
import json
import os
import signal
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
WORKER_ID = os.environ.get("WORKER_ID", socket.gethostname())
VISIBILITY_TIMEOUT = int(os.environ.get("VISIBILITY_TIMEOUT", 1200))
# How many consecutive empty polls before the worker shuts itself down.
# Each poll uses WaitTimeSeconds=20 (long polling), so the default of 1
# means the pod exits after ~20 seconds of an empty queue.
MAX_EMPTY_POLLS = int(os.environ.get("MAX_EMPTY_POLLS", 1))

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

sqs = boto3.client("sqs", region_name=AWS_REGION)
# Firestore authenticates via GOOGLE_APPLICATION_CREDENTIALS (service account JSON)
db = firestore.Client(project=FIRESTORE_PROJECT_ID)


# ---------------------------------------------------------------------------
# Firestore helpers
# ---------------------------------------------------------------------------

def _set_job_status(collection: str, job_id: str, status: str, extra: dict = None):
    """Write job status to Firestore."""
    data = {"workerStatus": status, "workerId": WORKER_ID, "updatedAt": firestore.SERVER_TIMESTAMP}
    if extra:
        data.update(extra)
    db.collection(collection).document(job_id).set(data, merge=True)


# ---------------------------------------------------------------------------
# Spot instance / SIGTERM handling
# ---------------------------------------------------------------------------

# Tracks the message currently being processed so the SIGTERM handler can
# release it back to the queue immediately rather than waiting for the
# visibility timeout to expire.
_current_message = None

def _handle_sigterm(signum, frame):
    print(f"[eks-handler] SIGTERM received — spot instance being reclaimed.")
    if _current_message:
        job_id = None
        try:
            payload = json.loads(_current_message["Body"])
            job_id = payload.get("id")
            collection = payload.get("collection")
            sqs.change_message_visibility(
                QueueUrl=SQS_QUEUE_URL,
                ReceiptHandle=_current_message["ReceiptHandle"],
                VisibilityTimeout=0,
            )
            print(f"[eks-handler] Released message back to queue.")
            if job_id and collection:
                _set_job_status(collection, job_id, "QUEUED")
                print(f"[eks-handler] Job {job_id} reset to QUEUED.")
        except Exception as e:
            print(f"[eks-handler] Error during SIGTERM cleanup: {e}")
    sys.exit(0)

signal.signal(signal.SIGTERM, _handle_sigterm)


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
    collection = None
    receipt_handle = message["ReceiptHandle"]
    aws_message_id = message["MessageId"]

    try:
        try:
            payload = json.loads(message["Body"])
        except json.JSONDecodeError:
            print(f"[eks-handler] ERROR: Invalid JSON in message {aws_message_id}, deleting.")
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
            return

        job_id = payload.get("id")
        if not job_id:
            print(f"[eks-handler] ERROR: Message {aws_message_id} missing 'id' field, deleting.")
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
            return

        collection = payload.get("collection")
        if not collection:
            print(f"[eks-handler] ERROR: Message {aws_message_id} (job {job_id}) missing 'collection' field, deleting.")
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
            return

        if "input" not in payload:
            print(f"[eks-handler] ERROR: Message {aws_message_id} (job {job_id}) missing 'input' field, deleting.")
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
            return

        print(f"[eks-handler] Received job {job_id}")
        _set_job_status(collection, job_id, "IN_PROGRESS")

        result = handler(payload)

        if "error" in result:
            print(f"[eks-handler] Job {job_id} failed: {result['error']}")
            _set_job_status(collection, job_id, "FAILED", {
                "error": result["error"],
                "details": result.get("details"),
            })
        else:
            print(f"[eks-handler] Job {job_id} completed successfully.")
            _set_job_status(collection, job_id, "COMPLETED")

        sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)

    except Exception as e:
        print(f"[eks-handler] Unexpected error processing job {job_id}: {e}")
        traceback.print_exc()
        if job_id and collection:
            _set_job_status(collection, job_id, "FAILED", {"error": f"Unexpected worker error: {e}"})
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
            print(f"[eks-handler] Shutting down...")
            break
        except ClientError as e:
            print(f"[eks-handler] SQS error: {e}")
            time.sleep(5)
