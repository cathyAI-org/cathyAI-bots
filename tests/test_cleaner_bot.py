import pytest
import tempfile
import sqlite3
from pathlib import Path
from cleaner.cleaner import (
    parse_mxc, find_media_files, get_disk_usage_ratio, 
    Policy, PersonalityConfig, init_db, extract_mxc_and_info
)


class TestCleanerBot:
    def test_parse_mxc_valid(self):
        result = parse_mxc("mxc://example.com/abc123")
        assert result == ("example.com", "abc123")

    def test_parse_mxc_invalid(self):
        assert parse_mxc("https://example.com/file") is None
        assert parse_mxc("mxc://invalid") is None
        assert parse_mxc(None) is None

    def test_get_disk_usage_ratio(self):
        ratio = get_disk_usage_ratio("/tmp")
        assert 0.0 <= ratio <= 1.0

    def test_find_media_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_id = "test123"
            test_file = Path(tmpdir) / f"media_{media_id}"
            test_file.touch()
            results = find_media_files(tmpdir, f"mxc://example.com/{media_id}")
            assert len(results) == 1
            assert results[0].name == f"media_{media_id}"

    def test_policy_defaults(self):
        p = Policy()
        assert p.image_days == 90
        assert p.non_image_days == 30
        assert p.pressure == 0.85
        assert p.emergency == 0.92

    def test_personality_config_defaults(self):
        cfg = PersonalityConfig()
        assert cfg.enabled is False
        assert cfg.character_id == "irina"
        assert cfg.characters_api_key is None
        assert cfg.characters_api_key_header == "X-API-Key"
        assert cfg.timeout_seconds == 15
        assert cfg.max_tokens == 180
        assert cfg.temperature == 0.2
        assert cfg.cathy_api_mode == "ollama"
        assert cfg.cathy_api_model == "phi3.5:latest"

    def test_personality_config_with_auth(self):
        cfg = PersonalityConfig(
            enabled=True,
            characters_api_key="test_key_123",
            characters_api_key_header="Authorization"
        )
        assert cfg.enabled is True
        assert cfg.characters_api_key == "test_key_123"
        assert cfg.characters_api_key_header == "Authorization"

    def test_init_db_creates_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.db"
            conn = init_db(db_path)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='uploads'")
            assert cur.fetchone() is not None
            conn.close()

    def test_extract_mxc_from_dict_content(self):
        mock_event = type('obj', (object,), {
            'content': {
                'url': 'mxc://test.com/file123',
                'info': {'mimetype': 'image/png', 'size': 1024}
            }
        })()
        url, mimetype, size = extract_mxc_and_info(mock_event)
        assert url == 'mxc://test.com/file123'
        assert mimetype == 'image/png'
        assert size == 1024

    def test_extract_mxc_from_encrypted_file(self):
        mock_event = type('obj', (object,), {
            'content': {
                'file': {'url': 'mxc://test.com/encrypted123'},
                'info': {'mimetype': 'video/mp4', 'size': 2048}
            }
        })()
        url, mimetype, size = extract_mxc_and_info(mock_event)
        assert url == 'mxc://test.com/encrypted123'
        assert mimetype == 'video/mp4'
        assert size == 2048
