import os
import tomllib
from pathlib import Path
import pytest
from pydantic import ValidationError

from roebuck.config import AppConfig, load_config


MINIMAL_CONFIG = """
[github]
token = "ghp_test"
repo = "owner/repo"
"""

FULL_CONFIG = """
[github]
token = "ghp_test"
repo = "owner/repo"

[claude]
model = "claude-opus-4-6"
max_tokens = 8192
temperature = 0.1

[specs]
patterns = ["docs/**/*.md", "specs/*.md"]

[churn]
lookback_days = 60
defect_keywords = ["fix", "bug"]
min_commits_threshold = 5

[reports]
output_dir = "./out"
"""


def _write_toml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(content)
    return p


def test_minimal_config_loads(tmp_path):
    cfg = load_config(_write_toml(tmp_path, MINIMAL_CONFIG))
    assert cfg.github.repo == "owner/repo"
    assert cfg.github.token == "ghp_test"
    # defaults applied
    assert cfg.claude.model == "claude-sonnet-4-6"
    assert cfg.churn.lookback_days == 90


def test_full_config_loads(tmp_path):
    cfg = load_config(_write_toml(tmp_path, FULL_CONFIG))
    assert cfg.claude.model == "claude-opus-4-6"
    assert cfg.churn.lookback_days == 60
    assert cfg.reports.output_dir == Path("./out")


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.toml"))


def test_invalid_repo_format(tmp_path):
    bad = MINIMAL_CONFIG.replace("owner/repo", "noslash")
    with pytest.raises(ValidationError, match="owner/name"):
        load_config(_write_toml(tmp_path, bad))


def test_env_token_override(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env_token")
    cfg = load_config(_write_toml(tmp_path, MINIMAL_CONFIG))
    assert cfg.github.token == "env_token"


def test_temperature_bounds(tmp_path):
    bad = FULL_CONFIG.replace("temperature = 0.1", "temperature = 1.5")
    with pytest.raises(ValidationError):
        load_config(_write_toml(tmp_path, bad))


# ---------------------------------------------------------------------------
# ProfileConfig — TASK-013
# ---------------------------------------------------------------------------

PROFILE_CONFIG = MINIMAL_CONFIG + """
[profile]
patterns = ["src/**/*.py"]
max_chars = 30000
"""

PROFILE_CONFIG_FULL = MINIMAL_CONFIG + """
[profile]
patterns = ["src/**/*.py", "api/**/*.py"]
max_chars = 50000
stale_commit_threshold = 10
hard_stale_threshold = 50
enable_drift_detection = true
"""


def test_profile_absent_gives_none(tmp_path):
    cfg = load_config(_write_toml(tmp_path, MINIMAL_CONFIG))
    assert cfg.profile is None


def test_profile_section_loads(tmp_path):
    cfg = load_config(_write_toml(tmp_path, PROFILE_CONFIG))
    assert cfg.profile is not None
    assert cfg.profile.patterns == ["src/**/*.py"]
    assert cfg.profile.max_chars == 30000
    # defaults applied
    assert cfg.profile.stale_commit_threshold == 20
    assert cfg.profile.hard_stale_threshold == 100
    assert cfg.profile.enable_drift_detection is False


def test_profile_full_config_loads(tmp_path):
    cfg = load_config(_write_toml(tmp_path, PROFILE_CONFIG_FULL))
    assert cfg.profile.patterns == ["src/**/*.py", "api/**/*.py"]
    assert cfg.profile.max_chars == 50000
    assert cfg.profile.stale_commit_threshold == 10
    assert cfg.profile.hard_stale_threshold == 50
    assert cfg.profile.enable_drift_detection is True


def test_profile_max_chars_below_minimum(tmp_path):
    bad = PROFILE_CONFIG.replace("max_chars = 30000", "max_chars = 500")
    with pytest.raises(ValidationError):
        load_config(_write_toml(tmp_path, bad))
