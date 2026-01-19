"""
Shared utilities for RunPod workflow testing
"""
import base64
import os
from datetime import timedelta
from google.cloud import storage


# Google Cloud Storage Configuration
GCS_BUCKET_NAME = "project-lovegood.firebasestorage.app"
GCS_CREDENTIALS_PATH = "C:/Users/edcat/Downloads/project-lovegood-cc7dbb5289e9.json"


def encode_image_to_base64(filepath):
    """Reads an image file and returns its Base64 encoded string."""
    with open(filepath, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def generate_signed_upload_url(bucket_name, blob_name, content_type, expiration_minutes=60):
    """
    Generates a signed URL for uploading a file to GCS.
    
    Args:
        bucket_name: Name of the GCS bucket
        blob_name: Name of the file/blob in the bucket
        content_type: MIME type of the file (e.g., "image/png", "video/mp4")
        expiration_minutes: How long the URL should be valid (default 60 minutes)
    
    Returns:
        A signed URL string that can be used for PUT requests
    """
    # Initialize the storage client
    if os.path.exists(GCS_CREDENTIALS_PATH):
        storage_client = storage.Client.from_service_account_json(GCS_CREDENTIALS_PATH)
    else:
        storage_client = storage.Client()
    
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    
    # Generate a signed URL for uploading (PUT method)
    signed_url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=expiration_minutes),
        method="PUT",
        content_type=content_type
    )
    
    return signed_url


def generate_signed_download_url(bucket_name, blob_name, expiration_minutes=60):
    """
    Generates a signed URL for downloading a file from GCS.
    
    Args:
        bucket_name: Name of the GCS bucket
        blob_name: Name of the file/blob in the bucket
        expiration_minutes: How long the URL should be valid (default 60 minutes)
    
    Returns:
        A signed URL string that can be used for GET requests
    """
    # Initialize the storage client
    if os.path.exists(GCS_CREDENTIALS_PATH):
        storage_client = storage.Client.from_service_account_json(GCS_CREDENTIALS_PATH)
    else:
        storage_client = storage.Client()
    
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    
    # Generate a signed URL for downloading (GET method)
    signed_url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=expiration_minutes),
        method="GET"
    )
    
    return signed_url
