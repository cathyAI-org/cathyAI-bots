import asyncio
from datetime import datetime
from mautrix.types import (
    EventType,
    MessageEvent,
    Filter,
    EventFilter,
    RoomFilter,
    RoomEventFilter,
)
from catcord_bots.config import load_yaml, FrameworkConfig
from catcord_bots.matrix import create_client, create_client_e2ee, whoami
from catcord_bots.invites import join_all_invites
try:
    from .cleaner import (
        init_db,
        log_upload,
        get_disk_usage_ratio,
        Policy,
        run_pressure,
    )
except ImportError:
    from cleaner import (
        init_db,
        log_upload,
        get_disk_usage_ratio,
        Policy,
        run_pressure,
    )



conn = None


async def on_message(event: MessageEvent, session, cfg, policy):
    """Handle media upload, including decrypted E2EE media when possible."""
    global conn

    event_type = str(getattr(event, "type", ""))
    is_encrypted = event_type == "m.room.encrypted"

    # Try to decrypt encrypted timeline events.
    if is_encrypted and getattr(session, "crypto", None) is not None:
        try:
            decrypted = await session.crypto.decrypt_megolm_event(event)
            print(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"Encrypted event decrypted: type={getattr(decrypted, 'type', None)}",
                flush=True,
            )
            event = decrypted
            event_type = str(getattr(event, "type", ""))
            is_encrypted = False
        except Exception as e:
            used = get_disk_usage_ratio("/srv/media")
            print(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"Encrypted event could not be decrypted ({type(e).__name__}: {e}). "
                f"Checking emergency pressure only. Current disk usage: {used:.1%}",
                flush=True,
            )

            if used >= policy.emergency:
                print(f"Emergency pressure detected: {used:.1%} >= {policy.emergency:.1%}", flush=True)
                await run_pressure(
                    session=session,
                    conn=conn,
                    media_root="/srv/media",
                    policy=policy,
                    notifications_room=cfg.notifications.log_room_id,
                    send_zero=False,
                    dry_run=False,
                    print_effective_config=False,
                )
            return

    msgtype = getattr(getattr(event, "content", None), "msgtype", None)

    # Still encrypted / unknown: do not log fake uploads.
    if is_encrypted:
        used = get_disk_usage_ratio("/srv/media")
        print(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"Encrypted event seen. Checking emergency pressure only. "
            f"Current disk usage: {used:.1%}",
            flush=True,
        )

        if used >= policy.emergency:
            print(f"Emergency pressure detected: {used:.1%} >= {policy.emergency:.1%}", flush=True)
            await run_pressure(
                session=session,
                conn=conn,
                media_root="/srv/media",
                policy=policy,
                notifications_room=cfg.notifications.log_room_id,
                send_zero=False,
                dry_run=False,
                print_effective_config=False,
            )
        return

    # Unencrypted or successfully decrypted: only actual media messages are uploads.
    if str(msgtype) not in ("m.image", "m.video", "m.file", "m.audio"):
        return

    used = get_disk_usage_ratio("/srv/media")
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"Media event seen, logging upload. msgtype={msgtype}. "
        f"Current disk usage: {used:.1%}",
        flush=True,
    )

    await log_upload(conn, event)

    if used >= policy.emergency:
        print(f"Emergency pressure detected: {used:.1%} >= {policy.emergency:.1%}", flush=True)
        await run_pressure(
            session=session,
            conn=conn,
            media_root="/srv/media",
            policy=policy,
            notifications_room=cfg.notifications.log_room_id,
            send_zero=False,
            dry_run=False,
            print_effective_config=False,
        )


async def main_async(config_path: str):
    global conn
    raw = load_yaml(config_path)
    cfg = FrameworkConfig.from_dict(raw)
    e2ee_cfg = raw.get("e2ee") or {}
    if e2ee_cfg.get("enabled"):
        session = await create_client_e2ee(
            cfg.bot.mxid,
            cfg.homeserver.url,
            cfg.bot.access_token,
            e2ee_cfg,
        )
        print("E2EE enabled for cleaner client", flush=True)
    else:
        session = create_client(cfg.bot.mxid, cfg.homeserver.url, cfg.bot.access_token)

    try:
        me = await whoami(session)
        print(f"Event-driven cleaner: {me}")

        allow = cfg.rooms_allowlist[:] if cfg.rooms_allowlist else (
            [cfg.notifications.log_room_id] if cfg.notifications.log_room_id else []
        )
        joined = await join_all_invites(session, allowlist=[r for r in allow if r])
        if joined:
            print(f"Joined: {joined}")

        conn = init_db("/state/uploads.db")

        pol = raw.get("policy", {})
        rd = pol.get("retention_days", {})
        thr = pol.get("disk_thresholds", {})
        policy = Policy(
            image_days=int(rd.get("image", 90)),
            non_image_days=int(rd.get("non_image", 30)),
            pressure=float(thr.get("pressure", 0.85)),
            emergency=float(thr.get("emergency", 0.92)),
        )

        session.client.add_event_handler(
            EventType.ROOM_MESSAGE,
            lambda evt: on_message(evt, session, cfg, policy),
            wait_sync=True,
        )
        session.client.add_event_handler(
            EventType.ROOM_ENCRYPTED,
            lambda evt: on_message(evt, session, cfg, policy),
            wait_sync=True,
        )

        sync_filter = Filter(
            account_data=EventFilter(not_types=["*"]),
            room=RoomFilter(
                account_data=RoomEventFilter(not_types=["*"]),
                timeline=RoomEventFilter(types=[EventType.ROOM_MESSAGE, EventType.ROOM_ENCRYPTED]),
            ),
        )

        filter_id = await session.client.create_filter(sync_filter)

        print("Listening for media uploads...")
        since = None
        while True:
            data = await session.client.sync(
                since=since,
                timeout=30000,
                filter_id=filter_id,
                full_state=False,
            )

            data.pop("account_data", None)
            rooms = data.get("rooms") or {}
            for section in ("join", "invite", "leave"):
                for room in (rooms.get(section) or {}).values():
                    room.pop("account_data", None)

            session.client.handle_sync(data)
            since = data.get("next_batch")
    finally:
        if conn:
            conn.close()
        await session.close()


def main():
    asyncio.run(main_async("/config/config.yaml"))


if __name__ == "__main__":
    main()
