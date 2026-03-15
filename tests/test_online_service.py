"""Tests for online service."""
import pytest
import tempfile
from pathlib import Path


def test_health():
    """Test health endpoint."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "online"))

    with tempfile.TemporaryDirectory() as tmpdir:
        import main
        main.DB_PATH = Path(tmpdir) / "test.db"
        main.init_db()

        from fastapi.testclient import TestClient
        with TestClient(main.app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}


def test_fetch_rss_empty_feeds():
    """Test RSS fetch with empty feeds list."""
    import sys

    # Clear any cached main module
    if 'main' in sys.modules:
        del sys.modules['main']

    sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "online"))

    with tempfile.TemporaryDirectory() as tmpdir:
        import main
        main.DB_PATH = Path(tmpdir) / "test.db"
        main.init_db()

        from fastapi.testclient import TestClient
        with TestClient(main.app) as client:
            response = client.post(
                "/v1/rss/fetch",
                json={
                    "feeds": [],
                    "lookback_hours": 24,
                    "max_items": 10,
                    "caller": {"bot": "test"},
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "fetched_at" in data
            assert len(data["items"]) == 0
