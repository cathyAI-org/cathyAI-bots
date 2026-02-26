# Catcord Bots Framework

Shared framework for Matrix bots with individual bot services.

## Structure

```
./
  docker-compose.bots.yml    # All bots orchestration
  framework/                 # Shared runtime
    catcord_bots/           # Python package
    Dockerfile              # Base image
  cleaner/                  # Cleaner bot (batch job)
    main.py
    cleaner.py
    Dockerfile
    config.yaml
```

## Build Instructions

### 1. Build framework base image

```bash
docker build -t catcord-bots-framework:latest ./framework
```

### 2. Build bot images

```bash
docker-compose -f docker-compose.bots.yml build
```

## Running Bots

### Cleaner Bot (batch mode)

Dry-run pressure check:
```bash
docker-compose -f docker-compose.bots.yml run --rm cleaner --config /config/config.yaml --mode pressure --dry-run
```

Dry-run retention:
```bash
docker-compose -f docker-compose.bots.yml run --rm cleaner --config /config/config.yaml --mode retention --dry-run
```

Production runs:
```bash
docker-compose -f docker-compose.bots.yml run --rm cleaner --config /config/config.yaml --mode pressure
docker-compose -f docker-compose.bots.yml run --rm cleaner --config /config/config.yaml --mode retention
```

## Deployment to Server

1. Copy entire repo to `/opt/catcord/bots/`
2. Build framework image on server
3. Build bot images
4. Create systemd timers

### Systemd Timer Example

Pressure check every 2 minutes:
```ini
[Unit]
Description=Cleaner bot pressure check

[Service]
Type=oneshot
ExecStart=/usr/bin/flock -n /var/lock/catcord/cleaner.lock /usr/bin/docker-compose -f /opt/catcord/bots/docker-compose.bots.yml run --rm cleaner --config /config/config.yaml --mode pressure
WorkingDirectory=/opt/catcord/bots
```

Nightly retention:
```ini
[Unit]
Description=Cleaner bot retention

[Service]
Type=oneshot
ExecStart=/usr/bin/flock -n /var/lock/catcord/cleaner.lock /usr/bin/docker-compose -f /opt/catcord/bots/docker-compose.bots.yml run --rm cleaner --config /config/config.yaml --mode retention
WorkingDirectory=/opt/catcord/bots
```

## Adding New Bots

1. Create new bot directory (e.g., `news/`, `chat/`)
2. Add bot service to `docker-compose.bots.yml`
3. Bot Dockerfile inherits from `catcord-bots-framework:latest`
4. Import from `catcord_bots` package
