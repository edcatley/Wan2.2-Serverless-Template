# Webhook Implementation

## Overview

The orchestrator now supports webhook notifications for job state transitions, matching RunPod's webhook behavior.

## Features

### State Tracking

All jobs now properly track these states:
- `IN_QUEUE` - Job is waiting for a worker
- `IN_PROGRESS` - Worker is processing the job
- `COMPLETED` - Job finished successfully
- `FAILED` - Job encountered an error
- `CANCELLED` - Job was manually cancelled
- `TIMED_OUT` - Job exceeded timeout threshold

### Webhook Notifications

When a job transitions between states, the orchestrator sends a POST request to the configured webhook URL with:

```json
{
  "id": "job-uuid",
  "status": "COMPLETED",
  "delayTime": 1234,
  "executionTime": 5678,
  "output": { /* job result */ }
}
```

**Retry Logic:**
- 3 attempts maximum
- 10 second delay between attempts
- Expects 200 status code to acknowledge receipt

## Usage

### Specify Webhook in Request

Use either `webhook` or `webhookv2` field:

```json
{
  "input": {
    "workflow": { /* ... */ },
    "download_urls": [ /* ... */ ],
    "upload_urls": [ /* ... */ ]
  },
  "webhookv2": "https://your-webhook-url.com"
}
```

### Webhook Payload Format

**For IN_QUEUE state:**
```json
{
  "id": "abc-123",
  "status": "IN_QUEUE"
}
```

**For IN_PROGRESS state:**
```json
{
  "id": "abc-123",
  "status": "IN_PROGRESS",
  "delayTime": 1234
}
```

**For terminal states (COMPLETED/FAILED/CANCELLED/TIMED_OUT):**
```json
{
  "id": "abc-123",
  "status": "COMPLETED",
  "delayTime": 1234,
  "executionTime": 5678,
  "output": {
    "images": [
      {
        "filename": "output_00001_.png",
        "type": "uploaded",
        "url": "https://..."
      }
    ]
  }
}
```

## Implementation Details

### StateManager Class

Centralized state management in `state_manager.py`:
- Validates state transitions
- Updates Redis with timestamps
- Triggers webhook notifications in background threads
- Handles retry logic

### Integration Points

**API (api.py):**
- Accepts `webhook` and `webhookv2` fields
- Stores webhook URL with job data
- Uses StateManager for all state transitions

**Worker Manager (worker_manager.py):**
- Uses StateManager for FAILED and TIMED_OUT states
- Properly tracks job timeouts
- Handles container failures

## Testing

Run the webhook test:

```bash
cd tests
python test_webhook.py
```

This starts a local webhook receiver and sends a test job to verify notifications are working.

## Notes

- Webhook URLs must be accessible from the orchestrator (use `host.docker.internal` for local testing)
- Webhooks are sent asynchronously and don't block job processing
- Failed webhook deliveries are logged but don't affect job execution
- Job data is stored in Redis with 1 hour expiration
