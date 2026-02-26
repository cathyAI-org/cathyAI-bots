import argparse
import asyncio
import os
from catcord_bots.config import load_yaml, FrameworkConfig
from catcord_bots.matrix import create_client, whoami
from catcord_bots.invites import join_all_invites
from cleaner import init_db, sync_uploads, Policy, run_retention, run_pressure


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
            if args.mode == "retention":
                await run_retention(
                    session=session,
                    conn=conn,
                    media_root="/srv/media",
                    policy=policy,
                    notifications_room=cfg.notifications.log_room_id,
                    send_zero=cfg.notifications.send_zero_deletion_summaries,
                    dry_run=args.dry_run,
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
