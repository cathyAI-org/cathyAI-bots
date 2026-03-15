"""State management for news bot deduplication."""
import hashlib
import json
import os
from typing import Dict, Any


def payload_fingerprint(payload: Dict[str, Any]) -> str:
    """Generate stable hash from news payload.

    :param payload: News payload
    :type payload: Dict[str, Any]
    :return: SHA256 hexdigest
    :rtype: str
    """
    normalized = {
        "mode": payload.get("mode"),
        "sections": [],
    }

    for section in payload.get("sections", []):
        items = []
        for item in section.get("items", []):
            items.append({
                "url": item.get("url"),
                "published_at": item.get("published_at"),
            })
        normalized["sections"].append({
            "name": section.get("name"),
            "items": items,
        })

    s = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def should_send(state_path: str, fp: str, force: bool) -> bool:
    """Check if message should be sent based on dedupe state.

    :param state_path: Path to state file
    :type state_path: str
    :param fp: Fingerprint of current payload
    :type fp: str
    :param force: Override dedupe and force send
    :type force: bool
    :return: True if should send
    :rtype: bool
    """
    if force:
        return True

    prev = None
    if os.path.exists(state_path):
        with open(state_path, "r") as f:
            prev = f.read().strip() or None

    if prev == fp:
        return False

    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w") as f:
        f.write(fp)
    return True
