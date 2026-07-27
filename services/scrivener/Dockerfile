FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md /app/
RUN uv sync --frozen --no-dev --no-install-project

COPY src /app/src
COPY migrations /app/migrations

RUN uv sync --frozen --no-dev
RUN groupadd --system scrivener && useradd --system --gid scrivener --home-dir /app scrivener \
    && chown -R scrivener:scrivener /app

USER scrivener

EXPOSE 8000

CMD ["scrivener", "serve", "--port", "8000"]
