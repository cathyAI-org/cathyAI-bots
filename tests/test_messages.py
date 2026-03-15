"""Tests for cleaner.messages — deterministic status-message composition."""
import json
import re
import tempfile
from pathlib import Path

import pytest
from cleaner.messages import (
    build_status_message,
    derive_status_label,
    load_message_parts,
)

PARTS_PATH = Path(__file__).parent.parent / "cleaner" / "message_parts.json"


class TestDeriveStatusLabel:
    """Tests for derive_status_label."""

    def test_all_labels(self) -> None:
        cases = [
            ("retention", 0, 40.0, "retention_nothing_to_do"),
            ("retention", 5, 40.0, "retention_cleanup_done"),
            ("pressure",  0, 60.0, "pressure_no_action"),
            ("pressure",  3, 86.0, "pressure_cleanup_done"),
            ("pressure",  3, 93.0, "emergency_cleanup_done"),
        ]
        for mode, deleted, used, expected in cases:
            assert derive_status_label(
                mode, deleted_count=deleted,
                used_pct=used, pressure_pct=85.0, emergency_pct=92.0,
            ) == expected, f"{mode}/{deleted}/{used} -> {expected}"


class TestLoadMessageParts:
    """Tests for JSON loading."""

    def test_loads_default_file(self) -> None:
        parts = load_message_parts(path=PARTS_PATH)
        assert "retention_nothing_to_do" in parts
        assert "retention_cleanup_done" in parts
        assert "pressure_no_action" in parts
        assert "pressure_cleanup_done" in parts
        assert "emergency_cleanup_done" in parts

    def test_every_bucket_has_required_categories(self) -> None:
        parts = load_message_parts(path=PARTS_PATH)
        for label, bucket in parts.items():
            for cat in ("opening", "truth", "stats"):
                assert cat in bucket and len(bucket[cat]) > 0, (
                    f"{label} missing non-empty '{cat}'"
                )


class TestBuildStatusMessage:
    """Tests for build_status_message."""

    @pytest.fixture()
    def parts(self) -> dict:
        return load_message_parts(path=PARTS_PATH)

    def test_output_is_non_empty_string(self, parts) -> None:
        msg = build_status_message(
            "retention_nothing_to_do",
            used_pct=42.3, parts=parts,
        )
        assert isinstance(msg, str) and len(msg) > 0

    def test_no_double_spaces(self, parts) -> None:
        for _ in range(50):
            msg = build_status_message(
                "retention_nothing_to_do",
                used_pct=42.3, parts=parts,
            )
            assert "  " not in msg

    def test_empty_closer_omitted(self, parts) -> None:
        """When closer is '' it must not leave trailing space."""
        tiny = {
            "test_status": {
                "opening": ["Hello, Master."],
                "truth": ["All good."],
                "stats": ["Usage is {used_pct:.1f}%."],
                "closer": [""],
            }
        }
        msg = build_status_message(
            "test_status", used_pct=50.0, parts=tiny,
        )
        assert not msg.endswith(" ")

    def test_unknown_status_returns_safe_fallback(self) -> None:
        msg = build_status_message(
            "nonexistent_label", used_pct=55.5, parts={},
        )
        assert "55.5%" in msg

    def test_placeholders_formatted(self, parts) -> None:
        msg = build_status_message(
            "retention_cleanup_done",
            used_pct=72.1,
            deleted_count=3,
            parts=parts,
        )
        assert "72.1%" in msg
        assert "3" in msg

    def test_file_word_singular(self, parts) -> None:
        msg = build_status_message(
            "retention_cleanup_done",
            used_pct=50.0,
            deleted_count=1,
            parts=parts,
        )
        assert "1 file" in msg
        assert "1 files" not in msg

    def test_file_word_plural(self, parts) -> None:
        msg = build_status_message(
            "retention_cleanup_done",
            used_pct=50.0,
            deleted_count=7,
            parts=parts,
        )
        assert "7 files" in msg


# -- factual safety rules ------------------------------------------

_AFFIRM_CLEANUP = re.compile(
    r"\b(removed|deleted|cleared|purged|pruned|reclaimed"
    r"|trimmed)\b",
    re.IGNORECASE,
)


class TestNoActionSafety:
    """No-action statuses must never imply cleanup happened."""

    @pytest.fixture()
    def parts(self) -> dict:
        return load_message_parts(path=PARTS_PATH)

    @pytest.mark.parametrize("label", [
        "retention_nothing_to_do",
        "pressure_no_action",
    ])
    def test_no_affirmative_cleanup_wording(self, label, parts) -> None:
        for _ in range(100):
            msg = build_status_message(
                label, used_pct=40.0,
                pressure_pct=85.0, parts=parts,
            )
            assert not _AFFIRM_CLEANUP.search(msg), (
                f"{label} produced affirmative cleanup wording: {msg!r}"
            )


class TestCleanupDoneSafety:
    """Cleanup-done statuses may mention cleanup."""

    @pytest.fixture()
    def parts(self) -> dict:
        return load_message_parts(path=PARTS_PATH)

    @pytest.mark.parametrize("label", [
        "retention_cleanup_done",
        "pressure_cleanup_done",
        "emergency_cleanup_done",
    ])
    def test_includes_usage_pct(self, label, parts) -> None:
        """All cleanup-done messages must include the disk usage."""
        msg = build_status_message(
            label, used_pct=80.0,
            deleted_count=5, parts=parts,
        )
        assert "80.0%" in msg
