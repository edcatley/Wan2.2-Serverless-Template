ARG BASE_IMAGE_NAME
FROM ${BASE_IMAGE_NAME}

# Install GKE/GCP dependencies
RUN uv pip install google-cloud-pubsub google-cloud-firestore

# GKE mounts the network volume at /network-volume directly via a PersistentVolume,
# so no symlink needed — just ensure the path exists as a mount point.
RUN mkdir -p /network-volume

# Copy GKE scripts
COPY handler.py /handler.py
COPY start.sh /start.sh

RUN chmod +x /start.sh

CMD ["/start.sh"]
