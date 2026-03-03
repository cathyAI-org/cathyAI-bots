"""Online fetch service for RSS/Atom feeds and URL previews."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
import feedparser
import httpx
import sqlite3
import hashlib
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    global ALLOWLIST_ROOMS
    allowlist_str = os.getenv("ONLINE_ALLOWLIST_ROOMS", "")
    if allowlist_str:
        ALLOWLIST_ROOMS = set(r.strip() for r in allowlist_str.split(",") if r.strip())
    init_db()
    print(f"Online service started (allowlist={len(ALLOWLIST_ROOMS)} rooms)")
    yield


app = FastAPI(title="catcord-online", version="1.0.0", lifespan=lifespan)

DB_PATH = Path("/state/cache.sqlite3")
ALLOWLIST_ROOMS = set()


class FetchRequest(BaseModel):
    """RSS fetch request."""
    feeds: List[str] = Field(..., description="Feed URLs to fetch")
    lookback_hours: int = Field(24, description="Only include items newer than this")
    max_items: int = Field(10, description="Maximum items to return")
    caller: Dict[str, Any] = Field(..., description="Caller info (bot, room_id)")
    timeout_s: Optional[float] = Field(None, description="Request timeout override")
    user_agent: Optional[str] = Field(None, description="User agent override")


class FetchResponse(BaseModel):
    """RSS fetch response."""
    items: List[Dict[str, Any]]
    fetched_at: str


def init_db():
    """Initialize cache database.
    
    :return: None
    :rtype: None
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            url TEXT PRIMARY KEY,
            etag TEXT,
            last_modified TEXT,
            content_hash TEXT,
            fetched_at TEXT,
            response_data TEXT
        )
    """)
    conn.commit()
    conn.close()


@app.get("/health")
async def health():
    """Health check endpoint.
    
    :return: Health status
    :rtype: Dict[str, str]
    """
    return {"status": "ok"}


@app.post("/v1/rss/fetch", response_model=FetchResponse)
async def fetch_rss(req: FetchRequest):
    """Fetch RSS/Atom feeds with caching.
    
    :param req: Fetch request
    :type req: FetchRequest
    :return: Fetch response
    :rtype: FetchResponse
    :raises HTTPException: If room not in allowlist
    """
    # Check allowlist if configured
    if ALLOWLIST_ROOMS:
        room_id = req.caller.get("room_id")
        if room_id and room_id not in ALLOWLIST_ROOMS:
            raise HTTPException(status_code=403, detail="Room not in allowlist")
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=req.lookback_hours)
    items: List[Dict[str, Any]] = []
    
    user_agent = req.user_agent or "catcord-online/1.0"
    timeout_s = req.timeout_s or 10.0
    
    headers = {"User-Agent": user_agent}
    timeout = httpx.Timeout(timeout_s)
    
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc).isoformat()
    
    try:
        async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
            for feed_url in req.feeds:
                try:
                    cached = conn.execute(
                        "SELECT etag, last_modified, content_hash, response_data FROM cache WHERE url = ?",
                        (feed_url,)
                    ).fetchone()
                    
                    req_headers = {}
                    if cached:
                        if cached[0]:
                            req_headers["If-None-Match"] = cached[0]
                        if cached[1]:
                            req_headers["If-Modified-Since"] = cached[1]
                    
                    resp = await client.get(feed_url, headers=req_headers)
                    
                    if resp.status_code == 304 and cached:
                        feed_data = json.loads(cached[3])
                        conn.execute(
                            "UPDATE cache SET fetched_at = ? WHERE url = ?",
                            (now, feed_url)
                        )
                        conn.commit()
                    else:
                        resp.raise_for_status()
                        feed = feedparser.parse(resp.text)
                        
                        source = feed.feed.get("title", "Unknown")
                        feed_items = []
                        
                        for entry in feed.entries:
                            pub_dt = _parse_published(entry)
                            if not pub_dt or pub_dt < cutoff:
                                continue
                            
                            title = entry.get("title", "").strip()
                            link = entry.get("link", "").strip()
                            snippet = _extract_snippet(entry)
                            
                            if not title or not link:
                                continue
                            
                            feed_items.append({
                                "title": title,
                                "source": source,
                                "url": link,
                                "published_at": pub_dt.isoformat(),
                                "snippet": snippet,
                                "feed_url": feed_url,
                            })
                        
                        feed_data = {"items": feed_items}
                        
                        content_hash = hashlib.sha256(
                            json.dumps(feed_data, sort_keys=True).encode()
                        ).hexdigest()
                        
                        if cached and cached[2] == content_hash:
                            conn.execute(
                                "UPDATE cache SET fetched_at = ? WHERE url = ?",
                                (now, feed_url)
                            )
                        else:
                            etag = resp.headers.get("etag")
                            last_mod = resp.headers.get("last-modified")
                            
                            conn.execute("""
                                INSERT OR REPLACE INTO cache
                                (url, etag, last_modified, content_hash, fetched_at, response_data)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (
                                feed_url,
                                etag,
                                last_mod,
                                content_hash,
                                now,
                                json.dumps(feed_data),
                            ))
                        conn.commit()
                    
                    items.extend(feed_data["items"])
                    
                except Exception as e:
                    print(f"Error fetching {feed_url}: {e!r}")
                    continue
    finally:
        conn.close()
    
    items.sort(key=lambda x: x["published_at"], reverse=True)
    items = items[:req.max_items]
    
    return FetchResponse(
        items=items,
        fetched_at=now,
    )


def _parse_published(entry: Any) -> Optional[datetime]:
    """Parse published date from feed entry.
    
    :param entry: Feed entry
    :type entry: Any
    :return: Published datetime or None
    :rtype: Optional[datetime]
    """
    for field in ["published_parsed", "updated_parsed"]:
        ts = getattr(entry, field, None)
        if ts:
            try:
                return datetime(*ts[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _strip_html(text: str) -> str:
    """Strip HTML tags and collapse whitespace.
    
    :param text: Text with HTML
    :type text: str
    :return: Plain text
    :rtype: str
    """
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _extract_snippet(entry: Any) -> str:
    """Extract snippet from feed entry.
    
    :param entry: Feed entry
    :type entry: Any
    :return: Snippet text (max 280 chars)
    :rtype: str
    """
    text = ""
    if hasattr(entry, "summary"):
        text = entry.summary
    elif hasattr(entry, "description"):
        text = entry.description
    
    text = _strip_html(text)
    if len(text) > 280:
        text = text[:277] + "..."
    return text


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8088)
