from __future__ import annotations
from dataclasses import dataclass
from mautrix.api import HTTPAPI
from mautrix.client import Client
from mautrix.types import RoomID


@dataclass
class MatrixSession:
    api: HTTPAPI
    client: Client

    async def close(self) -> None:
        try:
            await self.api.session.close()
        except Exception:
            pass


def create_client(mxid: str, base_url: str, token: str) -> MatrixSession:
    api = HTTPAPI(base_url=base_url, token=token)
    client = Client(mxid=mxid, api=api)
    return MatrixSession(api=api, client=client)


async def whoami(session: MatrixSession) -> str:
    me = await session.client.whoami()
    return str(me.user_id)


async def send_text(session: MatrixSession, room_id: str, body: str) -> None:
    await session.client.send_text(RoomID(room_id), body)
