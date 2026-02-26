import pytest
from catcord_bots.config import FrameworkConfig, Homeserver, BotCreds, Notifications


class TestConfig:
    def test_from_dict_minimal(self):
        d = {
            "homeserver_url": "https://matrix.example.com",
            "bot": {"mxid": "@bot:example.com", "access_token": "token123"}
        }
        cfg = FrameworkConfig.from_dict(d)
        assert cfg.homeserver.url == "https://matrix.example.com"
        assert cfg.bot.mxid == "@bot:example.com"
        assert cfg.bot.access_token == "token123"
        assert cfg.notifications.send_deletion_summary is True
        assert cfg.rooms_allowlist == []

    def test_from_dict_full(self):
        d = {
            "homeserver_url": "https://matrix.example.com",
            "server_name": "example.com",
            "bot": {"mxid": "@bot:example.com", "access_token": "token123"},
            "notifications": {
                "log_room_id": "!room:example.com",
                "send_deletion_summary": False,
                "send_nightly_status": False,
                "send_zero_deletion_summaries": True
            },
            "rooms_allowlist": ["!room1:example.com", "!room2:example.com"]
        }
        cfg = FrameworkConfig.from_dict(d)
        assert cfg.homeserver.server_name == "example.com"
        assert cfg.notifications.log_room_id == "!room:example.com"
        assert cfg.notifications.send_deletion_summary is False
        assert cfg.notifications.send_zero_deletion_summaries is True
        assert len(cfg.rooms_allowlist) == 2
