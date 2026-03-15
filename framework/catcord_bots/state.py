"""State management for deduplication."""
import hashlib
import json
import os
from typing import Dict, Any


def _normalize_payload_for_fingerprint(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract stable fields for fingerprinting, excluding volatile timing/IDs.

    :param payload: Full payload dictionary
    :type payload: Dict[str, Any]
    :return: Normalized payload with stable fields only
    :rtype: Dict[str, Any]
    """
    mode = payload.get("mode", "unknown")
    normalized = {
        "mode": mode,
        "server": payload.get("server", "unknown"),
    }

    disk = payload.get("disk") or {}
    normalized["disk"] = {
        "percent_before": disk.get("percent_before"),
        "percent_after": disk.get("percent_after"),
        "pressure_threshold": disk.get("pressure_threshold"),
        "emergency_threshold": disk.get("emergency_threshold"),
    }

    actions = payload.get("actions") or {}
    normalized["actions"] = {
        "deleted_count": actions.get("deleted_count"),
        "freed_gb": actions.get("freed_gb"),
        "deleted_by_type": actions.get("deleted_by_type"),
    }

    if mode == "retention":
        policy = payload.get("policy") or {}
        normalized["policy"] = policy
        normalized["candidates_count"] = payload.get("candidates_count")
        normalized["total_files_count"] = payload.get("total_files_count")

    return normalized


def payload_fingerprint(payload: Dict[str, Any]) -> str:
    """Generate stable hash from payload, excluding volatile fields.

    :param payload: Payload dictionary
    :type payload: Dict[str, Any]
    :return: SHA256 hexdigest of normalized payload
    :rtype: str
    """
    normalized = _normalize_payload_for_fingerprint(payload)
    s = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def should_send(state_path: str, fp: str, print_effective_config: bool) -> bool:
    """Check if message should be sent based on dedupe state.

    :param state_path: Path to state file
    :type state_path: str
    :param fp: Fingerprint of current payload
    :type fp: str
    :param print_effective_config: Override dedupe and force send
    :type print_effective_config: bool
    :return: True if should send
    :rtype: bool
    """
    if print_effective_config:
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
