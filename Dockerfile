# DropItX API — Multi-stage Dockerfile
# Builder installs deps with gcc/rust for asyncpg, runtime is slim

FROM python:3.12-slim AS builder

WORKDIR /app

# Build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    pip install --no-cache-dir uv

COPY pyproject.toml requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt \
    asyncpg>=0.30.0 boto3>=1.35.0 psycopg2-binary>=2.9.0

# --- Runtime ---
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
