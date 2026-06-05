from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Raw GitHub-fetched data (dataclasses — no validation needed)
# ---------------------------------------------------------------------------

@dataclass
class PRData:
    number: int
    title: str
    body: str
    author: str
    base_branch: str
    head_branch: str
    diff: str               # reconstructed unified diff from file patches
    changed_files: list[str]
    additions: int
    deletions: int
    commits: list[str]      # commit messages


@dataclass
class FileCommit:
    sha: str
    message: str
    author: str
    date: datetime
    is_defect: bool = False


@dataclass
class FileHistoryData:
    path: str
    commits: list[FileCommit] = field(default_factory=list)


@dataclass
class ChurnEntry:
    path: str
    total_commits: int
    defect_commits: int
    defect_ratio: float     # defect_commits / total_commits
    unique_authors: int = 0


@dataclass
class ReleaseData:
    tag: str
    base_tag: str
    diff: str               # reconstructed from comparison files
    changed_files: list[str]
    additions: int
    deletions: int
    tag_date: datetime | None = None


# ---------------------------------------------------------------------------
# LLM output models — parsed from Claude JSON responses via Pydantic
# ---------------------------------------------------------------------------

class PRAnalysisResult(BaseModel):
    spec_alignment: str         # "aligned" | "partial" | "misaligned" | "no_specs"
    spec_gaps: list[str]
    risk_level: str             # "low" | "medium" | "high" | "critical"
    risk_factors: list[str]
    test_adequacy: str          # "adequate" | "partial" | "insufficient" | "missing"
    test_gaps: list[str]
    summary: str
    recommendations: list[str]


class FileHistoryResult(BaseModel):
    evolution_summary: str
    risk_areas: list[str]
    stability_trend: str        # "improving" | "stable" | "degrading"
    notable_periods: list[str]


class ChurnAnalysisResult(BaseModel):
    hotspot_narrative: str
    top_risk_files: list[str]
    systemic_issues: list[str]
    recommendations: list[str]


class ReleaseAnalysisResult(BaseModel):
    risk_level: str             # "low" | "medium" | "high" | "critical"
    risk_summary: str
    high_risk_files: list[str]
    breaking_change_indicators: list[str]
    recommendations: list[str]
