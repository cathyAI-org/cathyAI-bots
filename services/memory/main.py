"""Memory/RAG service for event storage and retrieval."""
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import sqlite3
import httpx
import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

app = FastAPI(title="catcord-memory", version="1.0.0")

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


def init_db():
    """Initialize memory database.
    
    :return: None
    :rtype: None
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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


@app.on_event("startup")
async def startup():
    """Initialize service on startup.
    
    :return: None
    :rtype: None
    """
    global IDENTITY_API_URL, IDENTITY_API_KEY, IDENTITY_API_TIMEOUT_S
    IDENTITY_API_URL = os.getenv("IDENTITY_API_URL")
    IDENTITY_API_KEY = os.getenv("IDENTITY_API_KEY")
    IDENTITY_API_TIMEOUT_S = float(os.getenv("IDENTITY_API_TIMEOUT_S", "3.0"))
    init_db()
    print(f"Memory service started (identity={'enabled' if IDENTITY_API_URL else 'disabled'})")


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
