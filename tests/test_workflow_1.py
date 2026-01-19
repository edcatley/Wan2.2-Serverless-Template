"""
Test script for Workflow 1: Simple image passthrough
Input: 1 image (via signed URL)
Output: 1 image (uploaded to GCS)
"""
import requests
import json
import uuid
from shared_utils import (
    generate_signed_upload_url,
    generate_signed_download_url,
    GCS_BUCKET_NAME
)

# Configuration
RUNPOD_ENDPOINT_URL = "http://localhost:8001/runsync"
RUNPOD_API_KEY = "fake key"
WORKFLOW_FILE_PATH = "Test_Workflow.json"

# Input image already in GCS (you'll need to upload test_image.png to GCS first)
INPUT_IMAGE_GCS_PATH = "tests/test_workflow_1/inputs/test_image.png"


def main():
    """Main function to prepare and send the API request."""
    print("--- Workflow 1: Simple Image Passthrough (URL Input) ---")
    print("--- Preparing API Request ---")

    # 1. Generate signed download URL for input image
    try:
        input_signed_url = generate_signed_download_url(
            GCS_BUCKET_NAME,
            INPUT_IMAGE_GCS_PATH
        )
        print(f"Generated signed download URL for input: {input_signed_url[:100]}...")
    except Exception as e:
        print(f"ERROR: Failed to generate input signed URL: {e}")
        print("Make sure test_image.png is uploaded to GCS at:", INPUT_IMAGE_GCS_PATH)
        return

    # 2. Generate unique filename and signed upload URL for output
    unique_id = str(uuid.uuid4())
    output_filename = f"tests/test_workflow_1/outputs/processed_image_{unique_id}.png"
    
    try:
        output_signed_url = generate_signed_upload_url(
            GCS_BUCKET_NAME, 
            output_filename,
            content_type="image/png"
        )
        print(f"Generated unique output filename: {output_filename}")
        print(f"Generated signed upload URL for output: {output_signed_url[:100]}...")
    except Exception as e:
        print(f"ERROR: Failed to generate output signed URL: {e}")
        return

    # 3. Load the workflow from the JSON file
    try:
        with open(WORKFLOW_FILE_PATH, 'r', encoding='utf-8') as f:
            workflow_json = json.load(f)
        print(f"Successfully loaded workflow from: {WORKFLOW_FILE_PATH}")
    except FileNotFoundError:
        print(f"ERROR: Workflow file not found at: {WORKFLOW_FILE_PATH}")
        return
    except json.JSONDecodeError:
        print(f"ERROR: Could not decode JSON from: {WORKFLOW_FILE_PATH}")
        return

    # 4. Construct the final JSON payload using image_urls instead of base64
    payload = {
        "input": {
            "workflow": workflow_json,
            "image_urls": [
                {
                    "name": "input.png",
                    "url": input_signed_url
                }
            ],
            "upload_urls": {
                "processed_image_00001_.png": output_signed_url
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }

    print("\n--- Sending Request to Runpod Endpoint ---")
    print(f"URL: {RUNPOD_ENDPOINT_URL}")

    # 5. Send the request
    response = requests.post(RUNPOD_ENDPOINT_URL, headers=headers, json=payload, timeout=300)

    print("\n--- Received Response ---")
    print(f"Status Code: {response.status_code}")
    
    # 6. Print the response
    try:
        response_json = response.json()
        print("Response JSON:")
        print(json.dumps(response_json, indent=2))
    except json.JSONDecodeError:
        print("Could not decode JSON from response.")
        print("Response Text:")
        print(response.text)


if __name__ == "__main__":
    main()
