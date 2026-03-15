"""Deterministic status-message composition from JSON parts.

Loads sentence fragments from ``message_parts.json`` and assembles
status reports by randomly picking one fragment per category from the
matching status bucket.  Factual values are formatted in Python via
keyword placeholders.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, Optional

_PARTS_CACHE: Optional[Dict[str, Any]] = None
_PARTS_PATH = Path(__file__).with_name("message_parts.json")

_SAFE_FALLBACK = "Status report complete, Master. Disk usage is {used_pct:.1f}%."


def load_message_parts(
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load and cache message parts from JSON.

    :param path: Override path for testing
    :type path: Optional[Path]
    :return: Parsed message-parts dict
    :rtype: Dict[str, Any]
    """
    global _PARTS_CACHE
    if path is not None:
        with open(path) as f:
            return json.load(f)
    if _PARTS_CACHE is None:
        with open(_PARTS_PATH) as f:
            _PARTS_CACHE = json.load(f)
    return _PARTS_CACHE


def derive_status_label(
    mode: str,
    deleted_count: int,
    used_pct: float,
    pressure_pct: float,
    emergency_pct: float,
) -> str:
    """Derive a status label from run facts.

    :param mode: Run mode ('retention' or 'pressure')
    :type mode: str
    :param deleted_count: Files deleted this run
    :type deleted_count: int
    :param used_pct: Current disk usage percentage
    :type used_pct: float
    :param pressure_pct: Pressure threshold percentage
    :type pressure_pct: float
    :param emergency_pct: Emergency threshold percentage
    :type emergency_pct: float
    :return: Status label key into message_parts.json
    :rtype: str
    """
    if mode == "retention":
        if deleted_count > 0:
            return "retention_cleanup_done"
        return "retention_nothing_to_do"

    # pressure / emergency
    if deleted_count == 0:
        return "pressure_no_action"
    if used_pct >= emergency_pct or deleted_count > 0 and used_pct >= emergency_pct:
        return "emergency_cleanup_done"
    return "pressure_cleanup_done"


def build_status_message(
    status_label: str,
    *,
    used_pct: float = 0.0,
    pressure_pct: float = 85.0,
    deleted_count: int = 0,
    file_word: Optional[str] = None,
    parts: Optional[Dict[str, Any]] = None,
) -> str:
    """Compose a human-readable status message from JSON parts.

    Picks one random fragment per category (opening, truth, stats,
    closer) from the bucket matching *status_label*, formats
    placeholders, and joins them into a single string.

    :param status_label: Key into the message-parts dict
    :type status_label: str
    :param used_pct: Current disk usage percentage
    :type used_pct: float
    :param pressure_pct: Pressure threshold percentage
    :type pressure_pct: float
    :param deleted_count: Files deleted this run
    :type deleted_count: int
    :param file_word: Override for pluralization
    :type file_word: Optional[str]
    :param parts: Pre-loaded parts dict (for testing)
    :type parts: Optional[Dict[str, Any]]
    :return: Composed message string
    :rtype: str
    """
    if file_word is None:
        file_word = "file" if deleted_count == 1 else "files"

    fmt_kwargs: Dict[str, Any] = {
        "used_pct": used_pct,
        "pressure_pct": pressure_pct,
        "deleted_count": deleted_count,
        "file_word": file_word,
    }

    if parts is None:
        parts = load_message_parts()

    bucket = parts.get(status_label)
    if not bucket:
        return _SAFE_FALLBACK.format(**fmt_kwargs)

    fragments = []
    seen: set[str] = set()
    for category in ("opening", "truth", "stats", "closer"):
        choices = bucket.get(category, [])
        if not choices:
            continue
        pick = random.choice(choices)
        formatted = pick.format(**fmt_kwargs) if pick else ""
        if formatted and formatted not in seen:
            fragments.append(formatted)
            seen.add(formatted)

    return " ".join(fragments) if fragments else _SAFE_FALLBACK.format(**fmt_kwargs)
