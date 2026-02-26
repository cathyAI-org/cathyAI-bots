from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


def load_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


@dataclass
class BotCreds:
    mxid: str
    access_token: str


@dataclass
class Homeserver:
    url: str
    server_name: Optional[str] = None


@dataclass
class Notifications:
    log_room_id: Optional[str] = None
    send_deletion_summary: bool = True
    send_nightly_status: bool = True
    send_zero_deletion_summaries: bool = False


@dataclass
class FrameworkConfig:
    homeserver: Homeserver
    bot: BotCreds
    notifications: Notifications
    rooms_allowlist: list[str]

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FrameworkConfig":
        hs = Homeserver(url=d["homeserver_url"], server_name=d.get("server_name"))
        bot = BotCreds(mxid=d["bot"]["mxid"], access_token=d["bot"]["access_token"])
        n = d.get("notifications") or {}
        notif = Notifications(
            log_room_id=n.get("log_room_id"),
            send_deletion_summary=bool(n.get("send_deletion_summary", True)),
            send_nightly_status=bool(n.get("send_nightly_status", True)),
            send_zero_deletion_summaries=bool(n.get("send_zero_deletion_summaries", False)),
        )
        return FrameworkConfig(
            homeserver=hs,
            bot=bot,
            notifications=notif,
            rooms_allowlist=list(d.get("rooms_allowlist") or []),
        )
