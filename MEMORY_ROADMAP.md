# Memory/RAG Enhancement Roadmap

## Current State

**What Works:**
- ✅ Event storage in sqlite (append-only log)
- ✅ Query by person_id, char_id, filters
- ✅ Returns most recent k events
- ✅ Health check endpoint
- ✅ **Phase 1 Complete:** Identity resolution with cathyAI-identity-db integration
  - Automatic external_user_id → person_id resolution
  - Creates new person_id on 404 via POST /identity/link
  - Fail-open behavior (NULL person_id + metadata flag if API down)
  - Consistent ID normalization (matrix:, chainlit:, discord: prefixes)
- ✅ **Phase 2 Complete:** Curated memories with idempotent upsert
  - Fingerprint-based upsert (sha256 of person_id|scope|char_id|type|normalized_text)
  - Transactional merge: source_event_ids (set-union), importance (max)
  - Soft delete support (deleted_at)
  - Scope field (character, person_global, room, session)
  - Type allowlist (preference, fact, goal, relationship, project, open_loop)
  - Three indexes for fast retrieval
  - Upsert, list, forget endpoints
- ✅ **Phase 3 Complete:** Rule-based memory extraction
  - Conservative high-precision regex patterns in YAML
  - RuleExtractor with validation and deduplication
  - POST /v1/memories/extract endpoint
  - Returns candidates (proposed) and upserted (stored)
  - Automatic person_id resolution
  - Template-based text formatting

**What's Missing:**
- ❌ LLM fallback for extraction (rules-first complete)
- ❌ Vector embeddings / semantic search
- ❌ Enhanced query API (curated + semantic + recent + sources)

## ✅ Phase 1: Identity Resolution (COMPLETE)

**Goal:** Automatically resolve external_user_id → person_id

**Implemented:**
- Environment variables: IDENTITY_API_URL, IDENTITY_API_KEY, IDENTITY_API_TIMEOUT_S
- normalize_external_id() for consistent formatting
- resolve_or_create_person_id() with cathyAI-identity-db API:
  - GET /identity/resolve?external_id=... (200 or 404)
  - POST /identity/link with new person_id on 404
  - x-api-key authentication
  - Fail-open: stores NULL person_id + metadata flag if API down
- Updated docker-compose.yml and services/.env.template
- All 42 tests passing

**Files Modified:**
- `services/memory/main.py`
- `docker-compose.yml`
- `services/.env.template`
- `README.md`

## ✅ Phase 2: Curated Memories Table (COMPLETE)

**Goal:** Store important facts separately from event log with idempotent upsert

**Implemented:**
- Memories table with all fields and indexes
- Fingerprint computation: sha256(person_id|scope|char_id_or_empty|type|normalized_text)
- Text normalization: strip + collapse whitespace + lowercase (store original text)
- Transactional upsert with source_event_ids merge (set-union) and importance update (max)
- Soft delete support (deleted_at)
- Type allowlist: preference, fact, goal, relationship, project, open_loop
- Scope allowlist: character, person_global, room, session
- POST /v1/memories/upsert - Idempotent upsert via fingerprint
- GET /v1/memories/list - Filter by person_id, char_id, scope, include_deleted
- POST /v1/memories/forget - Soft delete by ID or fingerprint
- Replaced deprecated @app.on_event with modern lifespan context manager
- Comprehensive tests for idempotency, merge behavior, soft delete
- All 46 tests passing with zero deprecation warnings

**Files Modified:**
- `services/memory/main.py` - Added memories table, endpoints, fingerprint logic, lifespan
- `services/online/main.py` - Replaced deprecated on_event with lifespan
- `tests/test_memory_service.py` - Added 4 new tests for Phase 2 functionality

## Phase 2 Schema Reference
```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY,
    person_id TEXT NOT NULL,
    char_id TEXT,
    scope TEXT NOT NULL DEFAULT 'character',  -- character, person_global, room, session
    type TEXT NOT NULL,  -- preference, fact, goal, relationship, project, open_loop
    text TEXT NOT NULL,
    importance FLOAT DEFAULT 0.5,
    fingerprint TEXT UNIQUE,  -- sha256(person_id|scope|char_id_or_empty|type|normalized_text)
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,  -- soft delete for auditability
    source_event_ids TEXT,  -- JSON array (merged on upsert)
    metadata TEXT  -- JSON
);

CREATE INDEX idx_mem_person_char_deleted ON memories(person_id, char_id, deleted_at);
CREATE INDEX idx_mem_person_scope_deleted ON memories(person_id, scope, deleted_at);
CREATE INDEX idx_mem_importance_updated ON memories(importance, updated_at);
```

**Key Features:**
- Fingerprint-based upsert (idempotent)
- Soft delete (deleted_at) for auditability
- Importance scoring for retrieval ranking
- Scope field (character/person_global/room/session) for explicit context
- Type allowlist enforcement (preference, fact, goal, relationship, project, open_loop)
- Transactional upsert with source_event_ids merge and importance update

**Fingerprint Computation:**
```python
sha256(person_id | scope | char_id_or_empty | type | normalized_text)
# normalized_text: strip() + collapse whitespace + lowercase for fingerprint only
# Store original-cased text in text field
```

**Upsert Behavior (in transaction):**
- If fingerprint exists: merge source_event_ids (set-union), update importance (max), bump updated_at
- If new: insert with provided values

**New Endpoints:**

`POST /v1/memories/upsert`
```json
{
  "person_id": "uuid",
  "char_id": "delilah",
  "scope": "character",
  "type": "preference",
  "text": "Call me Sam.",
  "importance": 0.8,
  "source_event_ids": [101, 103],
  "metadata": {"source": "extractor_rules_v1"}
}
```
Response: `{"status": "upserted", "id": 12, "fingerprint": "sha256...", "created": false}`

`GET /v1/memories/list?person_id=...&char_id=...&scope=...&include_deleted=false`
- Returns non-deleted by default
- Supports filtering by person_id, char_id, scope

`POST /v1/memories/forget`
```json
{"fingerprint": "sha256...", "reason": "user_request"}
# OR
{"id": 123, "reason": "user_request"}
```
Response: `{"status": "forgotten", "fingerprint": "..."}`

**Files to modify:**
- `services/memory/main.py` - Add memories table, endpoints, fingerprint logic, transaction handling
- `tests/test_memory_service.py` - Add tests for upsert idempotency, merge behavior, forget

## ✅ Phase 3: Memory Extraction (COMPLETE - Rules-First)

**Goal:** Extract important facts from events using conservative patterns

**Implemented:**
- extraction_rules.yaml with 9 rule categories
- RuleExtractor class with pattern matching, validation, deduplication
- POST /v1/memories/extract endpoint
- Returns candidates (proposed) and upserted (stored) for auditability
- Automatic person_id resolution if not provided
- Validation: max 500 chars, reject generic phrases, URL rules
- Template-based text formatting for consistency
- Pattern categories:
  - preferred_name (importance 0.9): "call me X", "I go by X"
  - personal facts (0.7): "my name is X", "I live in X"
  - preferences (0.6): "I like/hate X", "I prefer X"
  - goals (0.6): "I want to X", "my goal is X"
  - projects (0.7): "I'm working on X" (URLs allowed)
  - reminders (0.55): "remind me to X"
- Comprehensive test coverage
- All 47 tests passing

**Files Created:**
- `services/memory/extraction_rules.yaml` - Pattern definitions
- `services/memory/extraction.py` - RuleExtractor implementation

**Files Modified:**
- `services/memory/main.py` - Added extraction endpoint
- `tests/test_memory_service.py` - Added extraction test

**Future Enhancement:**
- LLM fallback behind use_llm flag for complex cases
- Strict JSON validation when LLM is added

**Goal:** Extract important facts from events (LLM can't be trusted with facts)

**Two-Step Process:**
1. **LLM Output:** Strict JSON only
   ```json
   {"memories": [{"type": "preference", "text": "...", "importance": 0.8}]}
   ```
2. **Service Validation:**
   - Parse JSON (reject if invalid)
   - Validate types in allowlist (preference, fact, goal, relationship, project, open_loop)
   - Normalize text (trim, collapse whitespace)
   - Reject too-long strings (>500 chars)
   - Reject memories containing URLs (unless type == project)
   - Compute fingerprint and upsert
   - Return 200 with `{memories: [], error: "invalid_schema"}` on failure (don't blow up)

**Implementation Strategy:**
- Start with rule-based extraction (regex for obvious patterns)
- Fall back to LLM for complex cases
- Never trust LLM to write SQL or execute code

**New Endpoint:**
- `POST /v1/memories/extract` - Extract from event(s), returns candidate memories

**Files to create:**
- `services/memory/extraction.py` - Extraction logic (rules + LLM fallback)
- Update `services/memory/main.py` - Add extraction endpoint

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

**Goal:** Return "curated + relevant + recent" with per-item source citations

**New query behavior:**
```python
results = {
    "curated": [
        {"id": 12, "type": "preference", "text": "Call me Sam.", 
         "importance": 0.8, "sources": [101, 103]}
    ],
    "semantic": [
        {"chunk_id": "...", "text": "...", "score": 0.72, 
         "source_event_id": 98}
    ],
    "recent": [...],
    "ts": "..."
}
```

**Search Order:**
1. Curated memories (importance + recency)
2. Semantic chunks (vector search)
3. Recent events (last N)

**Benefits:**
- Prevents "you told me" hallucinations (per-item sources for citation)
- Prioritizes important facts over recency
- Person-aware filtering (no memory leakage)

**Files to modify:**
- `services/memory/main.py` - Update `/v1/memory/query` logic

## Implementation Order

**✅ Completed:**
- PersonalityRenderer task routing refactor (explicit task_id parameter)
- Phase 1: Identity resolution with cathyAI-identity-db integration
- Phase 2: Curated memories with fingerprint-based upsert, soft delete, transactional merge
- Phase 3: Rule-based memory extraction (rules-first, LLM fallback later)

**Next PR (Phase 4 or LLM Enhancement):**
- Option A: Add LLM fallback to extraction (use_llm flag, strict JSON validation)
- Option B: Vector search with Qdrant integration
- Option C: Enhanced query API (curated + semantic + recent + sources)

**Future PRs:**
1. Phase 3: Memory extraction (rule-based + LLM validation)
2. Phase 4: Vector search (Qdrant integration)
3. Phase 5: Enhanced query API (curated + semantic + recent + sources)

## Notes

- Keep memory service stateless (no in-memory caches)
- All operations idempotent where possible (fingerprint-based upsert)
- Use transactions for multi-step operations (upsert + merge)
- Log all identity resolutions for debugging
- Privacy: soft delete (deleted_at) for auditability, hard delete available if needed
- LLM constraint: Only proposes candidate memories as JSON, service validates and stores
- Person-aware filtering prevents memory leakage across users
- Type allowlist: preference, fact, goal, relationship, project, open_loop
- Scope values: character (default), person_global, room, session
- Fingerprint normalization: strip + collapse whitespace + lowercase (store original text)
- URL rejection: Reject memories with URLs unless type == project
