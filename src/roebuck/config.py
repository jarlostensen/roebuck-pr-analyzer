import os
import tomllib
from pathlib import Path
from pydantic import BaseModel, Field, field_validator


class GitHubConfig(BaseModel):
    token: str
    repo: str  # "owner/name"

    @field_validator("repo")
    @classmethod
    def repo_has_slash(cls, v: str) -> str:
        if "/" not in v:
            raise ValueError("repo must be in 'owner/name' format")
        return v


class ClaudeConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    max_tokens: int = Field(default=4096, ge=256, le=16384)
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)


class SpecsConfig(BaseModel):
    patterns: list[str] = ["docs/**/*.md"]


class ChurnConfig(BaseModel):
    lookback_days: int = Field(default=90, ge=1)
    defect_keywords: list[str] = ["fix", "bug", "hotfix", "patch", "regression", "revert"]
    min_commits_threshold: int = Field(default=3, ge=1)
    max_commits: int = Field(default=500, ge=10)
    coordination_risk_min_authors: int = Field(default=5, ge=2)
    coordination_risk_min_defect_ratio: float = Field(default=0.3, ge=0.0, le=1.0)


class ReportsConfig(BaseModel):
    output_dir: Path = Path("./reports")


class ContextConfig(BaseModel):
    team: str = ""
    phase: str = ""
    notes: str = ""

    def is_set(self) -> bool:
        """Return True if any context field has been provided."""
        return bool(self.team or self.phase or self.notes)


class AppConfig(BaseModel):
    github: GitHubConfig
    claude: ClaudeConfig = ClaudeConfig()
    specs: SpecsConfig = SpecsConfig()
    churn: ChurnConfig = ChurnConfig()
    reports: ReportsConfig = ReportsConfig()
    context: ContextConfig = ContextConfig()


def load_config(path: Path = Path("config.toml")) -> AppConfig:
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Copy config.toml.example to config.toml and fill in your credentials."
        )
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    # Allow GITHUB_TOKEN env var to override config file value
    if token := os.environ.get("GITHUB_TOKEN"):
        raw.setdefault("github", {})["token"] = token
    return AppConfig.model_validate(raw)
