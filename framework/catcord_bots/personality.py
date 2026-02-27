from __future__ import annotations
import json
import time
from typing import Any, Dict, Optional

import httpx


class PersonalityRenderer:
    def __init__(
        self,
        characters_api_url: str,
        character_id: str,
        cathy_api_url: str,
        fallback_system_prompt: str,
        cathy_api_key: Optional[str] = None,
        timeout_seconds: float = 6,
        connect_timeout_seconds: float = 2,
        max_tokens: int = 180,
        temperature: float = 0.2,
        top_p: float = 0.9,
        min_seconds_between_calls: int = 30,
        cathy_api_mode: str = "ollama",
        cathy_api_model: str = "gemma2:2b",
    ):
        self.characters_api_url = characters_api_url
        self.character_id = character_id
        self.cathy_api_url = cathy_api_url
        self.fallback_system_prompt = fallback_system_prompt
        self.cathy_api_key = cathy_api_key
        self.timeout_seconds = timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.min_seconds_between_calls = min_seconds_between_calls
        self.cathy_api_mode = cathy_api_mode
        self.cathy_api_model = cathy_api_model
        self._last_call_ts: float = 0.0
        self._cached_prompt: Optional[str] = None
        self._cached_etag: Optional[str] = None

    def _rate_limited(self) -> bool:
        now = time.time()
        if (now - self._last_call_ts) < self.min_seconds_between_calls:
            return True
        self._last_call_ts = now
        return False

    async def _fetch_system_prompt(self) -> str:
        base = self.characters_api_url.rstrip("/")
        url = f"{base}/characters/{self.character_id}?view=private"

        headers = {}
        if self._cached_etag:
            headers["If-None-Match"] = self._cached_etag

        timeout = httpx.Timeout(
            timeout=self.timeout_seconds,
            connect=self.connect_timeout_seconds,
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 304 and self._cached_prompt:
                return self._cached_prompt
            r.raise_for_status()

            data = r.json()
            prompt = (
                data.get("system_prompt")
                or data.get("prompt")
                or data.get("background")
                or ""
            ).strip()

            if not prompt:
                return self.fallback_system_prompt.strip()

            self._cached_prompt = prompt
            self._cached_etag = r.headers.get("ETag")
            return prompt

    def _build_user_prompt(self, summary_payload: Dict[str, Any]) -> str:
        payload_str = json.dumps(summary_payload, ensure_ascii=False, sort_keys=True)
        return (
            "You will be given a JSON payload with facts.\n"
            "Write a short ops update.\n\n"
            "STRICT RULES:\n"
            "- Only use facts present in the JSON.\n"
            "- Do NOT invent data or add new metrics.\n"
            "- Keep it under ~700 characters.\n"
            "- Include key numeric facts exactly as provided.\n"
            "- Plain text only.\n\n"
            f"JSON:\n{payload_str}\n"
        )

    async def render(self, summary_payload: Dict[str, Any]) -> Optional[str]:
        if self._rate_limited():
            return None

        try:
            system_prompt = await self._fetch_system_prompt()
            user_prompt = self._build_user_prompt(summary_payload)

            timeout = httpx.Timeout(
                timeout=self.timeout_seconds,
                connect=self.connect_timeout_seconds,
            )

            headers = {"Content-Type": "application/json"}
            if self.cathy_api_key:
                headers["Authorization"] = f"Bearer {self.cathy_api_key}"

            async with httpx.AsyncClient(timeout=timeout) as client:
                if self.cathy_api_mode.lower() == "ollama":
                    body = {
                        "model": self.cathy_api_model,
                        "stream": False,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "options": {
                            "temperature": self.temperature,
                        },
                    }
                    r = await client.post(
                        f"{self.cathy_api_url.rstrip('/')}/api/chat",
                        headers=headers,
                        json=body,
                    )
                    r.raise_for_status()
                    data = r.json()
                    text = (data.get("message") or {}).get("content", "").strip()
                else:
                    body = {
                        "model": self.cathy_api_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": self.temperature,
                        "top_p": self.top_p,
                        "max_tokens": self.max_tokens,
                        "stream": False,
                    }
                    r = await client.post(
                        f"{self.cathy_api_url.rstrip('/')}/v1/chat/completions",
                        headers=headers,
                        json=body,
                    )
                    r.raise_for_status()
                    data = r.json()
                    text = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        .strip()
                    )
                if text:
                    return text
                return None

        except Exception:
            return None
