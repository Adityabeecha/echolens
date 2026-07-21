FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2 + bcrypt build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY echolens ./echolens
RUN pip install --no-cache-dir -e .

ENV ECHOLENS_ENV=production
EXPOSE 8000

# Migrations run in the app's lifespan (init_db). $PORT is set by the platform
# (Fly sets it from fly.toml); 8000 is the local default.
CMD ["sh", "-c", "uvicorn echolens.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
