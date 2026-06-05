from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from mautrix.api import HTTPAPI
from mautrix.client import Client
from mautrix.types import RoomID, DeviceID


@dataclass
class MatrixSession:
    """Matrix session container."""

    api: HTTPAPI
    client: Client
    crypto: Any | None = None
    crypto_db: Any | None = None

    async def close(self) -> None:
        """Close Matrix resources."""
        try:
            if self.crypto_db is not None:
                await self.crypto_db.stop()
        except Exception:
            pass

        try:
            await self.api.session.close()
        except Exception:
            pass


def create_client(mxid: str, base_url: str, token: str) -> MatrixSession:
    """Create a Matrix client session without E2EE."""
    api = HTTPAPI(base_url=base_url, token=token)
    client = Client(mxid=mxid, api=api)
    return MatrixSession(api=api, client=client)


async def create_client_e2ee(
    mxid: str,
    base_url: str,
    token: str,
    e2ee_cfg: dict[str, Any],
) -> MatrixSession:
    """Create a Matrix client session with experimental E2EE support."""
    from mautrix.crypto import OlmMachine
    from mautrix.crypto.store import PgCryptoStore
    from mautrix.util.async_db import Database

    pg = e2ee_cfg["postgres"]
    username = quote(str(pg["username"]), safe="")
    password = quote(str(pg["password"]), safe="")
    host = pg["host"]
    port = int(pg.get("port", 5432))
    database = quote(str(pg["database"]), safe="")

    db_url = f"postgres://{username}:{password}@{host}:{port}/{database}"

    crypto_db = Database.create(
        db_url,
        upgrade_table=PgCryptoStore.upgrade_table,
        owner_name="catcord-cleaner-crypto",
    )
    await crypto_db.start()

    account_id = e2ee_cfg.get("account_id") or mxid
    pickle_key = e2ee_cfg["pickle_key"]

    crypto_store = PgCryptoStore(account_id, pickle_key, crypto_db)

    try:
        from mautrix.client.state_store import MemoryStateStore
    except ImportError:
        from mautrix.client.state_store.memory import MemoryStateStore

    state_store = MemoryStateStore()

    # mautrix crypto expects this on state stores when requesting room keys.
    # MemoryStateStore in this version does not provide it.
    if not hasattr(state_store, "find_shared_rooms"):
        async def find_shared_rooms(user_id):
            return []
        state_store.find_shared_rooms = find_shared_rooms

    api = HTTPAPI(base_url=base_url, token=token)
    client = Client(mxid=mxid, api=api, sync_store=crypto_store, state_store=state_store)

    await crypto_store.open()

    me = await client.whoami()
    device_id = getattr(me, "device_id", None)
    if not device_id:
        raise RuntimeError("E2EE enabled but /account/whoami returned no device_id")

    device_id = DeviceID(device_id)
    client.device_id = device_id
    await crypto_store.put_device_id(device_id)

    print(f"E2EE using device_id={device_id}", flush=True)

    crypto = OlmMachine(client, crypto_store, state_store)
    await crypto.load()
    await crypto.share_keys()

    return MatrixSession(api=api, client=client, crypto=crypto, crypto_db=crypto_db)


async def whoami(session: MatrixSession) -> str:
    """Get the current user ID."""
    me = await session.client.whoami()
    return str(me.user_id)


async def send_text(session: MatrixSession, room_id: str, body: str) -> None:
    """Send a text message to a room."""
    await session.client.send_text(RoomID(room_id), body)
