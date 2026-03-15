from __future__ import annotations
import hashlib
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

_FALLBACK_BANK: Dict[str, List[str]] = {
    "healthy_no_action": [
        "Logs clear, Master.",
        "All clear, Master.",
        "Storage looks healthy, Master.",
        "No action needed, Master.",
        "Everything looks orderly, Master.",
    ],
    "retention_nothing_to_do": [
        "Nothing expired, Master.",
        "No stale media found, Master.",
        "Retention check complete, Master.",
        "All media within policy, Master.",
    ],
    "tight_no_action": [
        "Storage getting tight, Master.",
        "Usage is climbing, Master.",
        "Capacity is tightening, Master.",
    ],
    "cleanup_done": [
        "Cleanup completed, Master.",
        "Maintenance complete, Master.",
        "Expired media handled, Master.",
        "Cleanup executed, Master.",
    ],
}

_STATUS_PROMPT_HINTS: Dict[str, str] = {
    "healthy_no_action": (
        "Status: healthy_no_action — storage is healthy, nothing was deleted.\n"
        "Do NOT imply cleanup happened.\n"
        "Good: 'All clear, Master.' / 'Storage looks healthy, Master.'"
    ),
    "retention_nothing_to_do": (
        "Status: retention_nothing_to_do — retention check ran, "
        "no files were old enough to delete.\n"
        "Do NOT imply files were removed.\n"
        "Good: 'Nothing expired, Master.' / "
        "'No stale media found, Master.'"
    ),
    "tight_no_action": (
        "Status: tight_no_action — disk usage is high but no "
        "cleanup was triggered yet.\n"
        "Do NOT imply cleanup happened.\n"
        "Good: 'Storage getting tight, Master.' / "
        "'Capacity is tightening, Master.'"
    ),
    "cleanup_done": (
        "Status: cleanup_done — files were actually deleted.\n"
        "You MAY mention cleanup or removal.\n"
        "Good: 'Cleanup completed, Master.' / "
        "'Expired media removed, Master.'"
    ),
}


class PersonalityRenderer:
    """Renders AI-generated status prefixes using prompt-composer and LLM.

    :param prompt_composer_url: URL of prompt-composer service
    :type prompt_composer_url: str
    :param character_id: Character ID for personality
    :type character_id: str
    :param cathy_api_url: URL of LLM API
    :type cathy_api_url: str
    :param fallback_system_prompt: Fallback system prompt if composer fails
    :type fallback_system_prompt: str
    :param cathy_api_key: Optional API key for LLM
    :type cathy_api_key: Optional[str]
    :param timeout_seconds: Request timeout in seconds
    :type timeout_seconds: float
    :param connect_timeout_seconds: Connection timeout in seconds
    :type connect_timeout_seconds: float
    :param max_tokens: Maximum tokens for LLM response
    :type max_tokens: int
    :param temperature: LLM temperature parameter
    :type temperature: float
    :param top_p: LLM top_p parameter
    :type top_p: float
    :param min_seconds_between_calls: Minimum seconds between API calls
    :type min_seconds_between_calls: int
    :param cathy_api_mode: API mode (ollama or openai)
    :type cathy_api_mode: str
    :param cathy_api_model: Model name
    :type cathy_api_model: str
    """

    def __init__(
        self,
        prompt_composer_url: str,
        character_id: str,
        cathy_api_url: str,
        fallback_system_prompt: str,
        cathy_api_key: Optional[str] = None,
        timeout_seconds: float = 60,
        connect_timeout_seconds: float = 3,
        max_tokens: int = 180,
        temperature: float = 0.2,
        top_p: float = 0.9,
        min_seconds_between_calls: int = 0,
        cathy_api_mode: str = "ollama",
        cathy_api_model: str = "gemma2:2b",
    ) -> None:
        self.prompt_composer_url = prompt_composer_url
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


    def _rate_limited(self) -> bool:
        """Check if rate limit prevents API call.

        :return: True if rate limited
        :rtype: bool
        """
        now = time.time()
        if (now - self._last_call_ts) < self.min_seconds_between_calls:
            return True
        self._last_call_ts = now
        return False

    @staticmethod
    def _derive_status_label(
        summary_payload: Dict[str, Any],
    ) -> str:
        """Derive a status label from the summary payload.

        :param summary_payload: Summary data
        :type summary_payload: Dict[str, Any]
        :return: One of the keys in ``_FALLBACK_BANK``
        :rtype: str
        """
        deleted = (
            summary_payload.get("actions", {})
            .get("deleted_count", 0)
        )
        if deleted > 0:
            return "cleanup_done"

        storage = summary_payload.get("storage_status", "")
        if storage in ("tight", "warning", "pressure", "critical"):
            return "tight_no_action"

        mode = summary_payload.get("mode", "")
        candidates = summary_payload.get("candidates_count", -1)
        if mode == "retention" and candidates == 0:
            return "retention_nothing_to_do"

        return "healthy_no_action"

    def _infer_task(self, summary_payload: Dict[str, Any]) -> str:
        """Infer task from payload mode (for backward compatibility).

        :param summary_payload: Summary data
        :type summary_payload: Dict[str, Any]
        :return: Task identifier
        :rtype: str
        """
        mode = summary_payload.get("mode", "unknown")
        if mode == "pressure":
            return "pressure_status"
        elif mode == "retention":
            return "retention_report"
        elif mode == "daily_digest":
            return "news_digest_prefix"
        return "retention_report"

    async def _compose_prompt(
        self, client: httpx.AsyncClient, summary_payload: Dict[str, Any], task: str
    ) -> Optional[Dict[str, Any]]:
        """Call prompt-composer to build system prompt and messages.

        :param client: HTTP client
        :type client: httpx.AsyncClient
        :param summary_payload: Summary data for prompt composition
        :type summary_payload: Dict[str, Any]
        :param task: Task identifier for prompt-composer
        :type task: str
        :return: Prompt bundle or None on failure
        :rtype: Optional[Dict[str, Any]]
        """
        body = {
            "task": task,
            "platform": "matrix",
            "character_id": self.character_id,
            "task_inputs": summary_payload,
        }

        url = f"{self.prompt_composer_url.rstrip('/')}/v1/prompt/compose"
        try:
            print(f"PersonalityRenderer: calling prompt-composer task={task}", flush=True)
            r = await client.post(url, json=body)
            r.raise_for_status()
            data = r.json()
            print(f"PersonalityRenderer: composer returned {len(json.dumps(data))} bytes", flush=True)
            return data
        except httpx.TimeoutException as e:
            print(f"PersonalityRenderer: composer timeout: {e!r}", flush=True)
            return None
        except httpx.HTTPStatusError as e:
            print(f"PersonalityRenderer: composer HTTP error: {e.response.status_code}", flush=True)
            return None
        except Exception as e:
            print(f"PersonalityRenderer: composer error: {e!r}", flush=True)
            return None

    def _normalize_prefix(self, raw: str) -> str:
        """Normalize raw prefix by removing wrapping quotes.

        :param raw: Raw prefix text
        :type raw: str
        :return: Normalized prefix
        :rtype: str
        """
        text = raw.strip()
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        elif text.startswith("'") and text.endswith("'"):
            text = text[1:-1]
        return text.strip()

    async def _call_llm(
        self, client: httpx.AsyncClient, messages: List[Dict[str, str]]
    ) -> Optional[str]:
        """Call LLM with messages and return prefix text.

        :param client: HTTP client
        :type client: httpx.AsyncClient
        :param messages: Chat messages
        :type messages: List[Dict[str, str]]
        :return: Generated prefix or None on failure
        :rtype: Optional[str]
        """
        headers = {"Content-Type": "application/json"}
        if self.cathy_api_key:
            headers["Authorization"] = f"Bearer {self.cathy_api_key}"

        try:
            if self.cathy_api_mode.lower() == "ollama":
                body = {
                    "model": self.cathy_api_model,
                    "stream": False,
                    "messages": messages,
                    "options": {
                        "temperature": self.temperature,
                        "top_p": self.top_p,
                        "num_predict": 32,
                        "num_ctx": 384,
                        "stop": ["\n"],
                    },
                }
                r = await client.post(
                    f"{self.cathy_api_url.rstrip('/')}/api/chat",
                    headers=headers,
                    json=body,
                )
                r.raise_for_status()
                data = r.json()
                prefix = (data.get("message") or {}).get("content", "").strip()
            else:
                body = {
                    "model": self.cathy_api_model,
                    "messages": messages,
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
                prefix = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )

            return prefix if prefix else None

        except httpx.TimeoutException as e:
            print(f"PersonalityRenderer: LLM timeout: {e!r}", flush=True)
            return None
        except httpx.HTTPStatusError as e:
            print(f"PersonalityRenderer: LLM HTTP error: {e.response.status_code}", flush=True)
            return None
        except Exception as e:
            print(f"PersonalityRenderer: LLM error: {e!r}", flush=True)
            return None

    def _get_fallback_prefix(self, summary_payload: Dict[str, Any]) -> str:
        """Get deterministic fallback prefix from status-based bank.

        Uses a hash of the payload to pick a phrase, giving variety
        across runs while remaining deterministic for the same input.

        :param summary_payload: Summary data
        :type summary_payload: Dict[str, Any]
        :return: Fallback prefix
        :rtype: str
        """
        bucket = self._derive_status_label(summary_payload)

        phrases = _FALLBACK_BANK[bucket]
        digest = hashlib.md5(
            json.dumps(summary_payload, sort_keys=True).encode()
        ).hexdigest()
        idx = int(digest, 16) % len(phrases)
        return phrases[idx]

    def _validate_prefix(
        self,
        text: str,
        deleted_count: int = 0,
    ) -> Tuple[bool, str]:
        """Validate AI prefix against safety rules.

        Cleanup wording is only allowed when *deleted_count > 0*.

        :param text: Prefix text to validate
        :type text: str
        :param deleted_count: Number of items deleted in this run
        :type deleted_count: int
        :return: Tuple of (is_valid, rejection_reason)
        :rtype: Tuple[bool, str]
        """
        t = text.strip()
        tlow = t.lower()

        if not t:
            return False, "empty"
        if len(t) > 140:
            return False, "too long"
        if "\n" in t:
            return False, "contains newline"
        if '"' in t or "'" in t:
            return False, "contains quotes"
        if re.search(r"[.!?].+[.!?]", t):
            return False, "multiple sentences"

        meta_phrases = [
            "matrix", "room", "multiple people", "responding",
            "system", "prompt", "rules", "as an ai",
            "i am a", "i'm a", "bot", "assistant",
        ]
        for phrase in meta_phrases:
            if phrase in tlow:
                return False, f"meta/self-description '{phrase}'"

        bad_ack = ["ok", "understood", "please provide"]
        if any(tlow.startswith(x) for x in bad_ack):
            return False, "acknowledgement/assistant filler"

        banned = [
            "today", "yesterday", "uptime",
            "since", "operational since", "elapsed",
        ]
        for b in banned:
            if re.search(rf"\b{re.escape(b)}\b", tlow):
                return False, f"banned phrase '{b}'"

        if re.search(r"\d", t):
            return False, "contains digits"

        action_words = [
            "deleted", "removed", "purged", "redacted", "cleared",
        ]
        if deleted_count == 0 and any(w in tlow for w in action_words):
            return False, "claims deletion"

        return True, ""

    async def render(
        self, summary_payload: Dict[str, Any], task_id: Optional[str] = None
    ) -> Optional[str]:
        """Render AI prefix using prompt-composer and LLM.

        :param summary_payload: Summary data for rendering
        :type summary_payload: Dict[str, Any]
        :param task_id: Explicit task identifier (overrides mode inference)
        :type task_id: Optional[str]
        :return: Generated prefix or None if rate limited
        :rtype: Optional[str]
        """
        if self._rate_limited():
            return None

        try:
            timeout = httpx.Timeout(
                connect=self.connect_timeout_seconds,
                read=self.timeout_seconds,
                write=self.timeout_seconds,
                pool=self.timeout_seconds,
            )

            async with httpx.AsyncClient(timeout=timeout) as client:
                task = task_id or self._infer_task(summary_payload)
                prompt_bundle = await self._compose_prompt(client, summary_payload, task)
                if not prompt_bundle:
                    print("PersonalityRenderer: no prompt bundle, skipping AI", flush=True)
                    return None

                messages = prompt_bundle.get("messages")
                if not messages:
                    system_text = prompt_bundle.get("system_text", "")
                    if not system_text:
                        print("PersonalityRenderer: empty prompt bundle, skipping AI", flush=True)
                        return None
                    status_label = self._derive_status_label(
                        summary_payload
                    )
                    hint = _STATUS_PROMPT_HINTS.get(
                        status_label,
                        _STATUS_PROMPT_HINTS["healthy_no_action"],
                    )
                    messages = [
                        {"role": "system", "content": system_text},
                        {"role": "user", "content": (
                            "Write ONE short prefix sentence, "
                            "3-8 words.\n"
                            "Address me as 'Master'.\n"
                            f"{hint}\n"
                            "Rules: no digits, no timestamps, "
                            "no percentages, no GB, no quotes, "
                            "no questions."
                        )},
                    ]

                for attempt in range(2):
                    print(f"PersonalityRenderer: input_messages={json.dumps(messages, indent=2)}", flush=True)
                    raw_prefix = await self._call_llm(client, messages)
                    if not raw_prefix:
                        print(f"PersonalityRenderer: empty LLM response (attempt={attempt})", flush=True)
                        if attempt == 0:
                            continue
                        return None

                    print(f"PersonalityRenderer: raw_prefix={raw_prefix!r}", flush=True)
                    normalized = self._normalize_prefix(raw_prefix)
                    print(f"PersonalityRenderer: normalized={normalized!r}", flush=True)

                    deleted_count = summary_payload.get(
                        "actions", {}
                    ).get("deleted_count", 0)
                    ok, reason = self._validate_prefix(
                        normalized, deleted_count=deleted_count
                    )
                    print(f"PersonalityRenderer: validation={ok} reason={reason!r}", flush=True)

                    if not ok:
                        print(f"PersonalityRenderer: rejected (attempt={attempt})", flush=True)
                        if attempt == 0:
                            messages.append({
                                "role": "user",
                                "content": (
                                    f"Your previous response violated a rule: {reason}\n"
                                    "Rewrite as ONE sentence. No digits, no percentages, no GB, no timestamps, no quotes."
                                )
                            })
                            continue
                        fallback = self._get_fallback_prefix(summary_payload)
                        print(f"PersonalityRenderer: using fallback={fallback!r}", flush=True)
                        return fallback

                    print(f"PersonalityRenderer: accepted prefix={normalized!r}", flush=True)
                    return normalized

                fallback = self._get_fallback_prefix(summary_payload)
                print(f"PersonalityRenderer: using fallback={fallback!r}", flush=True)
                return fallback

        except Exception as e:
            print(f"PersonalityRenderer: render exception: {e!r}", flush=True)
            return None
