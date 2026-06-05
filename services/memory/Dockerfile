FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends wget && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.109.0 \
    uvicorn[standard]==0.27.0 \
    pydantic==2.5.0 \
    httpx==0.26.0 \
    httpx==0.26.0

COPY main.py /app/main.py
COPY extraction.py /app/extraction.py
COPY extraction_rules.yaml /app/extraction_rules.yaml

EXPOSE 8090

CMD ["python", "-u", "/app/main.py"]
