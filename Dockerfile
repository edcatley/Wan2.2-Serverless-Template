# 1. SETUP THE BASE (CUDA 13)
ARG BASE_IMAGE=nvidia/cuda:13.0.0-devel-ubuntu24.04
FROM ${BASE_IMAGE} AS base

# 2. SETUP ARGS
ARG PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu130
ARG COMFYUI_VERSION=latest

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    TORCH_CUDA_ARCH_LIST="8.9;9.0;10.0"

# 3. INSTALL SYSTEM DEPS (Generic)
RUN apt-get update && apt-get install -y \
    python3.12 python3.12-venv python3.12-dev \
    git wget build-essential ninja-build ffmpeg \
    && ln -sf /usr/bin/python3.12 /usr/bin/python \
    && ln -sf /usr/bin/pip3 /usr/bin/pip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 4. INSTALL PYTHON ENV
RUN wget -qO- https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv \
    && uv venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# 5. INSTALL COMFY & PYTORCH
RUN uv pip install comfy-cli pip setuptools wheel ninja
RUN uv pip install --no-cache-dir torch torchvision --index-url ${PYTORCH_INDEX_URL}
RUN /usr/bin/yes | comfy --workspace /comfyui install --version "${COMFYUI_VERSION}" --nvidia

WORKDIR /comfyui


# Copy the config telling Comfy to look there
COPY src/extra_model_paths.yaml ./


# 6. INSTALL YOUR CUSTOM NODES & REQS
COPY requirements.txt .
RUN uv pip install --no-cache-dir -r requirements.txt

# (Add your node install script here or run commands directly)
# COPY scripts/comfy-node-install.sh ... etc ...
RUN comfy-node-install comfyui-videohelpersuite comfyui-kjnodes ...

# 7. EXPOSE THE STANDARD PORT
EXPOSE 8188

# 8. DEFAULT CMD (Just runs Comfy normally)
CMD ["python", "main.py", "--listen", "0.0.0.0"]g t