from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    profile_delta: list[str] = Field(
        default_factory=list,
        description=(
            "Interfaces added, removed, or changed by this PR relative to the "
            "stored project profile. Return an empty list if no project profile "
            "was provided or if drift detection is disabled."
        ),
    )
    spec_vs_reality_gaps: list[str] = Field(
        default_factory=list,
        description=(
            "Gaps between the provided specification documents and the project "
            "profile's description of current behaviour. Return an empty list "
            "if only one source (specs or profile) is present."
        ),
    )


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


# ---------------------------------------------------------------------------
# Project Profile models (Pydantic — LLM output from profile capture)
# ---------------------------------------------------------------------------

class PublicModule(BaseModel):
    """A source module included in the project profile."""

    path: str
    purpose: str


class PublicInterface(BaseModel):
    """A named public interface extracted from the codebase.

    Args:
        name: Identifier name as it appears in source.
        kind: Interface kind — "function", "class", "method", "endpoint", etc.
        signature: Canonical, deterministic string representation.
            Exact-match comparison is reliable only when source is "ast".
        module: Source module path containing this interface.
        source: How the interface was extracted — "ast" for deterministic
            language-specific extraction, "claude" for LLM-based fallback.
        is_public: Whether the interface is considered public by the extractor.
    """

    name: str
    kind: str
    signature: str
    module: str
    source: Literal["ast", "claude"]
    is_public: bool


class DataModel(BaseModel):
    """A key data structure identified in the project profile."""

    name: str
    fields_summary: str
    module: str


class ExtractedInterfaceItem(BaseModel):
    """Single interface extracted by Claude in the Phase 1b fallback path.

    Mirrors :class:`~roebuck.extractors.ExtractedInterface` as a Pydantic model
    so it can be used as the element type in :class:`ExtractionResult` and
    validated by the ADR-0003 schema injection pipeline.

    Args:
        name: Identifier name as it appears in source.
        kind: Interface kind — ``"function"``, ``"class"``, ``"endpoint"``, etc.
        signature: Canonical representation chosen by Claude for this paradigm.
        module: Source file path where this interface was found.
        is_public: Whether Claude considers this interface public.
    """

    name: str
    kind: str
    signature: str
    module: str
    is_public: bool


class ExtractionResult(BaseModel):
    """Claude output for Phase 1b of profile capture.

    Used when no :class:`~roebuck.extractors.LanguageExtractor` matches a file's
    extension. Claude extracts public interfaces from raw source text.

    Args:
        interfaces: Extracted public interfaces for the provided source files.
    """

    interfaces: list[ExtractedInterfaceItem]


class ProfileEnrichmentResult(BaseModel):
    """Claude output for Phase 2 of profile capture.

    Produced by a Claude call that receives the compact extracted interface list
    and returns the narrative and structural layers of the project profile. The
    ``public_interfaces`` list (from Phase 1/1b) and capture metadata
    (``captured_at``, ``captured_commit``, ``captured_ref``) are added by the
    capture orchestrator, not by Claude.

    Args:
        project_summary: One-paragraph description of the project's purpose.
        architecture_notes: Key architectural patterns observed in the interface surface.
        public_modules: Source modules with Claude-assigned purpose descriptions.
        data_models: Key data structures identified from interface signatures.
        external_dependencies: Notable external contracts this project depends on.
    """

    project_summary: str
    architecture_notes: str
    public_modules: list[PublicModule] = Field(default_factory=list)
    data_models: list[DataModel] = Field(default_factory=list)
    external_dependencies: list[str] = Field(default_factory=list)


class ProjectProfile(BaseModel):
    """Structured description of a project's public API surface.

    Captured by ``roebuck profile capture`` and stored in ``.roebuck/profile.json``.
    Used to enrich PR analysis with spec-free alignment checks and to detect
    drift between documented intent and actual implementation.

    Args:
        profile_version: Schema version; incremented on breaking changes.
        project_summary: One-paragraph description of the project's purpose.
        architecture_notes: Key architectural patterns observed in the codebase.
        public_modules: Source modules included in the captured profile.
        public_interfaces: Named public interfaces with signatures and metadata.
        data_models: Key data structures identified in the codebase.
        external_dependencies: Notable external contracts this project depends on.
        captured_at: UTC timestamp of when the profile was captured.
        captured_commit: Full SHA of the HEAD commit at capture time.
        captured_ref: Branch or tag name at capture time; fallback for SHA
            reachability failures caused by rebase or force-push.
    """

    profile_version: int = 1
    project_summary: str
    architecture_notes: str
    public_modules: list[PublicModule] = Field(default_factory=list)
    public_interfaces: list[PublicInterface] = Field(default_factory=list)
    data_models: list[DataModel] = Field(default_factory=list)
    external_dependencies: list[str] = Field(default_factory=list)
    captured_at: datetime
    captured_commit: str
    captured_ref: str
