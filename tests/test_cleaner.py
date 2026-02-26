import pytest
import tempfile
import sqlite3
from pathlib import Path
from cleaner.cleaner import init_db, parse_mxc, find_media_files, get_disk_usage_ratio, Policy


class TestCleaner:
    def test_parse_mxc_valid(self):
        result = parse_mxc("mxc://example.com/abc123")
        assert result == ("example.com", "abc123")

    def test_parse_mxc_invalid(self):
        assert parse_mxc("https://example.com/file") is None
        assert parse_mxc("mxc://invalid") is None
        assert parse_mxc(None) is None

    def test_init_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.db"
            conn = init_db(db_path)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='uploads'")
            assert cur.fetchone() is not None
            conn.close()

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
