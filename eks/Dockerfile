ARG BASE_IMAGE_NAME
FROM ${BASE_IMAGE_NAME}

# Install EKS/AWS dependencies + Firestore for result reporting
RUN uv pip install boto3 google-cloud-firestore

# EKS mounts the network volume at /network-volume directly via a PersistentVolume,
# so no symlink needed — just ensure the path exists as a mount point.
RUN mkdir -p /network-volume

# Copy EKS scripts
COPY eks/handler.py /handler.py
COPY eks/start.sh /start.sh

RUN chmod +x /start.sh

CMD ["/start.sh"]
