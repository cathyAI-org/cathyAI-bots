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
from catcord_bots.matrix import create_client, whoami
from catcord_bots.invites import join_all_invites
from cleaner import (
    init_db, log_upload, get_disk_usage_ratio, Policy,
    run_pressure, PersonalityConfig
)


conn = None


async def on_message(event: MessageEvent, session, cfg, policy, ai_cfg):
    """Handle media upload events."""
    global conn

    if str(event.content.msgtype) not in ("m.image", "m.video", "m.file", "m.audio"):
        return

    used = get_disk_usage_ratio("/srv/media")
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"Media event seen, logging upload. Current disk usage: {used:.1%}"
    )
    await log_upload(conn, event)

    if used >= policy.pressure:
        print(f"Pressure detected: {used:.1%} >= {policy.pressure:.1%}")
        await run_pressure(
            session=session,
            conn=conn,
            media_root="/srv/media",
            policy=policy,
            notifications_room=cfg.notifications.log_room_id,
            send_zero=False,
            dry_run=False,
            ai_cfg=ai_cfg,
            print_effective_config=False,
        )


async def main_async(config_path: str):
    global conn
    raw = load_yaml(config_path)
    cfg = FrameworkConfig.from_dict(raw)
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
        
        ai_raw = raw.get("add_personality", {})
        ai_cfg = PersonalityConfig(
            enabled=bool(ai_raw.get("enabled", False)),
            prompt_composer_url=str(ai_raw.get("prompt_composer_url", "http://192.168.1.59:8110")),
            character_id=str(ai_raw.get("character_id", "irina")),
            cathy_api_url=str(ai_raw.get("cathy_api_url", "http://192.168.1.59:8100")),
            cathy_api_key=ai_raw.get("cathy_api_key"),
            timeout_seconds=float(ai_raw.get("timeout_seconds", 6)),
            connect_timeout_seconds=float(ai_raw.get("connect_timeout_seconds", 2)),
            max_tokens=int(ai_raw.get("max_tokens", 180)),
            temperature=float(ai_raw.get("temperature", 0.2)),
            top_p=float(ai_raw.get("top_p", 0.9)),
            min_seconds_between_calls=int(ai_raw.get("min_seconds_between_calls", 30)),
            fallback_system_prompt=str(ai_raw.get("fallback_system_prompt", "You are a maintenance bot.")),
            cathy_api_mode=str(ai_raw.get("cathy_api_mode", "ollama")),
            cathy_api_model=str(ai_raw.get("cathy_api_model", "gemma2:2b")),
        )
        
        session.client.add_event_handler(
            EventType.ROOM_MESSAGE,
            lambda evt: on_message(evt, session, cfg, policy, ai_cfg),
            wait_sync=True,
        )

        sync_filter = Filter(
            account_data=EventFilter(not_types=["*"]),
            room=RoomFilter(
                account_data=RoomEventFilter(not_types=["*"]),
                timeline=RoomEventFilter(types=[EventType.ROOM_MESSAGE]),
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
