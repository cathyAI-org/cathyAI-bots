from __future__ import annotations
from typing import Dict, List
from .matrix import MatrixSession


async def list_invites(session: MatrixSession) -> List[str]:
    """List all pending room invites.

    :param session: Matrix session
    :type session: MatrixSession
    :return: List of room IDs with pending invites
    :rtype: List[str]
    """
    sync = await session.client.api.request(
        method="GET",
        path="/_matrix/client/v3/sync",
        query_params={"timeout": "0"},
    )
    invites: Dict[str, object] = ((sync.get("rooms") or {}).get("invite") or {})
    return list(invites.keys())


async def join_room(session: MatrixSession, room_id: str) -> None:
    """Join a Matrix room.

    :param session: Matrix session
    :type session: MatrixSession
    :param room_id: Room ID to join
    :type room_id: str
    :return: None
    :rtype: None
    """
    await session.client.api.request(
        method="POST",
        path=f"/_matrix/client/v3/rooms/{room_id}/join",
        content={},
    )


async def join_all_invites(session: MatrixSession, allowlist: list[str] | None = None) -> List[str]:
    """Join all pending room invites, optionally filtered by allowlist.

    :param session: Matrix session
    :type session: MatrixSession
    :param allowlist: Optional list of allowed room IDs
    :type allowlist: list[str] | None
    :return: List of successfully joined room IDs
    :rtype: List[str]
    """
    invites = await list_invites(session)
    joined: List[str] = []
    for rid in invites:
        if allowlist and rid not in allowlist:
            continue
        try:
            await join_room(session, rid)
            joined.append(rid)
        except Exception:
            continue
    return joined
