# We use a build ARG so we can pass the base image name dynamically from GitHub Actions
ARG BASE_IMAGE_NAME
FROM ${BASE_IMAGE_NAME}

# Install RunPod SDK
RUN uv pip install runpod

# Copy RunPod scripts
COPY handler.py /handler.py
COPY network_volume.py /network_volume.py
COPY start.sh /start.sh

RUN chmod +x /start.sh

# Overwrite the command to use RunPod's startup script
CMD ["/start.sh"]