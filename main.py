import argparse
import asyncio
import os
import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
import yaml
from mautrix.client import Client
from mautrix.api import HTTPAPI
from mautrix.types import EventType, RoomID, MessageEvent

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def get_disk_usage() -> float:
    st = os.statvfs("/srv/media")
    return 1.0 - (st.f_bavail / st.f_blocks)

def init_db(db_path: str):
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
    if not mxc.startswith("mxc://"):
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

async def log_upload(conn, event: MessageEvent):
    if not hasattr(event.content, "url") or not event.content.url:
        return
    
    size = getattr(event.content.info, "size", 0) if hasattr(event.content, "info") else 0
    mimetype = getattr(event.content.info, "mimetype", "") if hasattr(event.content, "info") else ""
    
    conn.execute("""
        INSERT OR IGNORE INTO uploads (event_id, room_id, sender, mxc_uri, mimetype, size, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (str(event.event_id), str(event.room_id), str(event.sender), event.content.url, mimetype, size, event.timestamp))
    conn.commit()

async def sync_uploads(client: Client, conn, cfg: dict):
    rooms = await client.get_joined_rooms()
    allowlist = cfg.get("rooms_allowlist", [])
    if allowlist:
        rooms = [r for r in rooms if str(r) in allowlist]
    
    for room_id in rooms:
        try:
            resp = await client.get_messages(room_id, limit=100)
            for event in resp.chunk:
                if event.type == EventType.ROOM_MESSAGE and hasattr(event.content, "url"):
                    await log_upload(conn, event)
        except Exception as e:
            print(f"Sync error in {room_id}: {e}")

async def run_retention(client: Client, conn, cfg: dict, dry_run: bool):
    policy = cfg.get("policy", {})
    img_days = policy.get("retention_days", {}).get("image", 90)
    non_img_days = policy.get("retention_days", {}).get("non_image", 30)
    
    cutoff_img = int((datetime.now() - timedelta(days=img_days)).timestamp() * 1000)
    cutoff_non = int((datetime.now() - timedelta(days=non_img_days)).timestamp() * 1000)
    
    cur = conn.execute("""
        SELECT event_id, room_id, mxc_uri, mimetype, size, timestamp
        FROM uploads
        WHERE (mimetype LIKE 'image/%' AND timestamp < ?)
           OR (mimetype NOT LIKE 'image/%' AND timestamp < ?)
        ORDER BY (mimetype LIKE 'image/%') ASC, timestamp ASC, size DESC
    """, (cutoff_img, cutoff_non))
    
    deleted_count = 0
    freed_bytes = 0
    
    for event_id, room_id, mxc_uri, mimetype, size, ts in cur.fetchall():
        paths = find_media_files("/srv/media", mxc_uri)
        
        if dry_run:
            print(f"[DRY-RUN] Would delete: {event_id} ({size} bytes, {len(paths)} files)")
        else:
            try:
                await client.redact(RoomID(room_id), event_id, reason="retention policy")
                for p in paths:
                    if p.exists():
                        freed_bytes += p.stat().st_size
                        p.unlink()
                conn.execute("DELETE FROM uploads WHERE event_id = ?", (event_id,))
            except Exception as e:
                print(f"Delete error {event_id}: {e}")
                continue
        
        deleted_count += 1
    
    if not dry_run:
        conn.commit()
    
    return deleted_count, freed_bytes

async def run_pressure(client: Client, conn, cfg: dict, dry_run: bool):
    policy = cfg.get("policy", {})
    threshold = policy.get("disk_thresholds", {}).get("pressure", 0.85)
    
    usage = get_disk_usage()
    if usage < threshold:
        return 0, 0
    
    cur = conn.execute("""
        SELECT event_id, room_id, mxc_uri, size
        FROM uploads
        ORDER BY (mimetype LIKE 'image/%') ASC, size DESC
    """)
    
    deleted_count = 0
    freed_bytes = 0
    
    for event_id, room_id, mxc_uri, size in cur.fetchall():
        if get_disk_usage() < threshold:
            break
        
        paths = find_media_files("/srv/media", mxc_uri)
        
        if dry_run:
            print(f"[DRY-RUN] Would delete: {event_id} ({size} bytes, {len(paths)} files)")
        else:
            try:
                await client.redact(RoomID(room_id), event_id, reason="disk pressure")
                for p in paths:
                    if p.exists():
                        freed_bytes += p.stat().st_size
                        p.unlink()
                conn.execute("DELETE FROM uploads WHERE event_id = ?", (event_id,))
            except Exception as e:
                print(f"Delete error {event_id}: {e}")
                continue
        
        deleted_count += 1
    
    if not dry_run:
        conn.commit()
    
    return deleted_count, freed_bytes

async def send_summary(client: Client, cfg: dict, log_room: str, mode: str, deleted: int, freed: int, dry_run: bool):
    notif = cfg.get("notifications", {})
    if deleted == 0 and not notif.get("send_zero_deletion_summaries", False):
        return
    
    prefix = "[DRY-RUN] " if dry_run else ""
    freed_mb = freed / (1024 * 1024)
    msg = f"{prefix}Cleanup: mode={mode}, deleted={deleted}, freed={freed_mb:.1f}MB"
    await client.send_text(RoomID(log_room), msg)

async def async_main(args, cfg):
    api = HTTPAPI(
        base_url=cfg["homeserver_url"],
        token=cfg["bot"]["access_token"],
    )
    client = Client(mxid=cfg["bot"]["mxid"], api=api)
    conn = init_db("/state/uploads.db")
    
    try:
        await client.start()
        await sync_uploads(client, conn, cfg)
        
        if args.mode == "retention":
            deleted, freed = await run_retention(client, conn, cfg, args.dry_run)
        else:
            deleted, freed = await run_pressure(client, conn, cfg, args.dry_run)
        
        log_room = cfg.get("notifications", {}).get("log_room_id")
        if log_room and cfg.get("notifications", {}).get("send_deletion_summary", True):
            await send_summary(client, cfg, log_room, args.mode, deleted, freed, args.dry_run)
        
        print(f"Completed: {deleted} events, {freed/(1024*1024):.1f}MB freed")
    finally:
        conn.close()
        await client.stop()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="/config/config.yaml")
    p.add_argument("--mode", choices=["retention", "pressure"], required=True)
    p.add_argument("--dry-run", action="store_true", help="Simulate without deleting")
    args = p.parse_args()

    cfg = load_config(args.config)
    os.makedirs("/state", exist_ok=True)

    asyncio.run(async_main(args, cfg))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"bot-a fatal: {e}", file=sys.stderr)
        raise
