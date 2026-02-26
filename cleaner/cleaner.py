from __future__ import annotations
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from mautrix.types import EventType, RoomID, EventID, MessageEvent
from catcord_bots.matrix import MatrixSession, send_text
from catcord_bots.invites import join_all_invites


def get_disk_usage_ratio(path: str) -> float:
    st = os.statvfs(path)
    return 1.0 - (st.f_bavail / st.f_blocks)


def init_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.Connection(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            event_id TEXT PRIMARY KEY,
            room_id TEXT,
            sender TEXT,
            mxc_uri TEXT,
            mimetype TEXT,
            size INTEGER,
            timestamp INTEGER
        )
    """)
    conn.commit()
    return conn


def parse_mxc(mxc: str) -> Optional[Tuple[str, str]]:
    if not isinstance(mxc, str) or not mxc.startswith("mxc://"):
        return None
    parts = mxc[6:].split("/", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def find_media_files(media_root: str, mxc: str) -> List[Path]:
    parsed = parse_mxc(mxc)
    if not parsed:
        return []
    _, media_id = parsed
    hits: List[Path] = []
    for root, _, files in os.walk(media_root):
        for fn in files:
            if media_id in fn:
                hits.append(Path(root) / fn)
    return hits


async def log_upload(conn: sqlite3.Connection, event: MessageEvent) -> None:
    url = getattr(event.content, "url", None)
    if not url and hasattr(event.content, "file"):
        url = getattr(event.content.file, "url", None)
    if not url:
        return
    size = getattr(getattr(event.content, "info", None), "size", 0) or 0
    mimetype = getattr(getattr(event.content, "info", None), "mimetype", "") or ""
    conn.execute("""
        INSERT OR IGNORE INTO uploads (event_id, room_id, sender, mxc_uri, mimetype, size, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (str(event.event_id), str(event.room_id), str(event.sender), str(url), str(mimetype), int(size), int(event.timestamp)))
    conn.commit()


async def sync_uploads(session: MatrixSession, conn: sqlite3.Connection, rooms_allowlist: list[str]) -> None:
    rooms = await session.client.get_joined_rooms()
    if rooms_allowlist:
        rooms = [r for r in rooms if str(r) in rooms_allowlist]
    for room_id in rooms:
        try:
            resp = await session.client.get_messages(room_id, limit=200)
            for event in resp.chunk:
                if event.type == EventType.ROOM_MESSAGE:
                    await log_upload(conn, event)
        except Exception:
            continue


@dataclass
class Policy:
    image_days: int = 90
    non_image_days: int = 30
    pressure: float = 0.85
    emergency: float = 0.92


async def run_retention(
    session: MatrixSession,
    conn: sqlite3.Connection,
    media_root: str,
    policy: Policy,
    notifications_room: Optional[str],
    send_zero: bool,
    dry_run: bool,
) -> None:
    cutoff_img = int((datetime.now() - timedelta(days=policy.image_days)).timestamp() * 1000)
    cutoff_non = int((datetime.now() - timedelta(days=policy.non_image_days)).timestamp() * 1000)
    cur = conn.execute("""
        SELECT event_id, room_id, mxc_uri, mimetype, size, timestamp
        FROM uploads
        WHERE (mimetype LIKE 'image/%' AND timestamp < ?)
           OR (mimetype NOT LIKE 'image/%' AND timestamp < ?)
        ORDER BY (mimetype LIKE 'image/%') ASC, timestamp ASC, size DESC
    """, (cutoff_img, cutoff_non))
    deleted = 0
    freed = 0
    for event_id, room_id, mxc_uri, mimetype, size, ts in cur.fetchall():
        paths = find_media_files(media_root, mxc_uri)
        if dry_run:
            print(f"[DRY-RUN] Would redact+delete {event_id} files={len(paths)}")
            deleted += 1
            continue
        try:
            await session.client.redact(RoomID(room_id), EventID(event_id), reason="Catcord cleanup: retention")
            for p in paths:
                if p.exists():
                    freed += p.stat().st_size
                    p.unlink()
            conn.execute("DELETE FROM uploads WHERE event_id = ?", (event_id,))
            conn.commit()
            deleted += 1
        except Exception as e:
            print(f"retention failed {event_id}: {e}")
    if notifications_room and (deleted > 0 or send_zero or dry_run):
        prefix = "[DRY-RUN] " if dry_run else ""
        await send_text(session, notifications_room, f"{prefix}🧹 Retention: deleted={deleted} freed={freed/1024/1024:.1f}MB")


async def run_pressure(
    session: MatrixSession,
    conn: sqlite3.Connection,
    media_root: str,
    policy: Policy,
    notifications_room: Optional[str],
    send_zero: bool,
    dry_run: bool,
) -> None:
    used = get_disk_usage_ratio(media_root)
    if used < policy.pressure:
        print(f"disk usage {used:.3f} < {policy.pressure:.3f}, no action")
        return
    cur = conn.execute("""
        SELECT event_id, room_id, mxc_uri, mimetype, size, timestamp
        FROM uploads
        ORDER BY (mimetype LIKE 'image/%') ASC, size DESC, timestamp ASC
    """)
    deleted = 0
    freed = 0
    for event_id, room_id, mxc_uri, mimetype, size, ts in cur.fetchall():
        used = get_disk_usage_ratio(media_root)
        if used < policy.pressure:
            break
        paths = find_media_files(media_root, mxc_uri)
        if dry_run:
            print(f"[DRY-RUN] Would redact+delete {event_id} files={len(paths)} used={used:.3f}")
            deleted += 1
            continue
        try:
            reason = "emergency" if used >= policy.emergency else "pressure"
            await session.client.redact(RoomID(room_id), EventID(event_id), reason=f"Catcord cleanup: {reason}")
            for p in paths:
                if p.exists():
                    freed += p.stat().st_size
                    p.unlink()
            conn.execute("DELETE FROM uploads WHERE event_id = ?", (event_id,))
            conn.commit()
            deleted += 1
        except Exception as e:
            print(f"pressure failed {event_id}: {e}")
    if notifications_room and (deleted > 0 or send_zero or dry_run):
        prefix = "[DRY-RUN] " if dry_run else ""
        await send_text(session, notifications_room, f"{prefix}⚠️ Pressure: deleted={deleted} freed={freed/1024/1024:.1f}MB")
