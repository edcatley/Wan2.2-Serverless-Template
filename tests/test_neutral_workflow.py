"""
Test script for Neutral Workflow: Image sequences + video processing

Prerequisites:
1. Run test_preprocessing_workflow.py first to generate the required input:
   - test-data/output/preprocessed_00001_.png
2. Start Firebase Emulators: firebase emulators:start
3. Start orchestrator: cd orchestrators/runpod && python orchestrator.py

This workflow:
- Takes 1 input image from storage (output of preprocessing workflow)
- Loads 2 image directories (head and tail) from baked-in test data
- Loads 1 video (neutral) from baked-in test data
- Outputs: 2 image sequences (head_*.png, tail_*.png) + 1 video (neutral_*.mp4)

Note: Directory/video paths are hardcoded in the workflow JSON to point to baked-in container data.
"""
import requests
import json
from shared_utils import generate_storage_url, FUNCTIONS_EMULATOR_URL

# Configuration
RUNPOD_ENDPOINT_URL = "http://localhost:8001/runsync"
RUNPOD_API_KEY = "fake key"
WORKFLOW_FILE_PATH = "neutral_workflow_mock.json"

# Input path in Firebase Storage (output from preprocessing workflow)
INPUT_STORAGE_PATH = "test-data/output/preprocessed_00001_.png"

# Output paths in Firebase Storage
OUTPUT_HEAD_PREFIX = "test-data/output/head"
OUTPUT_TAIL_PREFIX = "test-data/output/tail"
OUTPUT_VIDEO_PREFIX = "test-data/output/neutral"


def main():
    """Main function to prepare and send the API request."""
    print("--- Neutral Workflow: Image Sequences + Video Processing ---")
    print("--- Preparing API Request ---")
    
    # Check if Firebase Functions Emulator is running
    try:
        response = requests.get(f"{FUNCTIONS_EMULATOR_URL.replace('host.docker.internal', 'localhost')}/emulator_storage_proxy?path=test", timeout=2)
        print(f"✓ Firebase Functions Emulator is running")
    except requests.exceptions.RequestException:
        print(f"ERROR: Firebase Functions Emulator is not running")
        print("Start it with: firebase emulators:start")
        return

    # 1. Generate download URL for input image (output from preprocessing workflow)
    input_url = generate_storage_url(INPUT_STORAGE_PATH, method="GET")
    print(f"Generated download URL for input:")
    print(f"  Storage path: {INPUT_STORAGE_PATH}")
    print(f"  URL: {input_url}")

    # 2. Generate upload URLs for outputs
    # The workflow will generate multiple files with numbered suffixes
    upload_urls = []
    
    # Head images (assuming 16 frames based on test-data structure)
    for i in range(1, 17):
        filename = f"head_{i:05d}_.png"
        storage_path = f"{OUTPUT_HEAD_PREFIX}/{filename}"
        upload_urls.append({
            "name": filename,
            "url": generate_storage_url(storage_path, method="PUT", content_type="image/png")
        })
    
    # Tail images (assuming 16 frames)
    for i in range(1, 17):
        filename = f"tail_{i:05d}_.png"
        storage_path = f"{OUTPUT_TAIL_PREFIX}/{filename}"
        upload_urls.append({
            "name": filename,
            "url": generate_storage_url(storage_path, method="PUT", content_type="image/png")
        })
    
    # Video output
    video_filename = "neutral_00001.mp4"
    video_storage_path = f"{OUTPUT_VIDEO_PREFIX}/{video_filename}"
    upload_urls.append({
        "name": video_filename,
        "url": generate_storage_url(video_storage_path, method="PUT", content_type="video/mp4")
    })
    
    print(f"\nGenerated upload URLs for {len(upload_urls)} output files")
    print(f"  Head images: {OUTPUT_HEAD_PREFIX}/")
    print(f"  Tail images: {OUTPUT_TAIL_PREFIX}/")
    print(f"  Video: {OUTPUT_VIDEO_PREFIX}/")

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
            "download_urls": [
                {
                    "name": "preprocessed.png",  # Must match the filename in workflow JSON
                    "url": input_url
                }
            ],
            "upload_urls": upload_urls
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
        
        # Check if outputs were uploaded
        if "images" in response_json:
            print(f"\n✓ Received {len(response_json['images'])} image(s)")
            for img_data in response_json["images"]:
                if img_data.get("type") == "uploaded":
                    print(f"  ✓ Image uploaded: {img_data.get('filename')}")
        
        if "videos" in response_json:
            print(f"\n✓ Received {len(response_json['videos'])} video(s)")
            for vid_data in response_json["videos"]:
                if vid_data.get("type") == "uploaded":
                    print(f"  ✓ Video uploaded: {vid_data.get('filename')}")
        
        print("\nFull response:")
        print(json.dumps(response_json, indent=2))
        
    except json.JSONDecodeError:
        print("Could not decode JSON from response.")
        print("Response Text:")
        print(response.text)


if __name__ == "__main__":
    main()
