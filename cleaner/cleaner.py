from __future__ import annotations
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from mautrix.types import EventType, RoomID, EventID, MessageEvent, PaginationDirection
from catcord_bots.matrix import MatrixSession, send_text
from catcord_bots.invites import join_all_invites
from catcord_bots.personality import PersonalityRenderer


def get_disk_usage_ratio(path: str) -> float:
    st = os.statvfs(path)
    return 1.0 - (st.f_bavail / st.f_blocks)


def init_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
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


def extract_mxc_and_info(event) -> tuple[str | None, str, int]:
    c = getattr(event, "content", None)
    url = None
    mimetype = ""
    size = 0

    if hasattr(c, "serialize"):
        c = c.serialize()

    if isinstance(c, dict):
        url = c.get("url")
        if not url and isinstance(c.get("file"), dict):
            url = c["file"].get("url")

        info = c.get("info") if isinstance(c.get("info"), dict) else {}
        mimetype = info.get("mimetype", "") or ""
        size = int(info.get("size") or 0)
    else:
        url = getattr(c, "url", None)
        if not url and hasattr(c, "file"):
            url = getattr(getattr(c, "file", None), "url", None)

        info = getattr(c, "info", None)
        mimetype = getattr(info, "mimetype", "") if info else ""
        size = int(getattr(info, "size", 0) if info else 0)

    return url, mimetype, size


async def log_upload(conn: sqlite3.Connection, event: MessageEvent) -> None:
    url, mimetype, size = extract_mxc_and_info(event)
    if not url or not isinstance(url, str) or not url.startswith("mxc://"):
        return

    conn.execute("""
        INSERT OR IGNORE INTO uploads (event_id, room_id, sender, mxc_uri, mimetype, size, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (str(event.event_id), str(event.room_id), str(event.sender), url, mimetype, size, int(event.timestamp)))
    conn.commit()


async def sync_uploads(session: MatrixSession, conn: sqlite3.Connection, rooms_allowlist: list[str]) -> None:
    rooms = await session.client.get_joined_rooms()
    if rooms_allowlist:
        rooms = [r for r in rooms if str(r) in rooms_allowlist]
    for room_id in rooms:
        try:
            resp = await session.client.get_messages(
                room_id,
                direction=PaginationDirection.BACKWARD,
                limit=200,
            )
            for event in resp.events:
                t = str(event.type)
                if t in ("m.room.message", "m.sticker"):
                    await log_upload(conn, event)
        except Exception as e:
            print(f"Sync error in {room_id}: {e}")


@dataclass
class Policy:
    image_days: int = 90
    non_image_days: int = 30
    pressure: float = 0.85
    emergency: float = 0.92


@dataclass
class PersonalityConfig:
    enabled: bool = False
    characters_api_url: str = "http://192.168.1.59:8091"
    character_id: str = "irina"
    cathy_api_url: str = "http://192.168.1.59:8100"
    cathy_api_key: Optional[str] = None
    timeout_seconds: float = 6
    connect_timeout_seconds: float = 2
    max_tokens: int = 180
    temperature: float = 0.2
    top_p: float = 0.9
    min_seconds_between_calls: int = 30
    fallback_system_prompt: str = "You are a maintenance bot. Write short, calm, factual ops updates."
    cathy_api_mode: str = "openai"
    cathy_api_model: str = "cathy"


async def run_retention(
    session: MatrixSession,
    conn: sqlite3.Connection,
    media_root: str,
    policy: Policy,
    notifications_room: Optional[str],
    send_zero: bool,
    dry_run: bool,
    ai_cfg: Optional[PersonalityConfig] = None,
) -> None:
    start_time = datetime.now()
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
    deleted_images = 0
    deleted_non_images = 0
    for event_id, room_id, mxc_uri, mimetype, size, ts in cur.fetchall():
        paths = find_media_files(media_root, mxc_uri)
        if dry_run:
            print(f"[DRY-RUN] Would redact+delete {event_id} files={len(paths)}")
            deleted += 1
            if mimetype.startswith("image/"):
                deleted_images += 1
            else:
                deleted_non_images += 1
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
            if mimetype.startswith("image/"):
                deleted_images += 1
            else:
                deleted_non_images += 1
        except Exception as e:
            print(f"retention failed {event_id}: {e}")
    
    if notifications_room and (deleted > 0 or send_zero or dry_run):
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        summary_payload = {
            "run_id": f"{start_time.isoformat()}Z-retention",
            "mode": "retention",
            "server": "catcord",
            "policy": {
                "retention_days_images": policy.image_days,
                "retention_days_non_images": policy.non_image_days,
            },
            "actions": {
                "deleted_count": deleted,
                "freed_gb": round(freed / 1024 / 1024 / 1024, 2),
                "deleted_by_type": {
                    "images": deleted_images,
                    "non_images": deleted_non_images,
                },
            },
            "timing": {
                "started_at": start_time.isoformat() + "Z",
                "ended_at": end_time.isoformat() + "Z",
                "duration_seconds": int(duration),
            },
        }
        
        prefix = "[DRY-RUN] " if dry_run else ""
        freed_gb = freed / 1024 / 1024 / 1024
        fallback = (
            f"{prefix}🧹 Retention: deleted={deleted} "
            f"(images={deleted_images}, non_images={deleted_non_images}), "
            f"freed_gb={freed_gb:.2f}"
        )
        
        message = fallback
        if ai_cfg and ai_cfg.enabled:
            try:
                renderer = PersonalityRenderer(
                    characters_api_url=ai_cfg.characters_api_url,
                    character_id=ai_cfg.character_id,
                    cathy_api_url=ai_cfg.cathy_api_url,
                    fallback_system_prompt=ai_cfg.fallback_system_prompt,
                    cathy_api_key=ai_cfg.cathy_api_key,
                    timeout_seconds=ai_cfg.timeout_seconds,
                    connect_timeout_seconds=ai_cfg.connect_timeout_seconds,
                    max_tokens=ai_cfg.max_tokens,
                    temperature=ai_cfg.temperature,
                    top_p=ai_cfg.top_p,
                    min_seconds_between_calls=ai_cfg.min_seconds_between_calls,
                    cathy_api_mode=ai_cfg.cathy_api_mode,
                    cathy_api_model=ai_cfg.cathy_api_model,
                )
                rendered = await renderer.render(summary_payload)
                if rendered:
                    message = prefix + rendered
            except Exception:
                pass
        
        await send_text(session, notifications_room, message)


async def run_pressure(
    session: MatrixSession,
    conn: sqlite3.Connection,
    media_root: str,
    policy: Policy,
    notifications_room: Optional[str],
    send_zero: bool,
    dry_run: bool,
    ai_cfg: Optional[PersonalityConfig] = None,
) -> None:
    start_time = datetime.now()
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
    deleted_images = 0
    deleted_non_images = 0
    disk_before = used * 100
    for event_id, room_id, mxc_uri, mimetype, size, ts in cur.fetchall():
        used = get_disk_usage_ratio(media_root)
        if used < policy.pressure:
            break
        paths = find_media_files(media_root, mxc_uri)
        if dry_run:
            print(f"[DRY-RUN] Would redact+delete {event_id} files={len(paths)} used={used:.3f}")
            deleted += 1
            if mimetype.startswith("image/"):
                deleted_images += 1
            else:
                deleted_non_images += 1
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
            if mimetype.startswith("image/"):
                deleted_images += 1
            else:
                deleted_non_images += 1
        except Exception as e:
            print(f"pressure failed {event_id}: {e}")
    
    if notifications_room and (deleted > 0 or send_zero or dry_run):
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        disk_after = get_disk_usage_ratio(media_root) * 100
        
        summary_payload = {
            "run_id": f"{start_time.isoformat()}Z-pressure",
            "mode": "pressure",
            "server": "catcord",
            "disk": {
                "mount": media_root,
                "percent_before": round(disk_before, 1),
                "percent_after": round(disk_after, 1),
                "pressure_threshold": policy.pressure * 100,
                "emergency_threshold": policy.emergency * 100,
            },
            "policy": {
                "prefer_large_non_images": True,
            },
            "actions": {
                "deleted_count": deleted,
                "freed_gb": round(freed / 1024 / 1024 / 1024, 2),
                "deleted_by_type": {
                    "images": deleted_images,
                    "non_images": deleted_non_images,
                },
            },
            "timing": {
                "started_at": start_time.isoformat() + "Z",
                "ended_at": end_time.isoformat() + "Z",
                "duration_seconds": int(duration),
            },
        }
        
        prefix = "[DRY-RUN] " if dry_run else ""
        freed_gb = freed / 1024 / 1024 / 1024
        fallback = (
            f"{prefix}⚠️ Pressure cleanup: disk={disk_before:.1f}%→{disk_after:.1f}% "
            f"(threshold={policy.pressure*100:.1f}%, emergency={policy.emergency*100:.1f}%), "
            f"deleted={deleted} (images={deleted_images}, non_images={deleted_non_images}), "
            f"freed_gb={freed_gb:.2f}"
        )
        
        message = fallback
        if ai_cfg and ai_cfg.enabled:
            try:
                renderer = PersonalityRenderer(
                    characters_api_url=ai_cfg.characters_api_url,
                    character_id=ai_cfg.character_id,
                    cathy_api_url=ai_cfg.cathy_api_url,
                    fallback_system_prompt=ai_cfg.fallback_system_prompt,
                    cathy_api_key=ai_cfg.cathy_api_key,
                    timeout_seconds=ai_cfg.timeout_seconds,
                    connect_timeout_seconds=ai_cfg.connect_timeout_seconds,
                    max_tokens=ai_cfg.max_tokens,
                    temperature=ai_cfg.temperature,
                    top_p=ai_cfg.top_p,
                    min_seconds_between_calls=ai_cfg.min_seconds_between_calls,
                    cathy_api_mode=ai_cfg.cathy_api_mode,
                    cathy_api_model=ai_cfg.cathy_api_model,
                )
                rendered = await renderer.render(summary_payload)
                if rendered:
                    message = prefix + rendered
            except Exception:
                pass
        
        await send_text(session, notifications_room, message)
