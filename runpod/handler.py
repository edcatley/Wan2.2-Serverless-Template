"""
RunPod-specific handler wrapper.

This imports the generic base_handler and wraps it with RunPod's serverless SDK.
"""
import sys

# Add root to path so we can import from src/
sys.path.insert(0, '/')

from src.base_handler import handler
import runpod


if __name__ == "__main__":
    print("worker-comfyui - Starting RunPod serverless handler...")
    runpod.serverless.start({"handler": handler})
