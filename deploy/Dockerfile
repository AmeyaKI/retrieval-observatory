FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV RETOBS_READ_ONLY=1
ENV RETOBS_DASHBOARD_DBS=/data/nfcorpus.db:/data/scifact.db:/data/fiqa.db

COPY . .
RUN pip install --no-cache-dir -e ".[dashboard]"

RUN if [ -d "retrieval_observatory/dashboard/ui" ] && [ -f "retrieval_observatory/dashboard/ui/package.json" ]; then \
        apt-get update && apt-get install -y --no-install-recommends nodejs npm && \
        cd retrieval_observatory/dashboard/ui && npm ci && npm run build && \
        apt-get purge -y nodejs npm && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*; \
    fi

COPY deploy/data/nfcorpus.db deploy/data/scifact.db deploy/data/fiqa.db /data/

EXPOSE 8000

CMD ["retobs", "serve", "--host", "0.0.0.0", "--port", "8000"]
