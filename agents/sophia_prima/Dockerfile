FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g @readwise/cli \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy required local packages from monorepo
COPY services/sophia_pylon /workspace/services/sophia_pylon
COPY agents/sophia_prima /workspace/agents/sophia_prima

# Install local dependencies in order: pylon first, then prima
RUN pip install --no-cache-dir /workspace/services/sophia_pylon \
    && pip install --no-cache-dir /workspace/agents/sophia_prima

WORKDIR /workspace/agents/sophia_prima

EXPOSE 8080

CMD ["sophia-gateway"]
