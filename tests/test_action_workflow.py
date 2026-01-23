"""
Test script for Action Workflow: Video processing

Prerequisites:
1. Run test_neutral_workflow.py first to generate the required inputs:
   - test-data/output/head/*.png (16 images)
   - test-data/output/tail/*.png (16 images)
   - test-data/output/neutral/neutral_00001.mp4
2. Start Firebase Emulators: firebase emulators:start
3. Start orchestrator: cd orchestrators/runpod && python orchestrator.py

This workflow:
- Takes head/tail image sequences + neutral video from storage (outputs of neutral workflow)
- Outputs: 1 action video (action_*.mp4)
"""
import requests
import json
from shared_utils import generate_storage_url, FUNCTIONS_EMULATOR_URL

# Configuration
RUNPOD_ENDPOINT_URL = "http://localhost:8001/runsync"
RUNPOD_API_KEY = "fake key"
WORKFLOW_FILE_PATH = "action_workflow_mock.json"

# Input paths in Firebase Storage (outputs from neutral workflow)
INPUT_HEAD_PREFIX = "test-data/output/head"
INPUT_TAIL_PREFIX = "test-data/output/tail"
INPUT_VIDEO = "test-data/output/neutral/neutral_00001.mp4"

# Output paths in Firebase Storage
OUTPUT_VIDEO_PREFIX = "test-data/output/action"


def main():
    """Main function to prepare and send the API request."""
    print("--- Action Workflow: Video Processing ---")
    print("--- Preparing API Request ---")
    
    # Check if Firebase Functions Emulator is running
    try:
        response = requests.get(f"{FUNCTIONS_EMULATOR_URL.replace('host.docker.internal', 'localhost')}/emulator_storage_proxy?path=test", timeout=2)
        print(f"✓ Firebase Functions Emulator is running")
    except requests.exceptions.RequestException:
        print(f"ERROR: Firebase Functions Emulator is not running")
        print("Start it with: firebase emulators:start")
        return

    # 1. Generate download URLs for input images (outputs from neutral workflow)
    # All images will be uploaded to /comfyui/input/ in alphabetical order:
    # - head_00001_.png through head_00016_.png (16 files)
    # - preprocessed.png (1 file)
    # - tail_00001_.png through tail_00016_.png (16 files)
    # Total: 33 files
    # Node 7 will load images 0-15 (head)
    # Node 8 will skip first 17 and load images 17-32 (tail)
    
    image_urls = []
    
    # Head images (16 frames) - will be first alphabetically
    for i in range(1, 17):
        filename = f"head_{i:05d}_.png"
        storage_path = f"{INPUT_HEAD_PREFIX}/{filename}"
        url = generate_storage_url(storage_path, method="GET")
        image_urls.append({
            "name": filename,
            "url": url
        })
    
    # Preprocessed image (will be 17th alphabetically)
    preprocessed_storage_path = "test-data/output/preprocessed.png"
    preprocessed_url = generate_storage_url(preprocessed_storage_path, method="GET")
    image_urls.append({
        "name": "preprocessed.png",
        "url": preprocessed_url
    })
    
    # Tail images (16 frames) - will be last alphabetically
    for i in range(1, 17):
        filename = f"tail_{i:05d}_.png"
        storage_path = f"{INPUT_TAIL_PREFIX}/{filename}"
        url = generate_storage_url(storage_path, method="GET")
        image_urls.append({
            "name": filename,
            "url": url
        })
    
    print(f"Generated download URLs for inputs:")
    print(f"  Head images: {INPUT_HEAD_PREFIX}/ (16 files)")
    print(f"  Preprocessed image: {preprocessed_storage_path}")
    print(f"  Tail images: {INPUT_TAIL_PREFIX}/ (16 files)")
    print(f"  Total: {len(image_urls)} images in alphabetical order")

    # 2. Generate upload URL for output video
    output_filename = "action_00001.mp4"
    output_storage_path = f"{OUTPUT_VIDEO_PREFIX}/{output_filename}"
    output_url = generate_storage_url(output_storage_path, method="PUT", content_type="video/mp4")
    
    print(f"\nGenerated upload URL for output:")
    print(f"  Video: {output_storage_path}")

    # 3. Load the workflow from the JSON file
    try:
        with open(WORKFLOW_FILE_PATH, 'r', encoding='utf-8') as f:
            workflow_json = json.load(f)
        print(f"\nSuccessfully loaded workflow from: {WORKFLOW_FILE_PATH}")
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
            "image_urls": image_urls,
            "upload_urls": {
                output_filename: output_url
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
        if "videos" in response_json:
            print(f"\n✓ Received {len(response_json['videos'])} video(s)")
            for vid_data in response_json["videos"]:
                if vid_data.get("type") == "uploaded":
                    print(f"  ✓ Video uploaded: {vid_data.get('filename')}")
                    print(f"    Storage path: {output_storage_path}")
        
        print("\nFull response:")
        print(json.dumps(response_json, indent=2))
        
    except json.JSONDecodeError:
        print("Could not decode JSON from response.")
        print("Response Text:")
        print(response.text)


if __name__ == "__main__":
    main()
