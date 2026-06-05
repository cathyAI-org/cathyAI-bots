FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends wget && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.109.0 \
    uvicorn[standard]==0.27.0 \
    httpx==0.27.0 \
    feedparser==6.0.11 \
    pydantic==2.5.0

COPY main.py /app/main.py

EXPOSE 8088

CMD ["python", "-u", "/app/main.py"]
