FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Hosted demo: SQLite opened mode=ro, mutating routes 403, per-IP rate limit on.
ENV RETOBS_READ_ONLY=1
ENV RETOBS_RATE_LIMIT_PER_MINUTE=300
# The real SciFact run first: the site opens on it. Then the built-in demo (compare, Audit) and a
# verified integration (Connect).
ENV RETOBS_DASHBOARD_DBS=/data/scifact.db:/data/demo.db:/data/integration.db

# .dockerignore keeps .env, .retobs/, results/, dist/, artifacts/, sessions, and .git out.
COPY . .
RUN pip install --no-cache-dir -e ".[dashboard]"

RUN if [ -d "retrieval_observatory/dashboard/ui" ] && [ -f "retrieval_observatory/dashboard/ui/package.json" ]; then \
        apt-get update && apt-get install -y --no-install-recommends nodejs npm && \
        cd retrieval_observatory/dashboard/ui && npm ci && npm run build && \
        apt-get purge -y nodejs npm && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*; \
    fi

# Demo databases baked by deploy/prepare_data.py (migrated, indexed, checked for leaks, gzipped).
COPY deploy/data/scifact.db.gz deploy/data/demo.db.gz deploy/data/integration.db.gz /data/
RUN gunzip /data/*.db.gz && chmod 444 /data/*.db && useradd --system --no-create-home retobs
USER retobs

EXPOSE 8000

CMD ["retobs", "serve", "--host", "0.0.0.0", "--port", "8000"]
