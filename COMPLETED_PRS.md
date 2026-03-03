# Completed PRs Summary

## ✅ PR 1: Task Routing Refactor (READY TO MERGE)

**Commit:** `COMMIT_MSG_TASK_ROUTING.txt`

**Changes:**
- Added optional `task_id` parameter to `PersonalityRenderer.render()`
- Extracted `_infer_task()` method for backward-compatible mode inference
- Updated `_compose_prompt()` to accept explicit task parameter
- News bot now calls `await renderer.render(payload, task_id="news_digest_prefix")`
- Cleaner bot unchanged (continues using mode inference)

**Files Modified:**
- `framework/catcord_bots/personality.py`
- `news/__init__.py`

**Benefits:**
- Explicit and future-proof for new bots
- No more brittle mode-based inference
- Backward compatible
- All 42 tests passing

---

## ✅ PR 2: Phase 1 Identity Resolution (READY TO MERGE)

**Commit:** `COMMIT_MSG_IDENTITY_PHASE1.txt`

**Changes:**
- Implemented `normalize_external_id()` for consistent ID formatting
- Implemented `resolve_or_create_person_id()` with cathyAI-identity-db API
- GET /identity/resolve?external_id=... to resolve existing person_id
- POST /identity/link to create new person_id on 404
- x-api-key header authentication
- Fail-open behavior (NULL person_id + metadata flag if API down)
- Added IDENTITY_API_URL, IDENTITY_API_KEY, IDENTITY_API_TIMEOUT_S env vars

**Files Modified:**
- `services/memory/main.py`
- `docker-compose.yml`
- `services/.env.template`
- `README.md`

**API Contract (cathyAI-identity-db):**
- Auth: `x-api-key` header
- Resolve: `GET /identity/resolve?external_id=matrix:@user:server`
  - 200: `{"person_id": "...", "external_id": "...", "preferred_name": "..."}`
  - 404: Unknown user
- Link: `POST /identity/link` with `{"person_id": "...", "external_ids": [...], "preferred_name": "..."}`
  - 200: Success

**Benefits:**
- Ensures all events have reliable person_id
- Prevents identity fragmentation
- Graceful degradation when identity service unavailable
- All 42 tests passing

---

## Next Steps (Roadmap)

### Phase 2: Curated Memories Table
- Add `memories` table with schema:
  - `id`, `person_id`, `char_id`, `type`, `text`, `importance`, `created_at`, `updated_at`, `deleted_at`
  - `fingerprint` (sha256 of person_id|char_id|type|normalized_text) UNIQUE for idempotent upsert
- Upsert endpoint for storing validated memories
- Query endpoint enhancement to include curated memories

### Phase 3: Memory Extraction Endpoint
- LLM-based extraction with strict JSON validation
- Two-step process: model output → service validation
- Rule-based extraction first, LLM fallback for complex cases
- Reject invalid schemas gracefully (don't blow up pipeline)

### Phase 4: Vector Search (Optional)
- Qdrant integration for semantic search
- Keep curated memories separate from event chunks
- Search order: curated (importance + recency) → semantic chunks → recent events

### Phase 5: Enhanced Query API
- Include `sources` field in results for citation
- Combine curated memories + event history + semantic search
- Person-aware filtering to prevent memory leakage

---

## Testing

All 42 tests passing:
```bash
cd /home/ubk8751/cathyAI-bots
PYTHONPATH=/home/ubk8751/cathyAI-bots/framework:$PYTHONPATH python3 -m pytest tests/ -v
```

## Deployment

1. Rebuild framework:
   ```bash
   docker build -t catcord-bots-framework:latest -f framework/Dockerfile framework
   ```

2. Rebuild memory service:
   ```bash
   docker-compose build memory
   ```

3. Rebuild news bot:
   ```bash
   docker-compose build news
   ```

4. Configure identity API in `services/.env`:
   ```bash
   IDENTITY_API_URL=http://192.168.1.59:8092
   IDENTITY_API_KEY=your_key_here
   IDENTITY_API_TIMEOUT_S=3
   ```

5. Restart services:
   ```bash
   docker-compose up -d memory
   ```
