"""Unit tests for ClaudeClient — Anthropic API calls are mocked."""
import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from roebuck.claude_client import ClaudeClient
from roebuck.config import ClaudeConfig


# ---------------------------------------------------------------------------
# A minimal Pydantic model to use as output_model in tests
# ---------------------------------------------------------------------------

class SimpleModel(BaseModel):
    value: str
    count: int


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg():
    return ClaudeConfig()


@pytest.fixture
def mock_anthropic():
    """Patch Anthropic() for the duration of the test; yields the mock instance."""
    with patch("roebuck.claude_client.Anthropic") as MockAnthropic:
        yield MockAnthropic.return_value


@pytest.fixture
def client(cfg, mock_anthropic):
    return ClaudeClient(cfg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(text, stop_reason="end_turn"):
    response = MagicMock()
    response.stop_reason = stop_reason
    block = MagicMock()
    block.type = "text"
    block.text = text
    response.content = [block]
    return response


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_analyse_returns_parsed_model(client, mock_anthropic):
    mock_anthropic.messages.create.return_value = _make_response(
        json.dumps({"value": "hello", "count": 3})
    )
    result = client.analyse("system", "user", SimpleModel)
    assert result.value == "hello"
    assert result.count == 3


def test_analyse_strips_json_code_fence(client, mock_anthropic):
    fenced = '```json\n{"value": "ok", "count": 0}\n```'
    mock_anthropic.messages.create.return_value = _make_response(fenced)
    result = client.analyse("system", "user", SimpleModel)
    assert result.value == "ok"


def test_analyse_strips_plain_code_fence(client, mock_anthropic):
    fenced = '```\n{"value": "ok", "count": 1}\n```'
    mock_anthropic.messages.create.return_value = _make_response(fenced)
    result = client.analyse("system", "user", SimpleModel)
    assert result.count == 1


# ---------------------------------------------------------------------------
# API call parameters
# ---------------------------------------------------------------------------

def test_analyse_schema_injected_into_system_prompt(client, mock_anthropic, cfg):
    mock_anthropic.messages.create.return_value = _make_response(
        json.dumps({"value": "v", "count": 0})
    )
    client.analyse("MY_SYSTEM", "user", SimpleModel)

    kwargs = mock_anthropic.messages.create.call_args.kwargs
    assert "MY_SYSTEM" in kwargs["system"]
    # JSON schema fields must appear so Claude knows the structure
    assert "value" in kwargs["system"]
    assert "count" in kwargs["system"]


def test_analyse_uses_config_model(client, mock_anthropic, cfg):
    mock_anthropic.messages.create.return_value = _make_response(
        json.dumps({"value": "v", "count": 0})
    )
    client.analyse("sys", "usr", SimpleModel)
    kwargs = mock_anthropic.messages.create.call_args.kwargs
    assert kwargs["model"] == cfg.model


def test_analyse_uses_config_temperature(client, mock_anthropic, cfg):
    mock_anthropic.messages.create.return_value = _make_response(
        json.dumps({"value": "v", "count": 0})
    )
    client.analyse("sys", "usr", SimpleModel)
    kwargs = mock_anthropic.messages.create.call_args.kwargs
    assert kwargs["temperature"] == cfg.temperature


def test_analyse_uses_config_max_tokens(client, mock_anthropic, cfg):
    mock_anthropic.messages.create.return_value = _make_response(
        json.dumps({"value": "v", "count": 0})
    )
    client.analyse("sys", "usr", SimpleModel)
    kwargs = mock_anthropic.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == cfg.max_tokens


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_analyse_max_tokens_stop_reason_raises(client, mock_anthropic):
    mock_anthropic.messages.create.return_value = _make_response(
        "partial...", stop_reason="max_tokens"
    )
    with pytest.raises(RuntimeError, match="max_tokens"):
        client.analyse("sys", "usr", SimpleModel)


def test_analyse_no_text_block_raises(client, mock_anthropic):
    response = MagicMock()
    response.stop_reason = "end_turn"
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    response.content = [tool_block]
    mock_anthropic.messages.create.return_value = response

    with pytest.raises(RuntimeError, match="no text block"):
        client.analyse("sys", "usr", SimpleModel)


def test_analyse_empty_content_raises(client, mock_anthropic):
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = []
    mock_anthropic.messages.create.return_value = response

    with pytest.raises(RuntimeError, match="no text block"):
        client.analyse("sys", "usr", SimpleModel)


def test_analyse_invalid_json_raises(client, mock_anthropic):
    mock_anthropic.messages.create.return_value = _make_response("this is not json")
    with pytest.raises(RuntimeError, match="did not match the expected schema"):
        client.analyse("sys", "usr", SimpleModel)


def test_analyse_schema_mismatch_raises(client, mock_anthropic):
    # Valid JSON but wrong fields for SimpleModel
    mock_anthropic.messages.create.return_value = _make_response(
        json.dumps({"wrong_field": "oops"})
    )
    with pytest.raises(RuntimeError, match="did not match the expected schema"):
        client.analyse("sys", "usr", SimpleModel)


def test_analyse_error_includes_raw_response_preview(client, mock_anthropic):
    bad = "not json at all"
    mock_anthropic.messages.create.return_value = _make_response(bad)
    with pytest.raises(RuntimeError, match="not json at all"):
        client.analyse("sys", "usr", SimpleModel)
