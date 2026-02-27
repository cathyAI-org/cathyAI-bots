from __future__ import annotations
import asyncio
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
        characters_api_key: Optional[str] = None,
        characters_api_key_header: str = "X-API-Key",
        timeout_seconds: float = 15,
        connect_timeout_seconds: float = 2,
        max_tokens: int = 180,
        temperature: float = 0.2,
        top_p: float = 0.9,
        min_seconds_between_calls: int = 30,
        cathy_api_mode: str = "ollama",
        cathy_api_model: str = "phi3.5:latest",
    ):
        self.characters_api_url = characters_api_url
        self.character_id = character_id
        self.cathy_api_url = cathy_api_url
        self.fallback_system_prompt = fallback_system_prompt
        self.cathy_api_key = cathy_api_key
        self.characters_api_key = characters_api_key
        self.characters_api_key_header = characters_api_key_header
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
        if self.characters_api_key:
            headers[self.characters_api_key_header] = self.characters_api_key
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

    def _validate_output(self, summary_payload: Dict[str, Any], text: str) -> bool:
        """Validate AI output contains required facts from JSON."""
        tlow = text.lower()
        
        disk = summary_payload.get("disk") or {}
        actions = summary_payload.get("actions") or {}
        
        percent_before = disk.get("percent_before")
        pressure_threshold = disk.get("pressure_threshold")
        deleted_count = actions.get("deleted_count")
        freed_gb = actions.get("freed_gb")
        
        # Must include key numbers (allow rounding/formatting)
        if percent_before is not None:
            pb_str = str(percent_before).rstrip("0").rstrip(".")
            if pb_str not in text and f"{percent_before:.1f}" not in text:
                return False
        
        if pressure_threshold is not None:
            pt_str = str(pressure_threshold).rstrip("0").rstrip(".")
            pt_pct = str(int(pressure_threshold)) if pressure_threshold == int(pressure_threshold) else str(pressure_threshold)
            if pt_str not in text and pt_pct not in text:
                return False
        
        # Must correctly indicate no deletions when count is 0
        if deleted_count == 0:
            no_deletion_phrases = ["no action", "no deletions", "0 deletions", "deleted 0", "deleted_count=0", "deleted_count: 0"]
            if not any(p in tlow for p in no_deletion_phrases):
                return False
        
        # Must include freed_gb when deletions occurred
        if deleted_count and deleted_count > 0:
            if freed_gb is not None:
                fg_str = str(freed_gb).rstrip("0").rstrip(".")
                if fg_str not in text and f"{freed_gb:.1f}" not in text and f"{freed_gb:.2f}" not in text:
                    return False
        
        return True

    def _build_user_prompt(self, summary_payload: Dict[str, Any]) -> str:
        payload_str = json.dumps(summary_payload, ensure_ascii=False, sort_keys=True)
        return (
            "You will be given a JSON payload with facts.\n"
            "Write a short ops update in Irina's voice.\n\n"
            "STRICT RULES:\n"
            "- Only use facts present in the JSON.\n"
            "- Do NOT invent deletions, rooms, users, causes, or numbers.\n"
            "- If actions.deleted_count is 0, you MUST say there were no deletions and you MUST NOT imply anything was deleted.\n"
            "- If actions.deleted_count > 0, you MUST include deleted_count and freed_gb.\n"
            "- If disk.percent_before < disk.pressure_threshold, say below threshold.\n"
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
                for attempt in range(2):
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
                        if not text:
                            done = data.get("done_reason") if isinstance(data, dict) else None
                            raw = ""
                            try:
                                raw = r.text.replace("\n", " ")[:200]
                            except Exception:
                                pass
                            print(f"PersonalityRenderer: empty ollama content (attempt={attempt}) done={done} raw='{raw}'")
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
                    
                    if not text and attempt == 0:
                        await asyncio.sleep(0.3)
                        continue
                    
                    if text:
                        if not self._validate_output(summary_payload, text):
                            print(f"PersonalityRenderer: output failed validation: {text[:140]!r}")
                            return None
                        return text
                    return None

        except Exception as e:
            print(f"PersonalityRenderer exception: {e!r}")
            return None
