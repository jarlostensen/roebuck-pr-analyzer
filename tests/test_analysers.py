"""Unit tests for the profile capture and generate-docs analysers."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from roebuck.analysers.profile import (
    _apply_budget,
    _collision_check,
    _get_head_info,
    _phase1_extract,
    capture,
    generate_docs,
)
from roebuck.config import AppConfig, GitHubConfig, ProfileConfig, ReportsConfig
from roebuck.models import (
    DataModel,
    ExtractionResult,
    ExtractedInterfaceItem,
    ProfileEnrichmentResult,
    ProjectProfile,
    PublicInterface,
    PublicModule,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_cfg(with_profile: bool = True) -> AppConfig:
    github = GitHubConfig(token="ghp_test", repo="owner/repo")
    profile = (
        ProfileConfig(patterns=["src/**/*.py"], max_chars=40000)
        if with_profile
        else None
    )
    return AppConfig(github=github, profile=profile)


def _make_enrichment() -> ProfileEnrichmentResult:
    return ProfileEnrichmentResult(
        project_summary="A test project.",
        architecture_notes="Layered CLI.",
        public_modules=[PublicModule(path="src/main.py", purpose="Entry point")],
        data_models=[DataModel(name="Foo", fields_summary="x: int", module="src/main.py")],
        external_dependencies=["anthropic"],
    )


def _make_extraction_result() -> ExtractionResult:
    return ExtractionResult(
        interfaces=[
            ExtractedInterfaceItem(
                name="handler",
                kind="function",
                signature="def handler(req: Request) -> Response",
                module="api/handler.ts",
                is_public=True,
            )
        ]
    )


def _make_mock_gh(default_branch: str = "main", sha: str = "abc123" * 7) -> MagicMock:
    mock_gh = MagicMock()
    mock_gh.repo.default_branch = default_branch
    mock_gh.repo.get_branch.return_value.commit.sha = sha
    return mock_gh


def _make_mock_claude(enrichment: ProfileEnrichmentResult) -> MagicMock:
    mock_claude = MagicMock()
    mock_claude.analyse.return_value = enrichment
    return mock_claude


# ---------------------------------------------------------------------------
# _collision_check
# ---------------------------------------------------------------------------

def test_collision_check_no_file_returns_true(tmp_path):
    assert _collision_check(tmp_path / "profile.json", force=False) is True


def test_collision_check_force_true_always_proceeds(tmp_path):
    p = tmp_path / "profile.json"
    p.write_text('{"some": "data"}')
    assert _collision_check(p, force=True) is True


def test_collision_check_foreign_file_without_force(tmp_path, capsys):
    p = tmp_path / "profile.json"
    p.write_text('{"other_tool": true}')
    result = _collision_check(p, force=False)
    assert result is False
    assert "--force" in capsys.readouterr().out


def test_collision_check_roebuck_profile_proceeds(tmp_path):
    p = tmp_path / "profile.json"
    p.write_text('{"captured_at": "2024-01-01T00:00:00Z"}')
    assert _collision_check(p, force=False) is True


def test_collision_check_unreadable_file(tmp_path, capsys):
    p = tmp_path / "profile.json"
    p.write_text("{invalid json")
    result = _collision_check(p, force=False)
    assert result is False


# ---------------------------------------------------------------------------
# _apply_budget
# ---------------------------------------------------------------------------

def test_apply_budget_within_limit():
    sources = {"a.py": "aaa", "b.py": "bbb"}
    result = _apply_budget(sources, max_chars=100)
    assert result == {"a.py": "aaa", "b.py": "bbb"}


def test_apply_budget_truncates_at_boundary():
    sources = {"a.py": "a" * 10, "b.py": "b" * 10}
    result = _apply_budget(sources, max_chars=15)
    assert result["a.py"] == "a" * 10
    assert result["b.py"] == "b" * 5


def test_apply_budget_drops_files_beyond_limit():
    sources = {"a.py": "a" * 10, "b.py": "b" * 10, "c.py": "c" * 10}
    result = _apply_budget(sources, max_chars=15)
    assert "c.py" not in result


def test_apply_budget_zero_remaining_stops():
    sources = {"a.py": "a" * 10, "b.py": "b" * 10}
    result = _apply_budget(sources, max_chars=10)
    assert "b.py" not in result


# ---------------------------------------------------------------------------
# _phase1_extract
# ---------------------------------------------------------------------------

def test_phase1_extract_routes_py_to_extractor():
    sources = {"src/main.py": "def public_fn() -> None: ..."}
    ast_ifaces, buffered = _phase1_extract(sources)
    assert len(ast_ifaces) == 1
    assert ast_ifaces[0]["name"] == "public_fn"
    assert buffered == {}


def test_phase1_extract_buffers_unmatched():
    sources = {"src/app.ts": "export function hello(): void {}"}
    ast_ifaces, buffered = _phase1_extract(sources)
    assert ast_ifaces == []
    assert "src/app.ts" in buffered


def test_phase1_extract_mixed_routes_correctly():
    sources = {
        "src/main.py": "def run() -> None: ...",
        "app/handler.ts": "export function handler() {}",
    }
    ast_ifaces, buffered = _phase1_extract(sources)
    assert len(ast_ifaces) == 1
    assert ast_ifaces[0]["module"] == "src/main.py"
    assert "app/handler.ts" in buffered


# ---------------------------------------------------------------------------
# _get_head_info
# ---------------------------------------------------------------------------

def test_get_head_info_returns_sha_and_branch():
    mock_gh = _make_mock_gh(default_branch="main", sha="abc123")
    sha, ref = _get_head_info(mock_gh)
    assert sha == "abc123"
    assert ref == "main"


def test_get_head_info_fallback_on_exception():
    mock_gh = MagicMock()
    mock_gh.repo.default_branch = "main"
    mock_gh.repo.get_branch.side_effect = Exception("API error")
    sha, ref = _get_head_info(mock_gh)
    assert sha == "unknown"
    assert ref == "unknown"


# ---------------------------------------------------------------------------
# capture — guard and collision
# ---------------------------------------------------------------------------

def test_capture_no_profile_config_returns_none(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cfg = _make_cfg(with_profile=False)
    result = capture(cfg)
    assert result is None
    assert "profile" in capsys.readouterr().out.lower()


def test_capture_collision_aborts_without_force(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".roebuck").mkdir()
    (tmp_path / ".roebuck" / "profile.json").write_text('{"other": true}')
    cfg = _make_cfg()
    with patch("roebuck.analysers.profile.GitHubClient"):
        result = capture(cfg, force=False)
    assert result is None
    assert "--force" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# capture — full happy path (all external calls mocked)
# ---------------------------------------------------------------------------

def test_capture_writes_valid_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _make_cfg()
    enrichment = _make_enrichment()

    mock_gh = _make_mock_gh()
    mock_claude = _make_mock_claude(enrichment)

    with (
        patch("roebuck.analysers.profile.GitHubClient", return_value=mock_gh),
        patch("roebuck.analysers.profile.ClaudeClient", return_value=mock_claude),
        patch(
            "roebuck.analysers.profile.SpecLoader"
        ) as MockSpecLoader,
    ):
        MockSpecLoader.return_value.load_specs.return_value = {
            "src/main.py": "def run() -> None: ..."
        }
        result = capture(cfg)

    assert result == Path(".roebuck/profile.json")
    assert (tmp_path / ".roebuck" / "profile.json").exists()
    written = (tmp_path / ".roebuck" / "profile.json").read_text()
    profile = ProjectProfile.model_validate_json(written)
    assert profile.project_summary == "A test project."
    assert profile.captured_ref == "main"
    assert len(profile.public_interfaces) >= 1
    assert profile.public_interfaces[0].source == "ast"


def test_capture_phase1b_triggered_for_unmatched_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _make_cfg()
    enrichment = _make_enrichment()
    extraction = _make_extraction_result()

    mock_gh = _make_mock_gh()
    mock_claude = MagicMock()
    mock_claude.analyse.side_effect = [extraction, enrichment]

    with (
        patch("roebuck.analysers.profile.GitHubClient", return_value=mock_gh),
        patch("roebuck.analysers.profile.ClaudeClient", return_value=mock_claude),
        patch("roebuck.analysers.profile.SpecLoader") as MockSpecLoader,
    ):
        MockSpecLoader.return_value.load_specs.return_value = {
            "api/handler.ts": "export function handler() {}"
        }
        capture(cfg)

    # Two Claude calls: Phase 1b extraction + Phase 2 enrichment
    assert mock_claude.analyse.call_count == 2
    written = (tmp_path / ".roebuck" / "profile.json").read_text()
    profile = ProjectProfile.model_validate_json(written)
    assert any(i.source == "claude" for i in profile.public_interfaces)


def test_capture_only_phase2_when_all_matched(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _make_cfg()
    enrichment = _make_enrichment()
    mock_gh = _make_mock_gh()
    mock_claude = _make_mock_claude(enrichment)

    with (
        patch("roebuck.analysers.profile.GitHubClient", return_value=mock_gh),
        patch("roebuck.analysers.profile.ClaudeClient", return_value=mock_claude),
        patch("roebuck.analysers.profile.SpecLoader") as MockSpecLoader,
    ):
        MockSpecLoader.return_value.load_specs.return_value = {
            "src/app.py": "def app() -> None: ..."
        }
        capture(cfg)

    # Only Phase 2 enrichment call — no Phase 1b
    assert mock_claude.analyse.call_count == 1


def test_capture_force_overwrites_foreign_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".roebuck").mkdir()
    (tmp_path / ".roebuck" / "profile.json").write_text('{"other": true}')
    cfg = _make_cfg()
    enrichment = _make_enrichment()
    mock_gh = _make_mock_gh()
    mock_claude = _make_mock_claude(enrichment)

    with (
        patch("roebuck.analysers.profile.GitHubClient", return_value=mock_gh),
        patch("roebuck.analysers.profile.ClaudeClient", return_value=mock_claude),
        patch("roebuck.analysers.profile.SpecLoader") as MockSpecLoader,
    ):
        MockSpecLoader.return_value.load_specs.return_value = {}
        result = capture(cfg, force=True)

    assert result == Path(".roebuck/profile.json")


# ---------------------------------------------------------------------------
# generate_docs
# ---------------------------------------------------------------------------

def _make_stored_profile(tmp_path: Path) -> Path:
    profile = ProjectProfile(
        project_summary="A sample project.",
        architecture_notes="Monolith.",
        public_modules=[PublicModule(path="src/main.py", purpose="Entry point")],
        public_interfaces=[
            PublicInterface(
                name="run",
                kind="function",
                signature="def run() -> None",
                module="src/main.py",
                source="ast",
                is_public=True,
            )
        ],
        data_models=[DataModel(name="Config", fields_summary="path: str", module="src/config.py")],
        external_dependencies=["anthropic"],
        captured_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        captured_commit="abc123def456" * 3,
        captured_ref="main",
    )
    roebuck_dir = tmp_path / ".roebuck"
    roebuck_dir.mkdir()
    profile_path = roebuck_dir / "profile.json"
    profile_path.write_text(profile.model_dump_json(indent=2))
    return profile_path


def test_generate_docs_creates_markdown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_stored_profile(tmp_path)
    cfg = _make_cfg()
    cfg = cfg.model_copy(
        update={"reports": ReportsConfig(output_dir=tmp_path / "reports")}
    )
    out = generate_docs(cfg)
    assert out.exists()
    content = out.read_text()
    assert "Generated by Roebuck" in content
    assert "A sample project." in content
    assert "Entry point" in content
    assert "def run() -> None" in content


def test_generate_docs_raises_if_no_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _make_cfg()
    with pytest.raises(FileNotFoundError, match="profile capture"):
        generate_docs(cfg)


def test_generate_docs_filename_contains_date(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_stored_profile(tmp_path)
    cfg = _make_cfg()
    cfg = cfg.model_copy(
        update={"reports": ReportsConfig(output_dir=tmp_path / "reports")}
    )
    out = generate_docs(cfg)
    assert "project-profile-" in out.name
    assert out.suffix == ".md"


# ===========================================================================
# PR analyser — profile integration (TASK-018)
# ===========================================================================

from dataclasses import dataclass, field as dc_field
from roebuck.analysers.pr import _load_profile, _check_staleness, _build_sections
from roebuck.models import PRAnalysisResult, PRData, DataModel, PublicInterface, PublicModule


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_pr_data() -> PRData:
    return PRData(
        number=42,
        title="Add feature",
        body="Does stuff",
        author="user",
        base_branch="main",
        head_branch="feature/x",
        diff="+ added line",
        changed_files=["src/app.py"],
        additions=5,
        deletions=2,
        commits=["feat: add feature"],
    )


def _make_pr_result(**kwargs) -> PRAnalysisResult:
    defaults = dict(
        spec_alignment="aligned",
        spec_gaps=[],
        risk_level="low",
        risk_factors=[],
        test_adequacy="adequate",
        test_gaps=[],
        summary="Looks good.",
        recommendations=[],
    )
    defaults.update(kwargs)
    return PRAnalysisResult(**defaults)


def _write_profile(tmp_path: Path) -> Path:
    profile = ProjectProfile(
        project_summary="Test project.",
        architecture_notes="Layered CLI.",
        captured_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        captured_commit="abc" * 14,
        captured_ref="main",
    )
    d = tmp_path / ".roebuck"
    d.mkdir(exist_ok=True)
    p = d / "profile.json"
    p.write_text(profile.model_dump_json())
    return p


# ---------------------------------------------------------------------------
# _load_profile
# ---------------------------------------------------------------------------

def test_load_profile_absent_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _load_profile() is None


def test_load_profile_valid_returns_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path)
    profile = _load_profile()
    assert profile is not None
    assert profile.project_summary == "Test project."


def test_load_profile_malformed_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".roebuck").mkdir()
    (tmp_path / ".roebuck" / "profile.json").write_text("{bad json")
    assert _load_profile() is None


# ---------------------------------------------------------------------------
# _check_staleness
# ---------------------------------------------------------------------------

def test_check_staleness_returns_ahead_by():
    mock_gh = MagicMock()
    mock_gh.repo.compare.return_value.ahead_by = 5
    profile = ProjectProfile(
        project_summary="x",
        architecture_notes="y",
        captured_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        captured_commit="abc123",
        captured_ref="main",
    )
    assert _check_staleness(mock_gh, profile) == 5
    mock_gh.repo.compare.assert_called_once_with(base="abc123", head="HEAD")


def test_check_staleness_falls_back_to_ref_on_404():
    from github import GithubException
    mock_gh = MagicMock()
    exc = GithubException(404, {"message": "Not Found"}, {})
    mock_gh.repo.compare.side_effect = [exc, MagicMock(ahead_by=3)]
    profile = ProjectProfile(
        project_summary="x",
        architecture_notes="y",
        captured_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        captured_commit="dead1234",
        captured_ref="main",
    )
    assert _check_staleness(mock_gh, profile) == 3


def test_check_staleness_returns_none_when_both_fail():
    from github import GithubException
    mock_gh = MagicMock()
    exc = GithubException(404, {"message": "Not Found"}, {})
    mock_gh.repo.compare.side_effect = [exc, Exception("also fails")]
    profile = ProjectProfile(
        project_summary="x",
        architecture_notes="y",
        captured_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        captured_commit="dead1234",
        captured_ref="main",
    )
    assert _check_staleness(mock_gh, profile) is None


def test_check_staleness_non_404_returns_none():
    from github import GithubException
    mock_gh = MagicMock()
    mock_gh.repo.compare.side_effect = GithubException(500, {"message": "Server error"}, {})
    profile = ProjectProfile(
        project_summary="x",
        architecture_notes="y",
        captured_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        captured_commit="abc",
        captured_ref="main",
    )
    assert _check_staleness(mock_gh, profile) is None


# ---------------------------------------------------------------------------
# _build_sections
# ---------------------------------------------------------------------------

def test_build_sections_no_staleness_no_delta():
    pr = _make_pr_data()
    r = _make_pr_result()
    sections = _build_sections(pr, r)
    titles = [s[0] for s in sections]
    assert "Summary" in titles
    assert "Profile Staleness Warning" not in titles
    assert "Profile Drift" not in titles
    assert "Spec vs Reality Gaps" not in titles


def test_build_sections_staleness_warning_first():
    pr = _make_pr_data()
    r = _make_pr_result()
    sections = _build_sections(pr, r, staleness_warning="Stale!")
    assert sections[0] == ("Profile Staleness Warning", "Stale!")


def test_build_sections_profile_delta_appended():
    pr = _make_pr_data()
    r = _make_pr_result(profile_delta=["added: run()", "removed: old_run()"])
    sections = _build_sections(pr, r)
    titles = [s[0] for s in sections]
    assert "Profile Drift" in titles
    drift_body = dict(sections)["Profile Drift"]
    assert "added: run()" in drift_body


def test_build_sections_spec_vs_reality_gaps_appended():
    pr = _make_pr_data()
    r = _make_pr_result(spec_vs_reality_gaps=["spec says X; code does Y"])
    sections = _build_sections(pr, r)
    titles = [s[0] for s in sections]
    assert "Spec vs Reality Gaps" in titles
