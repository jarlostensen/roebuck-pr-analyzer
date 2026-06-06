"""CLI command dispatch tests using Typer's CliRunner."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from roebuck.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _good_config(tmp_path: Path) -> Path:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[github]\ntoken = "ghp_test"\nrepo = "owner/repo"\n'
    )
    return cfg_path


# ---------------------------------------------------------------------------
# profile --help
# ---------------------------------------------------------------------------

def test_profile_help_lists_subcommands():
    result = runner.invoke(app, ["profile", "--help"])
    assert result.exit_code == 0
    assert "capture" in result.output
    assert "generate-docs" in result.output


# ---------------------------------------------------------------------------
# profile capture
# ---------------------------------------------------------------------------

def test_profile_capture_dispatches_and_exits_0(tmp_path):
    cfg_path = _good_config(tmp_path)
    profile_path = tmp_path / ".roebuck" / "profile.json"
    with patch("roebuck.analysers.profile.capture", return_value=profile_path) as mock_capture:
        result = runner.invoke(app, ["profile", "capture", "--config", str(cfg_path)])
    assert result.exit_code == 0
    assert str(profile_path) in result.output.replace("\n", "")
    mock_capture.assert_called_once()


def test_profile_capture_force_flag_passed(tmp_path):
    cfg_path = _good_config(tmp_path)
    with patch("roebuck.analysers.profile.capture", return_value=None) as mock_capture:
        result = runner.invoke(app, ["profile", "capture", "--force", "--config", str(cfg_path)])
    assert result.exit_code == 0
    _cfg, force = mock_capture.call_args.args[0], mock_capture.call_args.kwargs.get("force", mock_capture.call_args.args[1] if len(mock_capture.call_args.args) > 1 else None)
    assert force is True


def test_profile_capture_missing_config_exits_1(tmp_path):
    result = runner.invoke(app, ["profile", "capture", "--config", str(tmp_path / "missing.toml")])
    assert result.exit_code == 1


def test_profile_capture_returns_none_exits_0(tmp_path):
    cfg_path = _good_config(tmp_path)
    with patch("roebuck.analysers.profile.capture", return_value=None):
        result = runner.invoke(app, ["profile", "capture", "--config", str(cfg_path)])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# profile generate-docs
# ---------------------------------------------------------------------------

def test_profile_generate_docs_dispatches_and_exits_0(tmp_path):
    cfg_path = _good_config(tmp_path)
    doc_path = tmp_path / "reports" / "project-profile-2024-06-01.md"
    with patch("roebuck.analysers.profile.generate_docs", return_value=doc_path) as mock_gen:
        result = runner.invoke(app, ["profile", "generate-docs", "--config", str(cfg_path)])
    assert result.exit_code == 0
    assert str(doc_path) in result.output.replace("\n", "")
    mock_gen.assert_called_once()


def test_profile_generate_docs_missing_profile_exits_1(tmp_path):
    cfg_path = _good_config(tmp_path)
    with patch(
        "roebuck.analysers.profile.generate_docs",
        side_effect=FileNotFoundError(".roebuck/profile.json not found. Run `roebuck profile capture`"),
    ):
        result = runner.invoke(app, ["profile", "generate-docs", "--config", str(cfg_path)])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_profile_generate_docs_runtime_error_exits_1(tmp_path):
    cfg_path = _good_config(tmp_path)
    with patch(
        "roebuck.analysers.profile.generate_docs",
        side_effect=RuntimeError("Failed to parse profile.json"),
    ):
        result = runner.invoke(app, ["profile", "generate-docs", "--config", str(cfg_path)])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_profile_generate_docs_missing_config_exits_1(tmp_path):
    result = runner.invoke(
        app, ["profile", "generate-docs", "--config", str(tmp_path / "missing.toml")]
    )
    assert result.exit_code == 1
