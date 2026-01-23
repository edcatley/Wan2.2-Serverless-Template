"""
Shared utilities for RunPod workflow testing
"""
import base64
import os
from datetime import timedelta
from urllib.parse import quote
from google.cloud import storage


# Google Cloud Storage Configuration
GCS_BUCKET_NAME = "project-lovegood.firebasestorage.app"
GCS_CREDENTIALS_PATH = "C:/Users/edcat/Downloads/project-lovegood-cc7dbb5289e9.json"

# Firebase Emulator Configuration
FIREBASE_PROJECT_ID = "project-lovegood"
FUNCTIONS_EMULATOR_URL = "http://host.docker.internal:5001/project-lovegood/us-central1"

# Set to True when testing with emulator, False for production
USE_EMULATOR = True


def encode_image_to_base64(filepath):
    """Reads an image file and returns its Base64 encoded string."""
    with open(filepath, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def generate_storage_url(storage_path, method="GET", content_type=None, expiration_minutes=60):
    """
    Generates a URL for storage access that works in both production and emulator modes.
    
    In production: Returns a signed URL using GCS
    In emulator: Returns a proxy URL to the emulator_storage_proxy Cloud Function
    
    Args:
        storage_path: Storage path (e.g., "test-data/test_image.png")
        method: HTTP method ("GET", "PUT", "DELETE", etc.)
        content_type: Content type for PUT requests (optional)
        expiration_minutes: How long the URL is valid (production only)
    
    Returns:
        URL string (signed URL in production, proxy URL in emulator)
    """
    if USE_EMULATOR:
        # Emulator mode: Return proxy URL to our Cloud Function
        encoded_path = quote(storage_path, safe='')
        proxy_url = f"{FUNCTIONS_EMULATOR_URL}/emulator_storage_proxy?path={encoded_path}"
        return proxy_url
    else:
        # Production mode: Use real signed URLs
        if os.path.exists(GCS_CREDENTIALS_PATH):
            storage_client = storage.Client.from_service_account_json(GCS_CREDENTIALS_PATH)
        else:
            storage_client = storage.Client()
        
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(storage_path)
        
        sign_params = {
            "version": "v4",
            "expiration": timedelta(minutes=expiration_minutes),
            "method": method
        }
        
        if method == "PUT" and content_type:
            sign_params["content_type"] = content_type
        
        signed_url = blob.generate_signed_url(**sign_params)
        return signed_url

def generate_signed_upload_url(bucket_name, blob_name, content_type, expiration_minutes=60):
    """
    DEPRECATED: Use generate_storage_url() instead.
    
    Generates a signed URL for uploading a file to GCS.
    """
    return generate_storage_url(blob_name, method="PUT", content_type=content_type, expiration_minutes=expiration_minutes)


def generate_signed_download_url(bucket_name, blob_name, expiration_minutes=60):
    """
    DEPRECATED: Use generate_storage_url() instead.
    
    Generates a signed URL for downloading a file from GCS.
    """
    return generate_storage_url(blob_name, method="GET", expiration_minutes=expiration_minutes)
