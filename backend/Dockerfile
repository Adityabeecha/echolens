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

# Migrations run in the app's lifespan (init_db). Honour $PORT when the platform
# injects one, otherwise 8000 — the port Northflank should be told to expose.
#
# One worker on purpose: investigations run in background threads inside this
# process and the collector scheduler is in-process too. Multiple workers would
# mean multiple schedulers racing on the same database.
#
# --proxy-headers: behind Northflank's load balancer every request arrives from
# the proxy, so without this the rate limiter — which keys on the client IP —
# sees ONE address for the whole internet and every visitor shares a single
# bucket. Measured: get_remote_address returned the proxy's 10.0.0.1 for a
# client at 9.9.9.9, and with ProxyHeadersMiddleware it returns 9.9.9.9.
# A handful of demo visitors would otherwise throttle each other out.
#
# --forwarded-allow-ips='*' is safe ONLY because the container is reachable
# solely through that proxy. If the port is ever exposed directly, a client
# could spoof X-Forwarded-For and dodge the rate limit entirely.
CMD ["sh", "-c", "uvicorn echolens.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
