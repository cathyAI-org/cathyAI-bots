import argparse
import asyncio
import os
from catcord_bots.config import load_yaml, FrameworkConfig
from catcord_bots.matrix import create_client, whoami
from catcord_bots.invites import join_all_invites
from cleaner import init_db, sync_uploads, Policy, run_retention, run_pressure, PersonalityConfig


async def main_async(args):
    raw = load_yaml(args.config)
    cfg = FrameworkConfig.from_dict(raw)
    session = create_client(cfg.bot.mxid, cfg.homeserver.url, cfg.bot.access_token)
    try:
        me = await whoami(session)
        print("Authenticated as:", me)
        allow = cfg.rooms_allowlist[:] if cfg.rooms_allowlist else ([cfg.notifications.log_room_id] if cfg.notifications.log_room_id else [])
        joined = await join_all_invites(session, allowlist=[r for r in allow if r])
        if joined:
            print("Auto-joined invites:", joined)
        conn = init_db("/state/uploads.db")
        try:
            await sync_uploads(session, conn, cfg.rooms_allowlist)
            pol = raw.get("policy") or {}
            rd = (pol.get("retention_days") or {})
            thr = (pol.get("disk_thresholds") or {})
            policy = Policy(
                image_days=int(rd.get("image", 90)),
                non_image_days=int(rd.get("non_image", 30)),
                pressure=float(thr.get("pressure", 0.85)),
                emergency=float(thr.get("emergency", 0.92)),
            )
            
            ai_raw = raw.get("add_personality") or {}
            ai_cfg = PersonalityConfig(
                enabled=bool(ai_raw.get("enabled", False)),
                characters_api_url=str(ai_raw.get("characters_api_url", "http://192.168.1.59:8091")),
                character_id=str(ai_raw.get("character_id", "irina")),
                cathy_api_url=str(ai_raw.get("cathy_api_url", "http://192.168.1.59:8100")),
                cathy_api_key=ai_raw.get("cathy_api_key"),
                timeout_seconds=float(ai_raw.get("timeout_seconds", 6)),
                connect_timeout_seconds=float(ai_raw.get("connect_timeout_seconds", 2)),
                max_tokens=int(ai_raw.get("max_tokens", 180)),
                temperature=float(ai_raw.get("temperature", 0.2)),
                top_p=float(ai_raw.get("top_p", 0.9)),
                min_seconds_between_calls=int(ai_raw.get("min_seconds_between_calls", 30)),
                fallback_system_prompt=str(ai_raw.get("fallback_system_prompt", "You are a maintenance bot. Write short, calm, factual ops updates.")),
                cathy_api_mode=str(ai_raw.get("cathy_api_mode", "openai")),
                cathy_api_model=str(ai_raw.get("cathy_api_model", "cathy")),
            )
            if args.mode == "retention":
                await run_retention(
                    session=session,
                    conn=conn,
                    media_root="/srv/media",
                    policy=policy,
                    notifications_room=cfg.notifications.log_room_id,
                    send_zero=cfg.notifications.send_zero_deletion_summaries,
                    dry_run=args.dry_run,
                    ai_cfg=ai_cfg,
                )
            else:
                await run_pressure(
                    session=session,
                    conn=conn,
                    media_root="/srv/media",
                    policy=policy,
                    notifications_room=cfg.notifications.log_room_id,
                    send_zero=cfg.notifications.send_zero_deletion_summaries,
                    dry_run=args.dry_run,
                    ai_cfg=ai_cfg,
                )
        finally:
            conn.close()
    finally:
        await session.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="/config/config.yaml")
    p.add_argument("--mode", choices=["retention", "pressure"], required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
