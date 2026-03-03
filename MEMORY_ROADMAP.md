# Memory/RAG Enhancement Roadmap

## Current State (MVP)

**What Works:**
- ✅ Event storage in sqlite (append-only log)
- ✅ Query by person_id, char_id, filters
- ✅ Returns most recent k events
- ✅ Health check endpoint

**What's Missing:**
- ❌ Identity resolution (person_id must be provided by caller)
- ❌ Vector embeddings / semantic search
- ❌ Curated memories (important facts extraction)
- ❌ Importance scoring
- ❌ Memory consolidation/distillation

## Phase 1: Identity Resolution (Minimal)

**Goal:** Automatically resolve external_user_id → person_id

**Changes:**
1. Add environment variables:
   - `IDENTITY_API_URL`
   - `IDENTITY_API_KEY`

2. Update `/v1/events/ingest`:
   - If `person_id` is None, call identity API
   - Store resolved person_id with event

**Files to modify:**
- `services/memory/main.py` - Add identity resolution
- `docker-compose.yml` - Add env vars
- `.env.template` - Document identity API config

## Phase 2: Curated Memories Table

**Goal:** Store important facts separately from event log

**Schema:**
```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY,
    person_id TEXT NOT NULL,
    char_id TEXT,
    type TEXT,  -- preference, fact, goal, relationship
    text TEXT NOT NULL,
    importance FLOAT DEFAULT 0.5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_event_ids TEXT,  -- JSON array
    pinned BOOLEAN DEFAULT 0,
    ttl_days INTEGER
);
```

**New Endpoints:**
- `POST /v1/memories/upsert` - Add/update curated memory
- `GET /v1/memories/list` - List memories for person/char

**Files to create/modify:**
- `services/memory/main.py` - Add memories table and endpoints

## Phase 3: Memory Extraction (Safe JSON-only)

**Goal:** Extract important facts from events

**Approach:**
- LLM outputs JSON only: `{"memories": [{"type": "preference", "text": "...", "importance": 0.8}]}`
- Service validates schema before storing
- Never trust LLM to write SQL or execute code

**Options:**
1. Rule-based extraction (regex patterns for obvious facts)
2. LLM extraction with strict JSON schema validation
3. Hybrid: rules first, LLM for complex cases

**Files to create:**
- `services/memory/extraction.py` - Memory extraction logic
- Add endpoint: `POST /v1/memories/extract` - Extract from event(s)

## Phase 4: Vector Search (Optional)

**Goal:** Semantic similarity search

**Approach:**
- Add Qdrant container to docker-compose
- Embed event content on ingest
- Query returns: curated + semantic matches + recent

**Files to modify:**
- `docker-compose.yml` - Add qdrant service
- `services/memory/main.py` - Add vector operations
- `requirements.txt` - Add qdrant-client

## Phase 5: Enhanced Query API

**Goal:** Return "curated + relevant + recent" instead of just "recent k"

**New query behavior:**
```python
results = {
    "curated": top_memories_by_importance(person_id, char_id),
    "semantic": vector_search(query, person_id, char_id) if query else [],
    "recent": last_n_events(person_id, char_id, n=5)
}
```

**Files to modify:**
- `services/memory/main.py` - Update `/v1/memory/query` logic

## Implementation Order

**Immediate (this PR):**
- ✅ Fix PersonalityRenderer task routing for news

**Next PR (Identity Resolution):**
1. Add identity API integration to memory service
2. Test with Matrix events

**Future PRs:**
1. Curated memories table + upsert endpoint
2. Memory extraction (rule-based first)
3. Vector search (Qdrant)
4. Enhanced query API

## Notes

- Keep memory service stateless (no in-memory caches)
- All operations should be idempotent where possible
- Use transactions for multi-step operations
- Log all identity resolutions for debugging
- Consider privacy: memories should be deletable
