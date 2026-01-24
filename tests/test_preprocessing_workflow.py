"""
Test script for Image Preprocessing Workflow: Simple image passthrough

Prerequisites:
1. Manually upload test_image.png to Firebase Storage Emulator at: test-data/test_image.png
2. Start Firebase Emulators: firebase emulators:start
3. Start orchestrator: cd orchestrators/runpod && python orchestrator.py

This script generates proxy URLs (for emulator) and sends the job to the orchestrator.
Output will be saved to: test-data/output/preprocessed_00001_.png
"""
import requests
import json
from shared_utils import generate_storage_url, FUNCTIONS_EMULATOR_URL

# Configuration
RUNPOD_ENDPOINT_URL = "http://localhost:8001/runsync"
RUNPOD_API_KEY = "fake key"
WORKFLOW_FILE_PATH = "image_preprocessing_workflow_mock.json"

# Input/output paths in Firebase Storage (manually upload test image to test-data folder first)
INPUT_STORAGE_PATH = "test-data/input/original.png"
OUTPUT_STORAGE_PATH = "test-data/output/preprocessed_00001_.png"  # SaveImage adds counter and underscore


def main():
    """Main function to prepare and send the API request."""
    print("--- Image Preprocessing Workflow: Simple Image Passthrough ---")
    print("--- Preparing API Request ---")
    
    # Check if Firebase Functions Emulator is running
    try:
        response = requests.get(f"{FUNCTIONS_EMULATOR_URL.replace('host.docker.internal', 'localhost')}/emulator_storage_proxy?path=test", timeout=2)
        print(f"✓ Firebase Functions Emulator is running")
    except requests.exceptions.RequestException:
        print(f"ERROR: Firebase Functions Emulator is not running")
        print("Start it with: firebase emulators:start")
        return

    # 1. Generate download URL for input image (assumes it already exists in storage)
    input_url = generate_storage_url(INPUT_STORAGE_PATH, method="GET")
    print(f"Generated download URL for input:")
    print(f"  Storage path: {INPUT_STORAGE_PATH}")
    print(f"  URL: {input_url}")

    # 2. Generate upload URL for output (same test-data folder)
    output_url = generate_storage_url(OUTPUT_STORAGE_PATH, method="PUT", content_type="image/png")
    print(f"Output will be saved to: {OUTPUT_STORAGE_PATH}")
    print(f"Generated upload URL for output: {output_url}")

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

    # 4. Construct the final JSON payload
    payload = {
        "input": {
            "workflow": workflow_json,
            "image_urls": [
                {
                    "name": "original.png",
                    "url": input_url
                }
            ],
            "upload_urls": {
                "preprocessed_00001_.png": output_url
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
