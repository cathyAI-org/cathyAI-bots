"""Deterministic formatting for news payloads."""
from typing import Dict, Any, Optional
from datetime import datetime


def format_digest(
    payload: Dict[str, Any], ai_prefix: Optional[str] = None
) -> str:
    """Format news digest with optional AI prefix.
    
    :param payload: News payload
    :type payload: Dict[str, Any]
    :param ai_prefix: Optional AI-generated prefix
    :type ai_prefix: Optional[str]
    :return: Formatted message
    :rtype: str
    """
    lines = []
    
    if ai_prefix:
        lines.append(f"Delilah: {ai_prefix}")
        lines.append("")
    
    sections = payload.get("sections", [])
    if not sections:
        lines.append("No recent news items found.")
        return "\n".join(lines)
    
    item_num = 1
    for section in sections:
        items = section.get("items", [])
        for item in items:
            title = item.get("title", "Untitled")
            source = item.get("source", "Unknown")
            url = item.get("url", "")
            pub_at = item.get("published_at", "")
            snippet = item.get("snippet", "")
            
            pub_display = _format_timestamp(pub_at)
            
            lines.append(f"{item_num}) {title} — {source} ({pub_display})")
            if url:
                lines.append(f"   {url}")
            if snippet:
                lines.append(f"   Snippet: {snippet}")
            lines.append("")
            item_num += 1
    
    return "\n".join(lines).rstrip()


def _format_timestamp(iso_str: str) -> str:
    """Format ISO timestamp for display.
    
    :param iso_str: ISO format timestamp
    :type iso_str: str
    :return: Human-readable timestamp
    :rtype: str
    """
    if not iso_str:
        return "Unknown"
    
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str[:16]
