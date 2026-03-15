"""Formatting utilities for bot messages."""
from typing import Dict, Any


def storage_status_label(percent: float, pressure_threshold: float, emergency_threshold: float) -> str:
    """Get storage status label based on usage percent.

    :param percent: Disk usage percentage (0-100)
    :type percent: float
    :param pressure_threshold: Pressure threshold percentage
    :type pressure_threshold: float
    :param emergency_threshold: Emergency threshold percentage
    :type emergency_threshold: float
    :return: Status label
    :rtype: str
    """
    if percent >= emergency_threshold:
        return "critical"
    elif percent >= pressure_threshold:
        return "pressure"
    elif percent >= 75.0:
        return "tight"
    elif percent >= 50.0:
        return "OK"
    else:
        return "healthy"


def format_retention_stats(payload: Dict[str, Any]) -> str:
    """Format retention statistics as multi-line block.

    :param payload: Retention payload dictionary
    :type payload: Dict[str, Any]
    :return: Formatted statistics block
    :rtype: str
    """
    mode = payload.get("mode", "unknown")
    server = payload.get("server", "unknown")
    run_id = payload.get("run_id", "unknown")

    disk = payload.get("disk") or {}
    actions = payload.get("actions") or {}
    timing = payload.get("timing") or {}

    percent_before = disk.get("percent_before", 0.0)
    percent_after = disk.get("percent_after", 0.0)
    pressure_threshold = disk.get("pressure_threshold", 85.0)
    emergency_threshold = disk.get("emergency_threshold", 92.0)

    status = storage_status_label(percent_before, pressure_threshold, emergency_threshold)

    deleted = actions.get("deleted_count", 0)
    freed = actions.get("freed_gb", 0.0)
    by_type = actions.get("deleted_by_type") or {}
    imgs = by_type.get("images", 0)
    non_imgs = by_type.get("non_images", 0)

    candidates = payload.get("candidates_count", 0)
    total_files = payload.get("total_files_count", 0)
    duration = timing.get("duration_seconds", 0)

    lines = [
        f"mode: {mode}",
        f"server: {server}",
        f"run_id: {run_id}",
        f"disk_percent_before: {percent_before:.1f}%",
        f"disk_percent_after: {percent_after:.1f}%",
        f"pressure_threshold: {pressure_threshold:.1f}%",
        f"emergency_threshold: {emergency_threshold:.1f}%",
        f"storage_status: {status}",
        f"candidates_count: {candidates}",
        f"deleted_count: {deleted}",
        f"deleted_images: {imgs}",
        f"deleted_non_images: {non_imgs}",
        f"freed_gb: {freed:.2f}",
        f"total_files_on_disk: {total_files}",
        f"duration_seconds: {duration}",
    ]

    return "\n".join(lines)


def format_pressure_stats(payload: Dict[str, Any]) -> str:
    """Format pressure statistics as single-line string.

    :param payload: Pressure payload dictionary
    :type payload: Dict[str, Any]
    :return: Formatted single-line statistics
    :rtype: str
    """
    disk = payload.get("disk") or {}
    actions = payload.get("actions") or {}

    pb = disk.get("percent_before", 0.0)
    pa = disk.get("percent_after", 0.0)
    pressure_threshold = disk.get("pressure_threshold", 85.0)

    deleted = actions.get("deleted_count", 0)
    freed = actions.get("freed_gb", 0.0)

    if deleted == 0:
        return f"Disk usage: {pb:.1f}% (threshold {pressure_threshold:.1f}%). No deletions. Freed: {freed:.2f} GB."
    else:
        return f"Disk usage: {pb:.1f}%→{pa:.1f}% (threshold {pressure_threshold:.1f}%). Deleted: {deleted}. Freed: {freed:.2f} GB."
