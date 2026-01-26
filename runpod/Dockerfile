# We use a build ARG so we can pass the base image name dynamically from GitHub Actions
ARG BASE_IMAGE_NAME
FROM ${BASE_IMAGE_NAME}

# Install RunPod SDK
RUN uv pip install runpod

# Create symlink so RunPod's /runpod-volume is accessible at /network-volume
# This allows the base image's extra_model_paths.yaml to work with RunPod's mount point
RUN ln -s /runpod-volume /network-volume

# Copy RunPod scripts
COPY handler.py /handler.py
COPY network_volume.py /network_volume.py
COPY start.sh /start.sh

RUN chmod +x /start.sh

# Overwrite the command to use RunPod's startup script
CMD ["/start.sh"]