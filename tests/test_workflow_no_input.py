"""
Test script for No Input Workflow: Loads demo image, saves it
No signed URLs, no external inputs - just tests if RunPod SDK can POST results
"""
import requests
import json

# Configuration
RUNPOD_ENDPOINT_URL = "http://localhost:8001/runsync"
RUNPOD_API_KEY = "fake key"
WORKFLOW_FILE_PATH = "Test_Workflow_NoInput.json"


def main():
    """Main function to prepare and send the API request."""
    print("--- No Input Workflow Test ---")
    print("--- Testing if RunPod SDK can POST successful results ---")
    
    # Load the workflow from the JSON file
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

    # Construct the payload - NO image_urls, NO upload_urls
    payload = {
        "input": {
            "workflow": workflow_json
        }
    }

    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }

    print("\n--- Sending Request to Runpod Endpoint ---")
    print(f"URL: {RUNPOD_ENDPOINT_URL}")

    # Send the request
    try:
        response = requests.post(RUNPOD_ENDPOINT_URL, headers=headers, json=payload, timeout=300)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Request failed: {e}")
        return

    print("\n--- Received Response ---")
    print(f"Status Code: {response.status_code}")
    
    # Print the response
    try:
        response_json = response.json()
        print("Response JSON:")
        
        # Check if output was returned
        if "images" in response_json:
            print(f"\n✓ Received {len(response_json['images'])} image(s)")
            for img_data in response_json["images"]:
                if img_data.get("type") == "base64":
                    print(f"  ✓ Image returned as base64: {img_data.get('filename')}")
        
        # Print response (truncate base64 data)
        response_copy = response_json.copy()
        if "images" in response_copy:
            for img in response_copy["images"]:
                if "data" in img:
                    img["data"] = f"<base64 data, {len(img['data'])} chars>"
        
        print("\nFull response:")
        print(json.dumps(response_copy, indent=2))
        
    except json.JSONDecodeError:
        print("Could not decode JSON from response.")
        print("Response Text:")
        print(response.text)


if __name__ == "__main__":
    main()
