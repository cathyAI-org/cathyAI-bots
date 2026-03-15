from __future__ import annotations
from dataclasses import dataclass
from mautrix.api import HTTPAPI
from mautrix.client import Client
from mautrix.types import RoomID


@dataclass
class MatrixSession:
    """Matrix session container.

    :param api: Matrix HTTP API instance
    :type api: HTTPAPI
    :param client: Matrix client instance
    :type client: Client
    """
    api: HTTPAPI
    client: Client

    async def close(self) -> None:
        """Close the Matrix API session.

        :return: None
        :rtype: None
        """
        try:
            await self.api.session.close()
        except Exception:
            pass


def create_client(mxid: str, base_url: str, token: str) -> MatrixSession:
    """Create a Matrix client session.

    :param mxid: Matrix user ID
    :type mxid: str
    :param base_url: Homeserver base URL
    :type base_url: str
    :param token: Access token
    :type token: str
    :return: Matrix session
    :rtype: MatrixSession
    """
    api = HTTPAPI(base_url=base_url, token=token)
    client = Client(mxid=mxid, api=api)
    return MatrixSession(api=api, client=client)


async def whoami(session: MatrixSession) -> str:
    """Get the current user ID.

    :param session: Matrix session
    :type session: MatrixSession
    :return: User ID
    :rtype: str
    """
    me = await session.client.whoami()
    return str(me.user_id)


async def send_text(session: MatrixSession, room_id: str, body: str) -> None:
    """Send a text message to a room.

    :param session: Matrix session
    :type session: MatrixSession
    :param room_id: Room ID
    :type room_id: str
    :param body: Message body
    :type body: str
    :return: None
    :rtype: None
    """
    await session.client.send_text(RoomID(room_id), body)
