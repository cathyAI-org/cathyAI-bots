# Catcord Bots

Matrix bot framework with automated media cleanup service.

## Architecture

```
bots/
├── framework/          # Shared Python package
│   └── catcord_bots/  # Matrix client, config, personality, state
├── services/          # Reusable backend services
│   ├── online/        # RSS/Atom fetch + URL preview service
│   └── memory/        # RAG/memory storage service
├── cleaner/           # Media cleanup bot
│   ├── main.py        # Entry point
│   ├── cleaner.py     # Cleanup logic
│   ├── messages.py    # Deterministic message composition
│   ├── message_parts.json  # Status-based sentence fragments
│   └── config.yaml    # Configuration
├── news/              # News digest bot
│   ├── main.py        # Entry point
│   ├── format.py      # Deterministic formatting
│   ├── state.py       # Deduplication
│   └── config.yaml    # Configuration
└── tests/             # Test suite
```

## Features

- **Matrix Integration**: Async Matrix client with auto-join and messaging
- **Media Cleanup**: Retention and pressure-based cleanup modes
- **News Digest**: RSS/Atom feed aggregation with AI-generated intros
- **Online Service**: Reusable RSS/Atom fetch with caching and rate limiting
- **Memory Service**: RAG/memory storage for cross-bot context
- **AI Personality**: Optional AI-generated status prefixes via prompt-composer
- **Deduplication**: Prevents duplicate notifications using payload fingerprints
- **State Management**: Tracks last notification to avoid spam
- **Deterministic Messages**: Status-based message composition from JSON sentence parts

## Setup

### Docker (Production)

```bash
./setup.sh  # Choose option 1
docker build -t catcord-bots-framework:latest -f framework/Dockerfile framework
docker-compose build online
docker-compose build memory
docker-compose build cleaner
docker-compose build news
```

### Local (Development)

```bash
./setup.sh  # Choose option 2
source venv/bin/activate
```

## Configuration

Copy `config.yaml.template` to `config.yaml` and configure:

```yaml
matrix:
  homeserver_url: "https://matrix.example.com"
  user_id: "@bot:example.com"
  access_token: "your_token"
  notifications_room: "!room:example.com"

cleaner:
  media_root: "/path/to/media"
  db_path: "/path/to/uploads.db"
  policy:
    image_days: 90
    non_image_days: 30
    pressure: 0.85
    emergency: 0.92
```

## Usage

### Cleaner Bot

**Event-Driven Mode** (Recommended): Runs continuously, monitors media uploads, triggers cleanup only when disk pressure detected

```bash
# Start event-driven cleaner (runs in background)
docker-compose up -d cleaner-event

# View logs
docker-compose logs -f cleaner-event

# Stop
docker-compose stop cleaner-event
```

**Scheduled Mode**: Run on-demand via cron/systemd for retention and pressure checks

**Retention Mode**: Delete media older than configured days

```bash
docker-compose run --rm cleaner --config /config/config.yaml --mode retention --dry-run
docker-compose run --rm cleaner --config /config/config.yaml --mode retention
```

**Pressure Mode**: Delete media when disk usage exceeds threshold

```bash
docker-compose run --rm cleaner --config /config/config.yaml --mode pressure --dry-run
docker-compose run --rm cleaner --config /config/config.yaml --mode pressure
```

**Flags**:
- `--mode {retention,pressure}`: Cleanup mode (required)
- `--dry-run`: Simulate without deleting
- `--print-effective-config`: Force send notification (for scheduled runs)

### Scheduling

**Event-Driven (Recommended)**: Use `cleaner-event` service for zero idle CPU usage. Cleanup triggers only on media uploads when disk pressure detected.

**Scheduled Mode**: Use systemd timers or cron for periodic checks:

```bash
# Nightly full check at 01:00
0 1 * * * docker-compose run --rm cleaner --config /config/config.yaml --mode retention --print-effective-config
0 1 * * * docker-compose run --rm cleaner --config /config/config.yaml --mode pressure --print-effective-config

# Frequent pressure monitoring every 2 minutes
*/2 * * * * docker-compose run --rm cleaner --config /config/config.yaml --mode pressure
```

### News Bot

**Daily Digest**: Fetch and post news from configured RSS/Atom feeds

```bash
docker-compose run --rm news --config /config/config.yaml --mode digest --dry-run
docker-compose run --rm news --config /config/config.yaml --mode digest
```

**Flags**:
- `--mode digest`: Run daily digest (required)
- `--dry-run`: Simulate without sending
- `--force-notify`: Force send even if deduplicated

**Scheduling**: Use systemd timer or cron for daily digest:

```bash
# Daily digest at 08:00
0 8 * * * docker-compose run --rm news --config /config/config.yaml --mode digest --force-notify
```

## AI Personality

The bot can generate contextual status prefixes using:
1. **prompt-composer**: Builds character-specific prompts
2. **LLM API**: Generates natural language prefixes (Ollama or OpenAI-compatible)

### Validation Rules

AI prefixes are validated to ensure:
- 3-140 characters, single sentence
- No digits, quotes, newlines
- No meta-descriptions (bot, Matrix, room, etc.)
- No temporal references (today, yesterday, uptime)
- Context-aware action-word filtering: deletion claims (deleted, removed, purged) are only rejected when no files were actually deleted

### Fallback Prefixes

If AI fails or is disabled, a status-based phrase bank provides variety while remaining deterministic for the same payload:

- **No deletions + healthy storage**: "Logs clear, Master.", "All clear, Master.", "Storage looks healthy, Master.", etc.
- **Retention check, nothing expired**: "Nothing expired, Master.", "No stale media found, Master.", etc.
- **No deletions + tight storage**: "Storage getting tight, Master.", "Usage is climbing, Master.", etc.
- **Deletions occurred**: "Cleanup completed, Master.", "Maintenance complete, Master.", etc.

## Cleaner Message Composition

The cleaner bot composes notification messages deterministically from `cleaner/message_parts.json`. Each status label has four fragment categories:

- **opening**: Short greeting/status line (e.g. "Nothing expired, Master.")
- **truth**: Factual description of what happened
- **stats**: Formatted stats with placeholders (`{used_pct}`, `{deleted_count}`, `{file_word}`)
- **closer**: Optional sign-off (empty string = omitted)

Status labels:
- `retention_nothing_to_do` — retention ran, nothing expired
- `retention_cleanup_done` — retention deleted files
- `pressure_no_action` — below pressure threshold
- `pressure_cleanup_done` — pressure cleanup ran
- `emergency_cleanup_done` — emergency threshold breached

To tune wording, edit `message_parts.json` — no Python changes needed.

## Deduplication

Notifications are deduplicated using payload fingerprints stored in `/state/{mode}_last.fp`. Messages are only sent when:
- Payload changes (different deletions, disk usage, etc.)
- `--print-effective-config` flag is used (always send)

This prevents spam from frequent checks while ensuring important changes are reported.

## Development

### Run Tests

```bash
pytest tests/ -v
```

### Code Standards

- PEP 8 compliance (88 char line length)
- reST docstrings with type annotations
- Type hints for all function signatures

### Commit Format

```
[type]: Title

Description:
  - Change 1
  - Change 2

Additional info:
  - Info 1
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

## Framework Modules

### catcord_bots.matrix
Matrix client wrapper with async operations, auto-join, and messaging.

### catcord_bots.config
YAML configuration parsing and validation.

### catcord_bots.personality
AI prefix generation with prompt-composer integration, validation, and fallbacks.

### catcord_bots.state
Payload fingerprinting and deduplication logic.

### catcord_bots.formatting
Message formatting for retention and pressure reports.

## Services

### catcord-online

Reusable online fetch service for RSS/Atom feeds and URL previews.

**Features:**
- RSS/Atom feed fetching with ETag/Last-Modified caching
- Rate limiting and allowlist enforcement
- Deterministic facts-only JSON output
- Shared across all bots

**Endpoints:**
- `GET /health` - Health check
- `POST /v1/rss/fetch` - Fetch RSS/Atom feeds

**Storage:** `/var/lib/catcord/online/cache.sqlite3`

### catcord-memory

Memory/RAG service for event storage and retrieval.

**Features:**
- Event ingestion from multiple sources (Matrix, Chainlit, bots)
- Person-aware storage with identity resolution
- Query by person, character, room, session
- Future: Vector embeddings and semantic search

**Endpoints:**
- `GET /health` - Health check
- `POST /v1/events/ingest` - Ingest event
- `POST /v1/memory/query` - Query memory

**Storage:** `/var/lib/catcord/memory/db.sqlite3`

### Service Architecture

Services are internal-only (not exposed outside docker network).

**Room Allowlist (Optional):**

Restrict which Matrix rooms can use the online service by setting `ONLINE_ALLOWLIST_ROOMS` in `.env`:

```bash
# Copy template
cp .env.template .env

# Edit .env and set allowlist (comma-separated room IDs)
ONLINE_ALLOWLIST_ROOMS="!room1:server,!room2:server"
```

Leave empty to allow all rooms. The service will return 403 for non-allowlisted rooms.

**Identity Resolution (Optional):**

Enable automatic person_id resolution and creation in memory service:

```bash
# In services/.env
IDENTITY_API_URL="http://192.168.1.59:8092"
IDENTITY_API_KEY="your_key_here"
IDENTITY_API_TIMEOUT_S=3
```

When enabled, memory service will:
1. Normalize external_user_id to consistent format (e.g. `matrix:@user:server`)
2. Call `GET /identity/resolve?external_id=...` to resolve person_id
3. If unknown (404), create new person_id and call `POST /identity/link` to register
4. Store event with resolved person_id
5. If identity API is down, fail open (store with NULL person_id + metadata flag)

This ensures all events have reliable person_id for cross-bot memory and prevents identity fragmentation.

## License

See repository license file.
