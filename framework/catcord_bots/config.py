from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


def load_yaml(path: str | Path) -> Dict[str, Any]:
    """Load YAML file and return as dictionary.

    :param path: Path to YAML file
    :type path: str | Path
    :return: Parsed YAML content
    :rtype: Dict[str, Any]
    """
    p = Path(path)
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


@dataclass
class BotCreds:
    """Bot credentials.

    :param mxid: Matrix user ID
    :type mxid: str
    :param access_token: Access token
    :type access_token: str
    """
    mxid: str
    access_token: str


@dataclass
class Homeserver:
    """Homeserver configuration.

    :param url: Homeserver URL
    :type url: str
    :param server_name: Optional server name
    :type server_name: Optional[str]
    """
    url: str
    server_name: Optional[str] = None


@dataclass
class Notifications:
    """Notification configuration.

    :param log_room_id: Optional log room ID
    :type log_room_id: Optional[str]
    :param send_deletion_summary: Whether to send deletion summaries
    :type send_deletion_summary: bool
    :param send_nightly_status: Whether to send nightly status
    :type send_nightly_status: bool
    :param send_zero_deletion_summaries: Whether to send zero deletion summaries
    :type send_zero_deletion_summaries: bool
    """
    log_room_id: Optional[str] = None
    send_deletion_summary: bool = True
    send_nightly_status: bool = True
    send_zero_deletion_summaries: bool = False


@dataclass
class FrameworkConfig:
    """Framework configuration.

    :param homeserver: Homeserver configuration
    :type homeserver: Homeserver
    :param bot: Bot credentials
    :type bot: BotCreds
    :param notifications: Notification configuration
    :type notifications: Notifications
    :param rooms_allowlist: List of allowed room IDs
    :type rooms_allowlist: list[str]
    """
    homeserver: Homeserver
    bot: BotCreds
    notifications: Notifications
    rooms_allowlist: list[str]

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FrameworkConfig":
        """Create FrameworkConfig from dictionary.

        :param d: Configuration dictionary
        :type d: Dict[str, Any]
        :return: Framework configuration
        :rtype: FrameworkConfig
        """
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
