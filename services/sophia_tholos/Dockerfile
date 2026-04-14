FROM python:3.11-slim

ARG THOLOS_INSTALL_SEMANTIC=true
ARG THOLOS_PRELOAD_MODEL=false
ARG THOLOS_MODEL_NAME=all-MiniLM-L6-v2

WORKDIR /app

ENV THOLOS_MODEL_CACHE_DIR=/models/sentence-transformers

COPY requirements-base.txt requirements-semantic.txt /app/
RUN pip install --no-cache-dir -r /app/requirements-base.txt
RUN if [ "$THOLOS_INSTALL_SEMANTIC" = "true" ]; then \
      pip install --no-cache-dir -r /app/requirements-semantic.txt; \
    fi

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir --no-deps .
RUN if [ "$THOLOS_INSTALL_SEMANTIC" = "true" ] && [ "$THOLOS_PRELOAD_MODEL" = "true" ]; then \
      python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${THOLOS_MODEL_NAME}', cache_folder='${THOLOS_MODEL_CACHE_DIR}')"; \
    fi

EXPOSE 8004

CMD ["python", "-m", "sophia_tholos.main"]
