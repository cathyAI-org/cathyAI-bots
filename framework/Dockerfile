FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/framework
COPY pyproject.toml /opt/framework/pyproject.toml
COPY catcord_bots /opt/framework/catcord_bots

RUN pip install --no-cache-dir .

WORKDIR /app
