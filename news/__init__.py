"""News bot core logic."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import httpx
from catcord_bots.matrix import MatrixSession, send_text
from catcord_bots.personality import PersonalityRenderer
from news.state import payload_fingerprint, should_send
from news.format import format_digest


@dataclass
class FetchConfig:
    """Feed fetch configuration.
    
    :param lookback_hours: Hours to look back for items
    :type lookback_hours: int
    :param max_items: Maximum items to fetch
    :type max_items: int
    :param timeout_s: Request timeout in seconds
    :type timeout_s: float
    :param user_agent: User agent string
    :type user_agent: str
    :param feeds: Feed URLs by section
    :type feeds: Dict[str, list]
    """
    lookback_hours: int = 24
    max_items: int = 10
    timeout_s: float = 10.0
    user_agent: str = "catcord-newsbot/1.0"
    feeds: Dict[str, list] = None
    
    def __post_init__(self):
        if self.feeds is None:
            self.feeds = {}


@dataclass
class ServicesConfig:
    """Services configuration.
    
    :param online_url: Online service URL
    :type online_url: str
    :param memory_url: Memory service URL
    :type memory_url: str
    """
    online_url: str = "http://online:8088"
    memory_url: str = "http://memory:8090"


@dataclass
class PersonalityConfig:
    """AI personality configuration.
    
    :param enabled: Enable AI personality
    :type enabled: bool
    :param prompt_composer_url: Prompt composer URL
    :type prompt_composer_url: str
    :param character_id: Character ID
    :type character_id: str
    :param cathy_api_url: LLM API URL
    :type cathy_api_url: str
    :param cathy_api_key: Optional API key
    :type cathy_api_key: Optional[str]
    :param timeout_seconds: Request timeout
    :type timeout_seconds: float
    :param connect_timeout_seconds: Connection timeout
    :type connect_timeout_seconds: float
    :param max_tokens: Max tokens for LLM
    :type max_tokens: int
    :param temperature: LLM temperature
    :type temperature: float
    :param top_p: LLM top_p
    :type top_p: float
    :param min_seconds_between_calls: Rate limit
    :type min_seconds_between_calls: int
    :param fallback_system_prompt: Fallback prompt
    :type fallback_system_prompt: str
    :param cathy_api_mode: API mode (ollama/openai)
    :type cathy_api_mode: str
    :param cathy_api_model: Model name
    :type cathy_api_model: str
    """
    enabled: bool = False
    prompt_composer_url: str = "http://192.168.1.57:8110"
    character_id: str = "delilah"
    cathy_api_url: str = "http://192.168.1.57:8100"
    cathy_api_key: Optional[str] = None
    timeout_seconds: float = 60
    connect_timeout_seconds: float = 3
    max_tokens: int = 180
    temperature: float = 0.0
    top_p: float = 0.9
    min_seconds_between_calls: int = 0
    fallback_system_prompt: str = "You are Delilah, a news-digest host."
    cathy_api_mode: str = "ollama"
    cathy_api_model: str = "gemma2:2b"


async def run_digest(
    session: MatrixSession,
    fetch_cfg: FetchConfig,
    services_cfg: ServicesConfig,
    notifications_room: Optional[str],
    ai_cfg: Optional[PersonalityConfig] = None,
    force_notify: bool = False,
    dry_run: bool = False,
) -> None:
    """Run daily news digest.
    
    :param session: Matrix session
    :type session: MatrixSession
    :param fetch_cfg: Fetch configuration
    :type fetch_cfg: FetchConfig
    :param services_cfg: Services configuration
    :type services_cfg: ServicesConfig
    :param notifications_room: Room to send notifications
    :type notifications_room: Optional[str]
    :param ai_cfg: AI personality configuration
    :type ai_cfg: Optional[PersonalityConfig]
    :param force_notify: Force send even if deduplicated
    :type force_notify: bool
    :param dry_run: Don't actually send
    :type dry_run: bool
    :return: None
    :rtype: None
    """
    start_time = datetime.now(timezone.utc)
    
    all_items = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for section_name, feed_urls in fetch_cfg.feeds.items():
            req_body = {
                "feeds": feed_urls,
                "lookback_hours": fetch_cfg.lookback_hours,
                "max_items": fetch_cfg.max_items,
                "timeout_s": fetch_cfg.timeout_s,
                "user_agent": fetch_cfg.user_agent,
                "caller": {
                    "bot": "news",
                    "room_id": notifications_room,
                },
            }
            
            try:
                resp = await client.post(
                    f"{services_cfg.online_url}/v1/rss/fetch",
                    json=req_body,
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])
                
                if items:
                    all_items.append({"name": section_name, "items": items})
            except Exception as e:
                print(f"Error fetching {section_name}: {e!r}")
                continue
    
    payload = {
        "mode": "daily_digest",
        "ts": start_time.isoformat(),
        "lookback_hours": fetch_cfg.lookback_hours,
        "sections": all_items,
    }
    
    if not notifications_room:
        print("No notifications_room configured")
        return
    
    state_path = "/state/digest_last.fp"
    fp = payload_fingerprint(payload)
    
    if not should_send(state_path, fp, force_notify):
        print("Digest unchanged, skipping send (use --force-notify to override)")
        return
    
    ai_prefix = None
    if ai_cfg and ai_cfg.enabled:
        try:
            renderer = PersonalityRenderer(
                prompt_composer_url=ai_cfg.prompt_composer_url,
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
            
            ai_prefix = await renderer.render(payload, task_id="news_digest_prefix")
            if ai_prefix:
                ai_prefix = ai_prefix.strip().strip('"').strip("'").strip()
                print("AI render: used")
            else:
                print("AI render: empty -> deterministic only")
        except Exception as e:
            print(f"AI render failed -> deterministic only: {e}")
    
    message = format_digest(payload, ai_prefix)
    prefix = "[DRY-RUN] " if dry_run else ""
    
    if dry_run:
        print(f"{prefix}Would send:")
        print(message)
    else:
        try:
            await send_text(session, notifications_room, message)
            print(f"Sent digest to {notifications_room}")
        except Exception as e:
            print(f"Failed to send message: {e}")
