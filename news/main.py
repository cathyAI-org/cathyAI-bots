"""News bot main entry point."""
import argparse
import asyncio
import os
from catcord_bots.config import load_yaml, FrameworkConfig
from catcord_bots.matrix import create_client, whoami
from catcord_bots.invites import join_all_invites
from news import run_digest, PersonalityConfig, FetchConfig, ServicesConfig


async def main_async(args):
    """Main async entry point.

    :param args: Command line arguments
    :type args: argparse.Namespace
    :return: None
    :rtype: None
    """
    raw = load_yaml(args.config)
    cfg = FrameworkConfig.from_dict(raw)
    session = create_client(cfg.bot.mxid, cfg.homeserver.url, cfg.bot.access_token)

    try:
        me = await whoami(session)
        print("Authenticated as:", me)

        allow = cfg.rooms_allowlist[:] if cfg.rooms_allowlist else (
            [cfg.notifications.log_room_id] if cfg.notifications.log_room_id else []
        )
        joined = await join_all_invites(session, allowlist=[r for r in allow if r])
        if joined:
            print("Auto-joined invites:", joined)

        fetch_raw = raw.get("fetch") or {}
        fetch_cfg = FetchConfig(
            lookback_hours=int(fetch_raw.get("lookback_hours", 24)),
            max_items=int(fetch_raw.get("max_items", 10)),
            timeout_s=float(fetch_raw.get("timeout_s", 10.0)),
            user_agent=str(fetch_raw.get("user_agent", "catcord-newsbot/1.0")),
            feeds=fetch_raw.get("feeds", {}),
        )

        services_raw = raw.get("services") or {}
        services_cfg = ServicesConfig(
            online_url=services_raw.get("online", {}).get("url", "http://online:8088"),
            memory_url=services_raw.get("memory", {}).get("url", "http://memory:8090"),
        )

        ai_raw = raw.get("add_personality") or {}
        ai_cfg = PersonalityConfig(
            enabled=bool(ai_raw.get("enabled", False)),
            prompt_composer_url=str(ai_raw.get("prompt_composer_url", "http://192.168.1.57:8110")),
            character_id=str(ai_raw.get("character_id", "delilah")),
            cathy_api_url=str(ai_raw.get("cathy_api_url", "http://192.168.1.57:8100")),
            cathy_api_key=ai_raw.get("cathy_api_key"),
            timeout_seconds=float(ai_raw.get("timeout_seconds", 60)),
            connect_timeout_seconds=float(ai_raw.get("connect_timeout_seconds", 3)),
            max_tokens=int(ai_raw.get("max_tokens", 180)),
            temperature=float(ai_raw.get("temperature", 0.0)),
            top_p=float(ai_raw.get("top_p", 0.9)),
            min_seconds_between_calls=int(ai_raw.get("min_seconds_between_calls", 0)),
            fallback_system_prompt=str(ai_raw.get(
                "fallback_system_prompt",
                "You are Delilah, a news-digest host. Output exactly one line. "
                "No links, titles, sources, dates, numbers. Keep it warm and brief."
            )),
            cathy_api_mode=str(ai_raw.get("cathy_api_mode", "ollama")),
            cathy_api_model=str(ai_raw.get("cathy_api_model", "gemma2:2b")),
        )

        if args.mode == "digest":
            await run_digest(
                session=session,
                fetch_cfg=fetch_cfg,
                services_cfg=services_cfg,
                notifications_room=cfg.notifications.log_room_id,
                ai_cfg=ai_cfg,
                force_notify=args.force_notify,
                dry_run=args.dry_run,
            )
    finally:
        await session.close()


def main():
    """Main entry point.

    :return: None
    :rtype: None
    """
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="/config/config.yaml")
    p.add_argument("--mode", choices=["digest"], default="digest")
    p.add_argument("--force-notify", action="store_true", help="Force send even if deduplicated")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    os.makedirs("/state", exist_ok=True)
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
