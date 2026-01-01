FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY migrations /app/migrations

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["scrivener", "serve", "--port", "8000"]
