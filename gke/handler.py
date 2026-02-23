"""
GKE-specific handler.

Pulls jobs from a Google Cloud Pub/Sub subscription, runs them through
the base ComfyUI handler, and writes results back to Firestore.

Required environment variables:
  PUBSUB_PROJECT_ID       - GCP project ID
  PUBSUB_SUBSCRIPTION     - Pub/Sub subscription name to pull jobs from
  FIRESTORE_COLLECTION    - Firestore collection to write job results to (default: "jobs")

Optional environment variables:
  WORKER_ID               - Identifier for this worker pod (defaults to hostname)
  MAX_OUTSTANDING_MESSAGES - Max messages to hold in flight (default: 1, since ComfyUI is single-threaded)
"""
import json
import os
import socket
import sys
import time
import traceback

from google.cloud import firestore, pubsub_v1

# Add root to path so we can import from src/
sys.path.insert(0, "/")
from src.base_handler import handler

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PROJECT_ID = os.environ["PUBSUB_PROJECT_ID"]
SUBSCRIPTION = os.environ["PUBSUB_SUBSCRIPTION"]
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "jobs")
WORKER_ID = os.environ.get("WORKER_ID", socket.gethostname())

# ComfyUI is single-threaded, so we only process one job at a time
MAX_OUTSTANDING_MESSAGES = int(os.environ.get("MAX_OUTSTANDING_MESSAGES", 1))

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

db = firestore.Client(project=PROJECT_ID)
subscriber = pubsub_v1.SubscriberClient()
subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION)


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

def _process_message(message: pubsub_v1.types.PubsubMessage):
    """
    Called for each Pub/Sub message. Parses the job, runs it through
    base_handler, and writes the result to Firestore.

    Message data should be JSON with shape:
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
    try:
        payload = json.loads(message.data.decode("utf-8"))
        job_id = payload.get("id")

        if not job_id:
            print(f"[gke-handler] ERROR: Message missing 'id' field, nacking.")
            message.nack()
            return

        print(f"[gke-handler] Received job {job_id}")
        _set_job_status(job_id, "IN_PROGRESS", {"started_at": firestore.SERVER_TIMESTAMP})

        # Run through the base handler — same interface as RunPod
        result = handler(payload)

        if "error" in result:
            print(f"[gke-handler] Job {job_id} failed: {result['error']}")
            _set_job_status(job_id, "FAILED", {
                "error": result["error"],
                "details": result.get("details"),
                "completed_at": firestore.SERVER_TIMESTAMP,
            })
        else:
            print(f"[gke-handler] Job {job_id} completed successfully.")
            _set_job_status(job_id, "COMPLETED", {
                "output": result,
                "completed_at": firestore.SERVER_TIMESTAMP,
            })

        message.ack()

    except Exception as e:
        print(f"[gke-handler] Unexpected error processing job {job_id}: {e}")
        traceback.print_exc()
        if job_id:
            _set_job_status(job_id, "FAILED", {
                "error": f"Unexpected worker error: {e}",
                "completed_at": firestore.SERVER_TIMESTAMP,
            })
        # Nack so Pub/Sub can redeliver or send to dead-letter topic
        message.nack()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"[gke-handler] Worker {WORKER_ID} starting...")
    print(f"[gke-handler] Subscribing to {subscription_path}")

    flow_control = pubsub_v1.types.FlowControl(max_messages=MAX_OUTSTANDING_MESSAGES)

    streaming_pull = subscriber.subscribe(
        subscription_path,
        callback=_process_message,
        flow_control=flow_control,
    )

    print(f"[gke-handler] Listening for jobs...")

    try:
        # Block forever — the subscriber runs callbacks on background threads
        streaming_pull.result()
    except KeyboardInterrupt:
        print(f"[gke-handler] Shutting down...")
        streaming_pull.cancel()
        streaming_pull.result()
