FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY retrieval_observatory ./retrieval_observatory

RUN pip install --no-cache-dir .
RUN pip install --no-cache-dir ".[dashboard,postgres]"

EXPOSE 8000

CMD ["retobs", "serve", "--db", "/data/results.db", "--host", "0.0.0.0", "--port", "8000"]
