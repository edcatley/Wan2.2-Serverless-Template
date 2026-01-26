# 1. SETUP THE BASE (CUDA 12.9)
ARG BASE_IMAGE=nvidia/cuda:12.9.0-devel-ubuntu24.04
FROM ${BASE_IMAGE} AS base

# 2. SETUP ARGS
ARG PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu129
ARG COMFYUI_VERSION=latest

# Added CMAKE_BUILD_PARALLEL_LEVEL back for faster compilation
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    TORCH_CUDA_ARCH_LIST="8.9;9.0" \
    CMAKE_BUILD_PARALLEL_LEVEL=8 \
    UV_HTTP_TIMEOUT=600

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

# Copy the config telling Comfy to look at /network-volume
COPY src/extra_model_paths.yaml ./

WORKDIR /

# 6. SCRIPTS & CUSTOM NODES
# Add script to install custom nodes
COPY scripts/comfy-node-install.sh /usr/local/bin/comfy-node-install
RUN chmod +x /usr/local/bin/comfy-node-install

# Add script to configure Manager (Security) - RESTORED
COPY scripts/comfy-manager-set-mode.sh /usr/local/bin/comfy-manager-set-mode
RUN chmod +x /usr/local/bin/comfy-manager-set-mode

# Install Requirements (requests, websocket-client, sageattention)
COPY requirements.txt .
RUN uv pip install --no-cache-dir -r requirements.txt

# Copy generic base handler (used by platform-specific wrappers)
COPY src/ /src/

# Add demo data for mock workflows to ComfyUI's input directory
COPY test-data/ /comfyui/input/demo/


# CUSTOM NODE INSTALL
ENV PIP_NO_INPUT=1
RUN comfy-node-install \
    comfyui-videohelpersuite \
    comfyui-kjnodes \
    comfyui-custom-scripts \
    comfyui-wan-vace-prep \
    comfymath \
    seedvr2_videoupscaler \
    comfyui-frame-interpolation \
    tripleksampler \
    comfyui-unload-model 

# 7. EXPOSE THE STANDARD PORT
EXPOSE 8188

# 8. DEFAULT CMD (Just runs Comfy normally)
CMD ["python", "main.py", "--listen", "0.0.0.0"]