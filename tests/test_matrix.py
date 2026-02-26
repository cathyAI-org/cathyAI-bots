import pytest
from unittest.mock import Mock, AsyncMock
from catcord_bots.matrix import MatrixSession, create_client


class TestMatrix:
    def test_create_client(self):
        session = create_client(
            mxid="@bot:example.com",
            base_url="https://matrix.example.com",
            token="test_token"
        )
        assert session.api is not None
        assert session.client is not None
        assert session.api.token == "test_token"
        assert session.api.base_url == "https://matrix.example.com"

    @pytest.mark.asyncio
    async def test_session_close(self):
        mock_api = Mock()
        mock_api.session = AsyncMock()
        mock_api.session.close = AsyncMock()
        session = MatrixSession(api=mock_api, client=Mock())
        await session.close()
        mock_api.session.close.assert_called_once()
