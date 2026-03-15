import pytest
from catcord_bots.formatting import storage_status_label, format_retention_stats, format_pressure_stats


class TestFormatting:
    def test_storage_status_label(self):
        cases = [
            (30.0, "healthy"), (60.0, "OK"), (80.0, "tight"),
            (87.0, "pressure"), (95.0, "critical"),
        ]
        for pct, expected in cases:
            assert storage_status_label(pct, 85.0, 92.0) == expected

    def test_format_retention_stats(self):
        payload = {
            "mode": "retention",
            "server": "catcord",
            "run_id": "2024-01-01T01:00:00Z-retention",
            "disk": {"percent_before": 45.2, "percent_after": 45.2, "pressure_threshold": 85.0, "emergency_threshold": 92.0},
            "actions": {"deleted_count": 10, "freed_gb": 1.5, "deleted_by_type": {"images": 3, "non_images": 7}},
            "candidates_count": 50,
            "total_files_count": 1000,
            "timing": {"duration_seconds": 5}
        }
        result = format_retention_stats(payload)
        for expected in (
            "mode: retention", "server: catcord",
            "disk_percent_before: 45.2%", "storage_status: healthy",
            "candidates_count: 50", "deleted_count: 10",
            "freed_gb: 1.50", "total_files_on_disk: 1000",
            "duration_seconds: 5",
        ):
            assert expected in result, f"{expected!r} not in result"

    def test_format_pressure_stats(self):
        payload = {
            "disk": {"percent_before": 87.0, "percent_after": 82.0, "pressure_threshold": 85.0, "emergency_threshold": 92.0},
            "actions": {"deleted_count": 5, "freed_gb": 0.8, "deleted_by_type": {"images": 2, "non_images": 3}},
            "timing": {"duration_seconds": 3}
        }
        result = format_pressure_stats(payload)
        for expected in (
            "Disk usage: 87.0%\u2192", "82.0%",
            "threshold 85.0%", "Deleted: 5", "Freed: 0.80 GB",
        ):
            assert expected in result, f"{expected!r} not in result"
        assert "\n" not in result
