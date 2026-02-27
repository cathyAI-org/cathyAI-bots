# Catcord Bots Framework

Shared framework for Matrix bots with individual bot services.

## Structure

```
./
  docker-compose.yml         # Bot orchestration
  framework/                 # Shared package
    catcord_bots/           # Python package (matrix, config, ai_summary)
    Dockerfile              # Base image
  cleaner/                  # Cleaner bot
    main.py                 # Entry point
    cleaner.py              # Core logic
    Dockerfile
    config.yaml
  tests/                    # Test suite
```

## Features

- **Framework**: Shared Matrix client, config parsing, AI summary rendering
- **Cleaner Bot**: Automated media cleanup with retention and pressure modes
- **Personality**: Optional summaries with personality via characters API

## Setup

Run `./setup.sh` and choose:
1. Docker (production)
2. Local Python (development)

## Build

```bash
docker build -t catcord-bots-framework:latest -f framework/Dockerfile framework
docker-compose build cleaner
```

## Run Cleaner Bot

Dry-run:
```bash
docker-compose run --rm cleaner --config /config/config.yaml --mode pressure --dry-run
docker-compose run --rm cleaner --config /config/config.yaml --mode retention --dry-run
```

Production:
```bash
docker-compose run --rm cleaner --config /config/config.yaml --mode pressure
docker-compose run --rm cleaner --config /config/config.yaml --mode retention
```

## AI Configuration

The personality renderer supports two API modes:

- `cathy_api_mode: "ollama"` - Uses Ollama `/api/chat` endpoint
- `cathy_api_mode: "openai"` - Uses OpenAI-compatible `/v1/chat/completions` endpoint

Set `cathy_api_model` to your model name (e.g., `llama3`, `gemma2:2b`, `cathy`).

## Tests

```bash
pytest tests/ -v
```