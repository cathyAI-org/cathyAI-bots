import pytest
from unittest.mock import Mock, AsyncMock, patch
from catcord_bots.personality import PersonalityRenderer


class TestFramework:
    def test_personality_renderer_init(self):
        renderer = PersonalityRenderer(
            characters_api_url="http://test.com",
            character_id="test_char",
            cathy_api_url="http://cathy.com",
            fallback_system_prompt="Test prompt",
            characters_api_key="test_key",
            characters_api_key_header="X-API-Key"
        )
        assert renderer.character_id == "test_char"
        assert renderer.fallback_system_prompt == "Test prompt"
        assert renderer.characters_api_key == "test_key"
        assert renderer.characters_api_key_header == "X-API-Key"
        assert renderer.timeout_seconds == 15
        assert renderer.min_seconds_between_calls == 30
        assert renderer.cathy_api_mode == "ollama"
        assert renderer.cathy_api_model == "phi3.5:latest"

    def test_personality_renderer_rate_limiting(self):
        renderer = PersonalityRenderer(
            characters_api_url="http://test.com",
            character_id="test",
            cathy_api_url="http://cathy.com",
            fallback_system_prompt="Test",
            min_seconds_between_calls=60
        )
        assert not renderer._rate_limited()
        import time
        renderer._last_call_ts = time.time()
        assert renderer._rate_limited()

    def test_personality_user_prompt_structure(self):
        renderer = PersonalityRenderer(
            characters_api_url="http://test.com",
            character_id="test",
            cathy_api_url="http://cathy.com",
            fallback_system_prompt="Test"
        )
        payload = {"test": "data", "count": 5}
        prompt = renderer._build_user_prompt(payload)
        assert "JSON:" in prompt
        assert "STRICT RULES:" in prompt
        assert "Do NOT invent" in prompt
        assert '"test": "data"' in prompt
