"""Memory/RAG service for event storage and retrieval."""
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
import sqlite3
import httpx
import os
import json
import uuid
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    global IDENTITY_API_URL, IDENTITY_API_KEY, IDENTITY_API_TIMEOUT_S
    IDENTITY_API_URL = os.getenv("IDENTITY_API_URL")
    IDENTITY_API_KEY = os.getenv("IDENTITY_API_KEY")
    IDENTITY_API_TIMEOUT_S = float(os.getenv("IDENTITY_API_TIMEOUT_S", "3.0"))
    init_db()
    print(f"Memory service started (identity={'enabled' if IDENTITY_API_URL else 'disabled'})")
    yield


app = FastAPI(title="catcord-memory", version="1.0.0", lifespan=lifespan)

DB_PATH = Path("/state/db.sqlite3")
IDENTITY_API_URL = None
IDENTITY_API_KEY = None
IDENTITY_API_TIMEOUT_S = 3.0


class IngestRequest(BaseModel):
    """Event ingest request."""
    source: str = Field(..., description="Event source (matrix, chainlit, bot)")
    external_user_id: str = Field(..., description="External user ID")
    person_id: Optional[str] = Field(None, description="Resolved person ID")
    room_id: Optional[str] = Field(None, description="Room/session ID")
    session_id: Optional[str] = Field(None, description="Session ID")
    char_id: Optional[str] = Field(None, description="Character ID")
    role: str = Field(..., description="Message role (user, assistant, system)")
    content: str = Field(..., description="Message content")
    ts: str = Field(..., description="ISO timestamp")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Extra metadata")


class IngestResponse(BaseModel):
    """Event ingest response."""
    event_id: int
    person_id: Optional[str]


class QueryRequest(BaseModel):
    """Memory query request."""
    person_id: Optional[str] = Field(None, description="Filter by person")
    char_id: Optional[str] = Field(None, description="Filter by character")
    query: Optional[str] = Field(None, description="Search query (future: vector)")
    k: int = Field(10, description="Number of results")
    filters: Optional[Dict[str, Any]] = Field(None, description="Additional filters")


class QueryResponse(BaseModel):
    """Memory query response."""
    results: List[Dict[str, Any]]


class MemoryUpsertRequest(BaseModel):
    """Memory upsert request."""
    person_id: str = Field(..., description="Person ID")
    char_id: Optional[str] = Field(None, description="Character ID")
    scope: str = Field("character", description="Scope (character, person_global, room, session)")
    type: str = Field(..., description="Memory type (preference, fact, goal, relationship, project, open_loop)")
    text: str = Field(..., description="Memory text")
    importance: float = Field(0.5, description="Importance score (0.0-1.0)")
    source_event_ids: Optional[List[int]] = Field(None, description="Source event IDs")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Extra metadata")


class MemoryUpsertResponse(BaseModel):
    """Memory upsert response."""
    status: str
    id: int
    fingerprint: str
    created: bool


class MemoryForgetRequest(BaseModel):
    """Memory forget request."""
    id: Optional[int] = Field(None, description="Memory ID")
    fingerprint: Optional[str] = Field(None, description="Memory fingerprint")
    reason: Optional[str] = Field(None, description="Reason for forgetting")


class MemoryForgetResponse(BaseModel):
    """Memory forget response."""
    status: str
    fingerprint: Optional[str]


TYPE_ALLOWLIST = {"preference", "fact", "goal", "relationship", "project", "open_loop"}
SCOPE_ALLOWLIST = {"character", "person_global", "room", "session"}


def init_db():
    """Initialize memory database.
    
    :return: None
    :rtype: None
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    
    # Events table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            external_user_id TEXT NOT NULL,
            person_id TEXT,
            room_id TEXT,
            session_id TEXT,
            char_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            ts TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_person_id ON events(person_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_char_id ON events(char_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ts ON events(ts)
    """)
    
    # Memories table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id TEXT NOT NULL,
            char_id TEXT,
            scope TEXT NOT NULL DEFAULT 'character',
            type TEXT NOT NULL,
            text TEXT NOT NULL,
            importance REAL DEFAULT 0.5,
            fingerprint TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            source_event_ids TEXT,
            metadata TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mem_person_char_deleted 
        ON memories(person_id, char_id, deleted_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mem_person_scope_deleted 
        ON memories(person_id, scope, deleted_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mem_importance_updated 
        ON memories(importance, updated_at)
    """)
    
    conn.commit()
    conn.close()


def normalize_external_id(source: str, external_user_id: str) -> str:
    """Normalize external ID to consistent format.
    
    :param source: Source system
    :type source: str
    :param external_user_id: External user ID
    :type external_user_id: str
    :return: Normalized external ID
    :rtype: str
    """
    s = (source or "").strip().lower()
    ext = (external_user_id or "").strip()
    if not ext:
        return ext
    if any(ext.startswith(p) for p in ("matrix:", "chainlit:", "discord:")):
        return ext
    if s == "matrix" and ext.startswith("@"):
        return f"matrix:{ext}"
    if s == "chainlit":
        return f"chainlit:username:{ext}"
    return f"{s}:{ext}" if s else ext


async def resolve_or_create_person_id(
    source: str, external_user_id: str, preferred_name: Optional[str] = None
) -> Optional[str]:
    """Resolve or create person ID via identity API.
    
    :param source: Source system
    :type source: str
    :param external_user_id: External user ID
    :type external_user_id: str
    :param preferred_name: Optional preferred name
    :type preferred_name: Optional[str]
    :return: Resolved/created person ID or None on failure
    :rtype: Optional[str]
    """
    if not IDENTITY_API_URL or not IDENTITY_API_KEY:
        return None
    
    external_id = normalize_external_id(source, external_user_id)
    if not external_id:
        return None
    
    headers = {"x-api-key": IDENTITY_API_KEY}
    timeout = httpx.Timeout(IDENTITY_API_TIMEOUT_S)
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Try resolve
            resp = await client.get(
                f"{IDENTITY_API_URL}/identity/resolve",
                params={"external_id": external_id},
                headers=headers,
            )
            
            if resp.status_code == 200:
                person_id = resp.json().get("person_id")
                print(f"Resolved {external_id} -> {person_id}")
                return person_id
            
            if resp.status_code != 404:
                print(f"Identity resolve error {resp.status_code} for {external_id}")
                return None
            
            # Unknown -> create + link
            new_person_id = str(uuid.uuid4())
            body = {
                "person_id": new_person_id,
                "external_ids": [external_id],
            }
            if preferred_name:
                body["preferred_name"] = preferred_name
            
            link_resp = await client.post(
                f"{IDENTITY_API_URL}/identity/link",
                json=body,
                headers=headers,
            )
            
            if link_resp.status_code == 200:
                print(f"Created {external_id} -> {new_person_id}")
                return new_person_id
            
            print(f"Identity link error {link_resp.status_code} for {external_id}")
            return None
            
    except Exception as e:
        print(f"Identity resolution failed for {external_id}: {e!r}")
        return None


def normalize_text_for_fingerprint(text: str) -> str:
    """Normalize text for fingerprint computation.
    
    :param text: Original text
    :type text: str
    :return: Normalized text
    :rtype: str
    """
    normalized = text.strip().lower()
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized


def compute_memory_fingerprint(
    person_id: str, scope: str, char_id: Optional[str], type: str, text: str
) -> str:
    """Compute memory fingerprint for idempotent upsert.
    
    :param person_id: Person ID
    :type person_id: str
    :param scope: Scope
    :type scope: str
    :param char_id: Character ID
    :type char_id: Optional[str]
    :param type: Memory type
    :type type: str
    :param text: Memory text
    :type text: str
    :return: SHA256 fingerprint
    :rtype: str
    """
    normalized_text = normalize_text_for_fingerprint(text)
    char_part = char_id or ""
    payload = f"{person_id}|{scope}|{char_part}|{type}|{normalized_text}"
    return hashlib.sha256(payload.encode()).hexdigest()


@app.get("/health")
async def health():
    """Health check endpoint.
    
    :return: Health status
    :rtype: Dict[str, str]
    """
    return {"status": "ok"}


@app.post("/v1/events/ingest", response_model=IngestResponse)
async def ingest_event(req: IngestRequest):
    """Ingest event into memory store.
    
    :param req: Ingest request
    :type req: IngestRequest
    :return: Ingest response
    :rtype: IngestResponse
    """
    # Resolve person_id if not provided
    person_id = req.person_id
    metadata = req.metadata or {}
    
    if not person_id:
        person_id = await resolve_or_create_person_id(
            req.source, req.external_user_id
        )
        if not person_id:
            metadata["identity_resolution"] = "failed"
    
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute("""
            INSERT INTO events
            (source, external_user_id, person_id, room_id, session_id, char_id,
             role, content, ts, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            req.source,
            req.external_user_id,
            person_id,
            req.room_id,
            req.session_id,
            req.char_id,
            req.role,
            req.content,
            req.ts,
            json.dumps(metadata) if metadata else None,
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()
        event_id = cursor.lastrowid
    finally:
        conn.close()
    
    return IngestResponse(event_id=event_id, person_id=person_id)


@app.post("/v1/memory/query", response_model=QueryResponse)
async def query_memory(req: QueryRequest):
    """Query memory store.
    
    :param req: Query request
    :type req: QueryRequest
    :return: Query response
    :rtype: QueryResponse
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        where_clauses = []
        params = []
        
        if req.person_id:
            where_clauses.append("person_id = ?")
            params.append(req.person_id)
        
        if req.char_id:
            where_clauses.append("char_id = ?")
            params.append(req.char_id)
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        cursor = conn.execute(f"""
            SELECT id, source, external_user_id, person_id, room_id, session_id,
                   char_id, role, content, ts, metadata
            FROM events
            WHERE {where_sql}
            ORDER BY ts DESC
            LIMIT ?
        """, params + [req.k])
        
        results = []
        for row in cursor.fetchall():
            results.append({
                "id": row[0],
                "source": row[1],
                "external_user_id": row[2],
                "person_id": row[3],
                "room_id": row[4],
                "session_id": row[5],
                "char_id": row[6],
                "role": row[7],
                "content": row[8],
                "ts": row[9],
                "metadata": json.loads(row[10]) if row[10] else None,
            })
    finally:
        conn.close()
    
    return QueryResponse(results=results)


@app.post("/v1/memories/upsert", response_model=MemoryUpsertResponse)
async def upsert_memory(req: MemoryUpsertRequest):
    """Upsert curated memory (idempotent via fingerprint).
    
    :param req: Upsert request
    :type req: MemoryUpsertRequest
    :return: Upsert response
    :rtype: MemoryUpsertResponse
    """
    # Validate type and scope
    if req.type not in TYPE_ALLOWLIST:
        raise ValueError(f"Invalid type: {req.type}. Must be one of {TYPE_ALLOWLIST}")
    if req.scope not in SCOPE_ALLOWLIST:
        raise ValueError(f"Invalid scope: {req.scope}. Must be one of {SCOPE_ALLOWLIST}")
    
    # Compute fingerprint
    fingerprint = compute_memory_fingerprint(
        req.person_id, req.scope, req.char_id, req.type, req.text
    )
    
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("BEGIN")
        
        # Check if exists
        cursor = conn.execute(
            "SELECT id, importance, source_event_ids FROM memories WHERE fingerprint = ?",
            (fingerprint,)
        )
        existing = cursor.fetchone()
        
        now = datetime.now(timezone.utc).isoformat()
        source_ids = req.source_event_ids or []
        
        if existing:
            # Upsert: merge source_event_ids, update importance (max), bump updated_at
            mem_id, old_importance, old_source_ids_json = existing
            old_source_ids = json.loads(old_source_ids_json) if old_source_ids_json else []
            merged_source_ids = sorted(set(old_source_ids + source_ids))
            new_importance = max(old_importance, req.importance)
            
            conn.execute("""
                UPDATE memories
                SET importance = ?, source_event_ids = ?, updated_at = ?, metadata = ?
                WHERE fingerprint = ?
            """, (
                new_importance,
                json.dumps(merged_source_ids),
                now,
                json.dumps(req.metadata) if req.metadata else None,
                fingerprint,
            ))
            created = False
        else:
            # Insert new
            cursor = conn.execute("""
                INSERT INTO memories
                (person_id, char_id, scope, type, text, importance, fingerprint,
                 created_at, updated_at, source_event_ids, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                req.person_id,
                req.char_id,
                req.scope,
                req.type,
                req.text,
                req.importance,
                fingerprint,
                now,
                now,
                json.dumps(source_ids),
                json.dumps(req.metadata) if req.metadata else None,
            ))
            mem_id = cursor.lastrowid
            created = True
        
        conn.commit()
        return MemoryUpsertResponse(
            status="upserted",
            id=mem_id,
            fingerprint=fingerprint,
            created=created,
        )
    finally:
        conn.close()


@app.get("/v1/memories/list")
async def list_memories(
    person_id: Optional[str] = None,
    char_id: Optional[str] = None,
    scope: Optional[str] = None,
    include_deleted: bool = False,
):
    """List curated memories.
    
    :param person_id: Filter by person ID
    :type person_id: Optional[str]
    :param char_id: Filter by character ID
    :type char_id: Optional[str]
    :param scope: Filter by scope
    :type scope: Optional[str]
    :param include_deleted: Include soft-deleted memories
    :type include_deleted: bool
    :return: List of memories
    :rtype: Dict[str, List[Dict[str, Any]]]
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        where_clauses = []
        params = []
        
        if person_id:
            where_clauses.append("person_id = ?")
            params.append(person_id)
        
        if char_id:
            where_clauses.append("char_id = ?")
            params.append(char_id)
        
        if scope:
            where_clauses.append("scope = ?")
            params.append(scope)
        
        if not include_deleted:
            where_clauses.append("deleted_at IS NULL")
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        cursor = conn.execute(f"""
            SELECT id, person_id, char_id, scope, type, text, importance,
                   fingerprint, created_at, updated_at, deleted_at,
                   source_event_ids, metadata
            FROM memories
            WHERE {where_sql}
            ORDER BY importance DESC, updated_at DESC
        """, params)
        
        results = []
        for row in cursor.fetchall():
            results.append({
                "id": row[0],
                "person_id": row[1],
                "char_id": row[2],
                "scope": row[3],
                "type": row[4],
                "text": row[5],
                "importance": row[6],
                "fingerprint": row[7],
                "created_at": row[8],
                "updated_at": row[9],
                "deleted_at": row[10],
                "sources": json.loads(row[11]) if row[11] else [],
                "metadata": json.loads(row[12]) if row[12] else None,
            })
        
        return {"memories": results}
    finally:
        conn.close()


@app.post("/v1/memories/forget", response_model=MemoryForgetResponse)
async def forget_memory(req: MemoryForgetRequest):
    """Soft delete memory by ID or fingerprint.
    
    :param req: Forget request
    :type req: MemoryForgetRequest
    :return: Forget response
    :rtype: MemoryForgetResponse
    """
    if not req.id and not req.fingerprint:
        raise ValueError("Must provide either id or fingerprint")
    
    conn = sqlite3.connect(DB_PATH)
    try:
        now = datetime.now(timezone.utc).isoformat()
        
        if req.fingerprint:
            cursor = conn.execute(
                "UPDATE memories SET deleted_at = ? WHERE fingerprint = ? AND deleted_at IS NULL",
                (now, req.fingerprint)
            )
            fingerprint = req.fingerprint
        else:
            cursor = conn.execute(
                "UPDATE memories SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                (now, req.id)
            )
            # Fetch fingerprint for response
            fp_cursor = conn.execute(
                "SELECT fingerprint FROM memories WHERE id = ?",
                (req.id,)
            )
            fp_row = fp_cursor.fetchone()
            fingerprint = fp_row[0] if fp_row else None
        
        conn.commit()
        
        if cursor.rowcount == 0:
            return MemoryForgetResponse(status="not_found", fingerprint=fingerprint)
        
        return MemoryForgetResponse(status="forgotten", fingerprint=fingerprint)
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
