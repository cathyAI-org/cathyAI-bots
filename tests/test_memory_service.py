"""Tests for memory service."""
import pytest
import tempfile
from pathlib import Path


def test_health():
    """Test health endpoint."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "memory"))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        import main
        main.DB_PATH = Path(tmpdir) / "test.db"
        main.init_db()
        
        from fastapi.testclient import TestClient
        with TestClient(main.app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}


def test_ingest_event():
    """Test event ingestion."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "memory"))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        import main
        main.DB_PATH = Path(tmpdir) / "test.db"
        main.init_db()
        
        from fastapi.testclient import TestClient
        with TestClient(main.app) as client:
            response = client.post(
                "/v1/events/ingest",
                json={
                    "source": "test",
                    "external_user_id": "test_user",
                    "person_id": "person_123",
                    "role": "user",
                    "content": "Test message",
                    "ts": "2024-01-01T12:00:00+00:00",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert "event_id" in data
            assert data["person_id"] == "person_123"


def test_query_memory():
    """Test memory query."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "memory"))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        import main
        main.DB_PATH = Path(tmpdir) / "test.db"
        main.init_db()
        
        from fastapi.testclient import TestClient
        with TestClient(main.app) as client:
            # First ingest an event
            client.post(
                "/v1/events/ingest",
                json={
                    "source": "test",
                    "external_user_id": "test_user",
                    "person_id": "person_123",
                    "role": "user",
                    "content": "Test message",
                    "ts": "2024-01-01T12:00:00+00:00",
                },
            )
            
            # Then query
            response = client.post(
                "/v1/memory/query",
                json={
                    "person_id": "person_123",
                    "k": 10,
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert "results" in data
            assert len(data["results"]) > 0
            assert data["results"][0]["content"] == "Test message"


def test_memory_upsert():
    """Test memory upsert."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "memory"))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        import main
        main.DB_PATH = Path(tmpdir) / "test.db"
        main.init_db()
        
        from fastapi.testclient import TestClient
        with TestClient(main.app) as client:
            # First upsert
            response = client.post(
                "/v1/memories/upsert",
                json={
                    "person_id": "person_123",
                    "char_id": "delilah",
                    "scope": "character",
                    "type": "preference",
                    "text": "Call me Sam.",
                    "importance": 0.8,
                    "source_event_ids": [101, 103],
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "upserted"
            assert data["created"] is True
            fingerprint = data["fingerprint"]
            mem_id = data["id"]
            
            # Second upsert with same fingerprint (idempotent)
            response2 = client.post(
                "/v1/memories/upsert",
                json={
                    "person_id": "person_123",
                    "char_id": "delilah",
                    "scope": "character",
                    "type": "preference",
                    "text": "Call me Sam.",
                    "importance": 0.9,
                    "source_event_ids": [105],
                },
            )
            assert response2.status_code == 200
            data2 = response2.json()
            assert data2["status"] == "upserted"
            assert data2["created"] is False
            assert data2["fingerprint"] == fingerprint
            assert data2["id"] == mem_id


def test_memory_list():
    """Test memory list."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "memory"))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        import main
        main.DB_PATH = Path(tmpdir) / "test.db"
        main.init_db()
        
        from fastapi.testclient import TestClient
        with TestClient(main.app) as client:
            # Upsert a memory
            client.post(
                "/v1/memories/upsert",
                json={
                    "person_id": "person_123",
                    "char_id": "delilah",
                    "type": "preference",
                    "text": "Call me Sam.",
                    "importance": 0.8,
                },
            )
            
            # List memories
            response = client.get(
                "/v1/memories/list",
                params={"person_id": "person_123"},
            )
            assert response.status_code == 200
            data = response.json()
            assert "memories" in data
            assert len(data["memories"]) == 1
            assert data["memories"][0]["text"] == "Call me Sam."
            assert data["memories"][0]["importance"] == 0.8


def test_memory_forget():
    """Test memory forget (soft delete)."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "memory"))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        import main
        main.DB_PATH = Path(tmpdir) / "test.db"
        main.init_db()
        
        from fastapi.testclient import TestClient
        with TestClient(main.app) as client:
            # Upsert a memory
            upsert_resp = client.post(
                "/v1/memories/upsert",
                json={
                    "person_id": "person_123",
                    "char_id": "delilah",
                    "type": "preference",
                    "text": "Call me Sam.",
                    "importance": 0.8,
                },
            )
            fingerprint = upsert_resp.json()["fingerprint"]
            
            # Forget by fingerprint
            forget_resp = client.post(
                "/v1/memories/forget",
                json={"fingerprint": fingerprint, "reason": "test"},
            )
            assert forget_resp.status_code == 200
            assert forget_resp.json()["status"] == "forgotten"
            
            # List should not include deleted
            list_resp = client.get(
                "/v1/memories/list",
                params={"person_id": "person_123"},
            )
            assert len(list_resp.json()["memories"]) == 0
            
            # List with include_deleted should show it
            list_deleted_resp = client.get(
                "/v1/memories/list",
                params={"person_id": "person_123", "include_deleted": True},
            )
            assert len(list_deleted_resp.json()["memories"]) == 1
            assert list_deleted_resp.json()["memories"][0]["deleted_at"] is not None


def test_memory_source_merge():
    """Test source_event_ids merge on upsert."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "memory"))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        import main
        main.DB_PATH = Path(tmpdir) / "test.db"
        main.init_db()
        
        from fastapi.testclient import TestClient
        with TestClient(main.app) as client:
            # First upsert with sources [1, 2]
            client.post(
                "/v1/memories/upsert",
                json={
                    "person_id": "person_123",
                    "type": "fact",
                    "text": "Lives in Seattle.",
                    "source_event_ids": [1, 2],
                },
            )
            
            # Second upsert with sources [2, 3] (should merge to [1, 2, 3])
            client.post(
                "/v1/memories/upsert",
                json={
                    "person_id": "person_123",
                    "type": "fact",
                    "text": "Lives in Seattle.",
                    "source_event_ids": [2, 3],
                },
            )
            
            # Check merged sources
            list_resp = client.get(
                "/v1/memories/list",
                params={"person_id": "person_123"},
            )
            memories = list_resp.json()["memories"]
            assert len(memories) == 1
            assert sorted(memories[0]["sources"]) == [1, 2, 3]


def test_memory_extraction():
    """Test memory extraction from messages."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "memory"))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        import main
        main.DB_PATH = Path(tmpdir) / "test.db"
        main.init_db()
        
        from fastapi.testclient import TestClient
        with TestClient(main.app) as client:
            # Extract memories from messages
            extract_resp = client.post(
                "/v1/memories/extract",
                json={
                    "source": "test",
                    "external_user_id": "test_user",
                    "person_id": "person_123",
                    "char_id": "delilah",
                    "scope": "character",
                    "messages": [
                        {"role": "user", "content": "Call me Sam."},
                        {"role": "user", "content": "I live in Seattle."},
                    ],
                },
            )
            assert extract_resp.status_code == 200
            data = extract_resp.json()
            assert data["status"] == "ok"
            assert len(data["candidates"]) >= 2
            assert len(data["upserted"]) >= 2
            
            # Verify memories were stored
            list_resp = client.get(
                "/v1/memories/list",
                params={"person_id": "person_123"},
            )
            memories = list_resp.json()["memories"]
            assert len(memories) >= 2
            texts = [m["text"] for m in memories]
            assert any("Sam" in t for t in texts)
            assert any("Seattle" in t for t in texts)
