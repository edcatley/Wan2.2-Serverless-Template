"""
Test script for Workflow 1: Simple image passthrough

Prerequisites:
1. Manually upload test_image.png to Firebase Storage Emulator at: test-data/test_image.png
2. Start Firebase Storage Emulator: firebase emulators:start --only storage
3. Start orchestrator: cd orchestrators/runpod && python orchestrator.py

This script generates signed URLs and sends the job to the orchestrator.
Output will be saved to: test-data/processed_image.png
"""
import requests
import json
import os
import firebase_admin
from firebase_admin import credentials, storage
from datetime import timedelta

# Configuration
RUNPOD_ENDPOINT_URL = "http://localhost:8001/runsync"
RUNPOD_API_KEY = "fake key"
WORKFLOW_FILE_PATH = "Test_Workflow.json"

# Firebase Storage Emulator Configuration
STORAGE_EMULATOR_HOST = "localhost:9199"
FIREBASE_PROJECT_ID = "project-lovegood"
FIREBASE_BUCKET = f"{FIREBASE_PROJECT_ID}.appspot.com"

# Input/output paths in Firebase Storage (manually upload test image to test-data folder first)
INPUT_STORAGE_PATH = "test-data/test_image.png"
OUTPUT_STORAGE_PATH = "test-data/processed_image.png"


def init_firebase():
    """Initialize Firebase Admin SDK for emulator"""
    # Set emulator host BEFORE initializing
    os.environ["FIREBASE_STORAGE_EMULATOR_HOST"] = STORAGE_EMULATOR_HOST
    
    # Only initialize once
    if not firebase_admin._apps:
        # Use the service account credentials (same as production)
        # The emulator env var makes it generate emulator URLs instead
        service_account_path = "C:/Users/edcat/Downloads/local-auth.json"
        cred = credentials.Certificate(service_account_path)
        firebase_admin.initialize_app(cred, options={
            'storageBucket': FIREBASE_BUCKET
        })
        print(f"✓ Firebase Admin SDK initialized for emulator at {STORAGE_EMULATOR_HOST}")


def generate_signed_url(storage_path, method="GET", content_type=None):
    """Generate a signed URL for Firebase Storage Emulator using Firebase Admin SDK"""
    bucket = storage.bucket()
    blob = bucket.blob(storage_path)
    
    # Generate signed URL (emulator creates token-based URL)
    params = {
        "version": "v4",
        "expiration": timedelta(minutes=60),
        "method": method
    }
    if content_type:
        params["content_type"] = content_type
    
    signed_url = blob.generate_signed_url(**params)
    
    # Replace localhost with host.docker.internal for Docker access
    signed_url = signed_url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
    
    return signed_url


def main():
    """Main function to prepare and send the API request."""
    print("--- Workflow 1: Simple Image Passthrough (Signed URL) ---")
    print("--- Preparing API Request ---")
    
    # Initialize Firebase Admin SDK
    try:
        init_firebase()
    except Exception as e:
        print(f"ERROR: Failed to initialize Firebase Admin SDK: {e}")
        return
    
    # Check if Firebase Storage Emulator is running
    try:
        response = requests.get(f"http://{STORAGE_EMULATOR_HOST}", timeout=2)
        print(f"✓ Firebase Storage Emulator is running at {STORAGE_EMULATOR_HOST}")
    except requests.exceptions.RequestException:
        print(f"ERROR: Firebase Storage Emulator is not running at {STORAGE_EMULATOR_HOST}")
        print("Start it with: firebase emulators:start --only storage")
        return

    # 1. Generate signed download URL for input image (assumes it already exists in storage)
    try:
        input_signed_url = generate_signed_url(INPUT_STORAGE_PATH, method="GET")
        print(f"Generated signed download URL for input:")
        print(f"  Full URL: {input_signed_url}")
        print(f"  (Assumes file exists at: {INPUT_STORAGE_PATH})")
    except Exception as e:
        print(f"ERROR: Failed to generate input signed URL: {e}")
        return

    # 2. Generate signed upload URL for output (same test-data folder)
    try:
        output_signed_url = generate_signed_url(OUTPUT_STORAGE_PATH, method="PUT", content_type="image/png")
        print(f"Output will be saved to: {OUTPUT_STORAGE_PATH}")
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

    # 4. Construct the final JSON payload using signed URLs
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
    try:
        response = requests.post(RUNPOD_ENDPOINT_URL, headers=headers, json=payload, timeout=300)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Request failed: {e}")
        return

    print("\n--- Received Response ---")
    print(f"Status Code: {response.status_code}")
    
    # 6. Print the response
    try:
        response_json = response.json()
        print("Response JSON:")
        
        # Check if output was uploaded
        if "images" in response_json:
            print(f"\n✓ Received {len(response_json['images'])} image(s)")
            for img_data in response_json["images"]:
                if img_data.get("type") == "uploaded":
                    print(f"  ✓ Image uploaded to storage: {img_data.get('filename')}")
                    print(f"    Storage path: {OUTPUT_STORAGE_PATH}")
        
        print("\nFull response:")
        print(json.dumps(response_json, indent=2))
        
    except json.JSONDecodeError:
        print("Could not decode JSON from response.")
        print("Response Text:")
        print(response.text)


if __name__ == "__main__":
    main()
