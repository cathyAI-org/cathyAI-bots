"""Core functionality tests for PersonalityRenderer."""
import pytest
from catcord_bots.personality import (
    PersonalityRenderer,
    _FALLBACK_BANK,
    _STATUS_PROMPT_HINTS,
)


class TestPersonalityRenderer:
    """Test suite for PersonalityRenderer class."""

    def _make_renderer(self, **kwargs) -> PersonalityRenderer:
        """Create a renderer with sensible defaults.

        :return: Configured renderer instance
        :rtype: PersonalityRenderer
        """
        defaults = dict(
            prompt_composer_url="http://test",
            character_id="test",
            cathy_api_url="http://test",
            fallback_system_prompt="test",
        )
        defaults.update(kwargs)
        return PersonalityRenderer(**defaults)

    # -- constructor defaults ----------------------------------------

    def test_constructor_defaults(self) -> None:
        """Test default values for optional constructor params."""
        renderer = self._make_renderer()
        assert renderer.timeout_seconds == 60
        assert renderer.min_seconds_between_calls == 0
        assert renderer.cathy_api_mode == "ollama"
        assert renderer.cathy_api_model == "gemma2:2b"

    # -- normalisation -----------------------------------------------

    def test_normalize_prefix_removes_quotes(self) -> None:
        """Test that normalization removes wrapping quotes."""
        renderer = self._make_renderer()

        assert renderer._normalize_prefix('"test"') == "test"
        assert renderer._normalize_prefix("'test'") == "test"
        assert renderer._normalize_prefix("test") == "test"

    # -- status label derivation ------------------------------------

    def test_derive_status_labels(self) -> None:
        cases = [
            ({"actions": {"deleted_count": 3},
              "storage_status": "healthy"}, "cleanup_done"),
            ({"actions": {"deleted_count": 0},
              "storage_status": "tight"}, "tight_no_action"),
            ({"actions": {"deleted_count": 0},
              "storage_status": "warning"}, "tight_no_action"),
            ({"actions": {"deleted_count": 0},
              "storage_status": "pressure"}, "tight_no_action"),
            ({"actions": {"deleted_count": 0},
              "storage_status": "critical"}, "tight_no_action"),
            ({"mode": "retention", "candidates_count": 0,
              "actions": {"deleted_count": 0},
              "storage_status": "healthy"}, "retention_nothing_to_do"),
            ({"actions": {"deleted_count": 0},
              "storage_status": "healthy"}, "healthy_no_action"),
        ]
        for payload, expected in cases:
            assert PersonalityRenderer._derive_status_label(
                payload
            ) == expected, f"{payload} -> {expected}"

    # -- validation --------------------------------------------------

    def test_validate_prefix(self) -> None:
        renderer = self._make_renderer()
        cases = [
            ("", False), ("Contains 123", False),
            ("I am a bot", False), ("Matrix room", False),
            ("Logs clear, Master.", True),
            ("Storage getting tight, Master.", True),
            ("Cleanup executed, Master.", True),
        ]
        for text, valid in cases:
            assert renderer._validate_prefix(text)[0] is valid, (
                f"{text!r} expected {valid}"
            )

    def test_validate_prefix_blocks_action_words_when_no_deletions(
        self,
    ) -> None:
        """Test action words are rejected when deleted_count is 0."""
        renderer = self._make_renderer()

        ok, reason = renderer._validate_prefix(
            "Files deleted, Master.", deleted_count=0
        )
        assert not ok
        assert "claims deletion" in reason

    def test_validate_prefix_allows_action_words_when_deletions(
        self,
    ) -> None:
        """Test action words are allowed when deleted_count > 0."""
        renderer = self._make_renderer()

        ok, _ = renderer._validate_prefix(
            "Old files deleted, Master.", deleted_count=5
        )
        assert ok

    # -- fallback bank -----------------------------------------------

    def test_fallback_prefix_buckets(self) -> None:
        """Test fallback selects from the correct bucket."""
        renderer = self._make_renderer()
        cases = [
            ({"actions": {"deleted_count": 0},
              "storage_status": "healthy"}, "healthy_no_action"),
            ({"actions": {"deleted_count": 0},
              "storage_status": "tight"}, "tight_no_action"),
            ({"actions": {"deleted_count": 5},
              "storage_status": "healthy"}, "cleanup_done"),
            ({"mode": "retention", "candidates_count": 0,
              "actions": {"deleted_count": 0},
              "storage_status": "healthy"}, "retention_nothing_to_do"),
        ]
        for payload, bucket in cases:
            result = renderer._get_fallback_prefix(payload)
            assert result in _FALLBACK_BANK[bucket], (
                f"{bucket}: {result!r} not in bank"
            )

    def test_fallback_prefix_deterministic_for_same_payload(
        self,
    ) -> None:
        """Test same payload always yields the same fallback."""
        renderer = self._make_renderer()
        payload = {
            "actions": {"deleted_count": 0},
            "storage_status": "healthy",
        }
        a = renderer._get_fallback_prefix(payload)
        b = renderer._get_fallback_prefix(payload)
        assert a == b

    def test_fallback_prefix_varies_with_payload(self) -> None:
        """Test different payloads can produce different fallbacks."""
        renderer = self._make_renderer()
        results = set()
        for i in range(20):
            payload = {
                "actions": {"deleted_count": 0},
                "storage_status": "healthy",
                "run_id": i,
            }
            results.add(renderer._get_fallback_prefix(payload))
        assert len(results) > 1

    # -- status prompt hints ----------------------------------------

    def test_status_prompt_hints_cover_all_buckets(self) -> None:
        """Every fallback bucket has a matching prompt hint."""
        assert set(_FALLBACK_BANK) == set(_STATUS_PROMPT_HINTS)

    # -- rate limiting -----------------------------------------------

    def test_rate_limiting(self) -> None:
        """Test rate limiting functionality."""
        renderer = self._make_renderer(min_seconds_between_calls=10)

        assert not renderer._rate_limited()
        assert renderer._rate_limited()
