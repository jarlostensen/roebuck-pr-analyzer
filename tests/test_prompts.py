"""Unit tests for prompt builders."""
from datetime import date, datetime, timedelta, timezone

from roebuck.config import ContextConfig
from roebuck.models import (
    ChurnEntry,
    FileCommit,
    FileHistoryData,
    PRData,
    ReleaseData,
)
from roebuck.prompts import pr as pr_prompts
from roebuck.prompts import churn as churn_prompts
from roebuck.prompts import file_history as fh_prompts
from roebuck.prompts import release as release_prompts


_CONTEXT = ContextConfig(team="Solo developer", phase="Active development", notes="Iterative discovery")


# ---------------------------------------------------------------------------
# PR prompt
# ---------------------------------------------------------------------------

def _make_pr(**kwargs) -> PRData:
    defaults = dict(
        number=42,
        title="Add feature",
        body="Some description",
        author="alice",
        base_branch="main",
        head_branch="feature/x",
        diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new",
        changed_files=["foo.py"],
        additions=1,
        deletions=1,
        commits=["feat: add feature"],
    )
    defaults.update(kwargs)
    return PRData(**defaults)


def test_pr_prompt_contains_metadata():
    pr = _make_pr()
    prompt = pr_prompts.build_user_prompt(pr, specs={})
    assert "#42" in prompt
    assert "alice" in prompt
    assert "Add feature" in prompt


def test_pr_prompt_diff_included():
    pr = _make_pr()
    prompt = pr_prompts.build_user_prompt(pr, specs={})
    assert "foo.py" in prompt
    assert "+new" in prompt


def test_pr_prompt_diff_truncated():
    big_diff = "x" * (pr_prompts.MAX_DIFF_CHARS + 100)
    pr = _make_pr(diff=big_diff)
    prompt = pr_prompts.build_user_prompt(pr, specs={})
    assert "truncated" in prompt.lower()


def test_pr_prompt_no_specs_message():
    pr = _make_pr()
    prompt = pr_prompts.build_user_prompt(pr, specs={})
    assert "No spec files matched" in prompt


def test_pr_prompt_with_specs():
    pr = _make_pr()
    prompt = pr_prompts.build_user_prompt(pr, specs={"docs/spec.md": "# Spec\ncontent"})
    assert "docs/spec.md" in prompt
    assert "# Spec" in prompt


def test_pr_prompt_specs_trimmed_to_budget():
    # Build specs that exceed the budget
    specs = {f"file{i}.md": "a" * 2000 for i in range(20)}
    pr = _make_pr()
    prompt = pr_prompts.build_user_prompt(pr, specs=specs)
    # The spec section should exist but not include all 20 files worth of content
    spec_content_chars = prompt.count("a" * 100)  # rough check content is bounded
    assert len(prompt) < len(pr_prompts.build_user_prompt(pr, specs={})) + pr_prompts.MAX_SPEC_CHARS_TOTAL + 500


def test_pr_prompt_body_truncated():
    pr = _make_pr(body="b" * 900)
    prompt = pr_prompts.build_user_prompt(pr, specs={})
    assert "TRUNCATED" in prompt


# ---------------------------------------------------------------------------
# Churn prompt
# ---------------------------------------------------------------------------

def test_churn_prompt_contains_repo_and_window():
    entries = [
        ChurnEntry(path="src/hot.py", total_commits=50, defect_commits=10, defect_ratio=0.2),
        ChurnEntry(path="src/cold.py", total_commits=5, defect_commits=0, defect_ratio=0.0),
    ]
    prompt = churn_prompts.build_user_prompt(entries, lookback_days=90, defect_keywords=["fix"], repo="org/repo")
    assert "org/repo" in prompt
    assert "90" in prompt
    assert "src/hot.py" in prompt
    assert "20.0%" in prompt


def test_churn_prompt_caps_at_max_files():
    entries = [
        ChurnEntry(path=f"file{i}.py", total_commits=i + 1, defect_commits=0, defect_ratio=0.0)
        for i in range(churn_prompts.MAX_FILES + 10)
    ]
    prompt = churn_prompts.build_user_prompt(entries, lookback_days=30, defect_keywords=[], repo="x/y")
    # Only MAX_FILES rows should appear in the table
    assert f"file{churn_prompts.MAX_FILES}.py" not in prompt


# ---------------------------------------------------------------------------
# File history prompt
# ---------------------------------------------------------------------------

def _make_file_history(n_commits: int = 3, n_defect: int = 1) -> FileHistoryData:
    commits = [
        FileCommit(
            sha=f"abc{i:04d}",
            message="fix: bug" if i < n_defect else "feat: thing",
            author="dev",
            date=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i),
            is_defect=(i < n_defect),
        )
        for i in range(n_commits)
    ]
    return FileHistoryData(path="src/module.py", commits=commits)


def test_file_history_prompt_contains_path():
    data = _make_file_history()
    prompt = fh_prompts.build_user_prompt(data)
    assert "src/module.py" in prompt


def test_file_history_prompt_defect_ratio():
    data = _make_file_history(n_commits=4, n_defect=1)
    prompt = fh_prompts.build_user_prompt(data)
    assert "25.0%" in prompt


def test_file_history_prompt_truncation_note():
    data = _make_file_history(n_commits=fh_prompts.MAX_COMMITS + 5)
    prompt = fh_prompts.build_user_prompt(data)
    assert "omitted" in prompt.lower() or "older commits" in prompt.lower()


def test_file_history_prompt_no_truncation_note_when_small():
    data = _make_file_history(n_commits=10)
    prompt = fh_prompts.build_user_prompt(data)
    assert "omitted" not in prompt.lower()


# ---------------------------------------------------------------------------
# Release prompt
# ---------------------------------------------------------------------------

def _make_release(**kwargs) -> ReleaseData:
    defaults = dict(
        tag="v1.1.0",
        base_tag="v1.0.0",
        diff="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new",
        changed_files=["app.py"],
        additions=1,
        deletions=1,
        tag_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return ReleaseData(**defaults)


def test_release_prompt_contains_tags():
    data = _make_release()
    prompt = release_prompts.build_user_prompt(data, repo="org/repo")
    assert "v1.1.0" in prompt
    assert "v1.0.0" in prompt
    assert "org/repo" in prompt


def test_release_prompt_diff_truncated():
    data = _make_release(diff="x" * (release_prompts.MAX_DIFF_CHARS + 100))
    prompt = release_prompts.build_user_prompt(data, repo="org/repo")
    assert "truncated" in prompt.lower()


def test_release_prompt_tag_date_shown():
    data = _make_release()
    prompt = release_prompts.build_user_prompt(data, repo="org/repo")
    assert "2024-06-01" in prompt


def test_release_prompt_unknown_date_when_none():
    data = _make_release(tag_date=None)
    prompt = release_prompts.build_user_prompt(data, repo="org/repo")
    assert "unknown" in prompt


# ---------------------------------------------------------------------------
# Context injection — all four prompts
# ---------------------------------------------------------------------------

def test_pr_prompt_includes_context():
    pr = _make_pr()
    prompt = pr_prompts.build_user_prompt(pr, specs={}, context=_CONTEXT)
    assert "Solo developer" in prompt
    assert "Active development" in prompt
    assert "Iterative discovery" in prompt


def test_pr_prompt_no_context_when_empty():
    pr = _make_pr()
    prompt = pr_prompts.build_user_prompt(pr, specs={}, context=ContextConfig())
    assert "Project Context" not in prompt


def test_churn_prompt_includes_context():
    entries = [ChurnEntry(path="src/hot.py", total_commits=5, defect_commits=2, defect_ratio=0.4)]
    prompt = churn_prompts.build_user_prompt(entries, lookback_days=90, defect_keywords=["fix"], repo="x/y", context=_CONTEXT)
    assert "Solo developer" in prompt
    assert "Active development" in prompt
    assert "Iterative discovery" in prompt


def test_churn_prompt_no_context_when_empty():
    entries = [ChurnEntry(path="src/hot.py", total_commits=5, defect_commits=2, defect_ratio=0.4)]
    prompt = churn_prompts.build_user_prompt(entries, lookback_days=90, defect_keywords=["fix"], repo="x/y", context=ContextConfig())
    assert "Project Context" not in prompt


def test_file_history_prompt_includes_context():
    data = _make_file_history()
    prompt = fh_prompts.build_user_prompt(data, context=_CONTEXT)
    assert "Solo developer" in prompt
    assert "Active development" in prompt
    assert "Iterative discovery" in prompt


def test_file_history_prompt_no_context_when_empty():
    data = _make_file_history()
    prompt = fh_prompts.build_user_prompt(data, context=ContextConfig())
    assert "Project Context" not in prompt


def test_release_prompt_includes_context():
    data = _make_release()
    prompt = release_prompts.build_user_prompt(data, repo="org/repo", context=_CONTEXT)
    assert "Solo developer" in prompt
    assert "Active development" in prompt
    assert "Iterative discovery" in prompt


def test_release_prompt_no_context_when_empty():
    data = _make_release()
    prompt = release_prompts.build_user_prompt(data, repo="org/repo", context=ContextConfig())
    assert "Project Context" not in prompt


# ---------------------------------------------------------------------------
# TASK-007: release.py — analysis questions and breaking-change taxonomy
# ---------------------------------------------------------------------------

def test_release_prompt_has_analysis_questions():
    data = _make_release()
    prompt = release_prompts.build_user_prompt(data, repo="org/repo")
    assert "Analysis Questions" in prompt
    assert "deployment risk level" in prompt.lower()
    assert "breaking changes" in prompt.lower()
    assert "actions" in prompt.lower()


def test_release_system_prompt_has_breaking_change_taxonomy():
    sp = release_prompts.SYSTEM_PROMPT.lower()
    assert "database schema" in sp
    assert "environment variable" in sp or "configuration" in sp
    assert "dependency" in sp
    assert "api" in sp or "signature" in sp


# ---------------------------------------------------------------------------
# TASK-008: pr.py and release.py — risk calibration and review dimensions
# ---------------------------------------------------------------------------

def test_pr_system_prompt_has_risk_calibration():
    sp = pr_prompts.SYSTEM_PROMPT.lower()
    assert "critical" in sp
    assert "data loss" in sp or "security" in sp
    assert "medium" in sp
    assert "low" in sp


def test_pr_system_prompt_has_spec_alignment_calibration():
    sp = pr_prompts.SYSTEM_PROMPT.lower()
    assert "aligned" in sp
    assert "misaligned" in sp
    assert "no_specs" in sp


def test_pr_system_prompt_has_review_dimensions():
    sp = pr_prompts.SYSTEM_PROMPT.lower()
    assert "security" in sp
    assert "performance" in sp
    assert "error handling" in sp
    assert "breaking changes" in sp


def test_release_system_prompt_has_risk_calibration():
    sp = release_prompts.SYSTEM_PROMPT.lower()
    assert "critical" in sp
    assert "data loss" in sp or "security" in sp
    assert "medium" in sp
    assert "low" in sp


# ---------------------------------------------------------------------------
# TASK-009: churn.py — keyword caveat, coordination thresholds, ranking note
# ---------------------------------------------------------------------------

def _make_churn_entries() -> list[ChurnEntry]:
    return [
        ChurnEntry(path="src/hot.py", total_commits=50, defect_commits=10, defect_ratio=0.2),
    ]


def test_churn_prompt_has_keyword_false_positive_caveat():
    prompt = churn_prompts.build_user_prompt(
        _make_churn_entries(), lookback_days=90, defect_keywords=["fix"], repo="x/y"
    )
    assert "false positive" in prompt.lower()


def test_churn_prompt_has_ranking_note():
    prompt = churn_prompts.build_user_prompt(
        _make_churn_entries(), lookback_days=90, defect_keywords=["fix"], repo="x/y"
    )
    assert "ranked" in prompt.lower() or "descending" in prompt.lower()


def test_churn_prompt_has_coordination_thresholds():
    prompt = churn_prompts.build_user_prompt(
        _make_churn_entries(),
        lookback_days=90,
        defect_keywords=["fix"],
        repo="x/y",
        coordination_risk_min_authors=3,
        coordination_risk_min_defect_ratio=0.25,
    )
    assert "3" in prompt
    assert "25%" in prompt


def test_churn_prompt_coordination_threshold_defaults():
    prompt = churn_prompts.build_user_prompt(
        _make_churn_entries(), lookback_days=90, defect_keywords=["fix"], repo="x/y"
    )
    # Default thresholds (5 authors, 30%) should appear
    assert "5" in prompt
    assert "30%" in prompt


# ---------------------------------------------------------------------------
# TASK-010: file_history.py — today anchor, stability definition, no emoji
# ---------------------------------------------------------------------------

def test_file_history_prompt_contains_analysis_date():
    data = _make_file_history()
    fixed_today = date(2024, 7, 15)
    prompt = fh_prompts.build_user_prompt(data, today=fixed_today)
    assert "2024-07-15" in prompt


def test_file_history_prompt_defaults_today_when_not_provided():
    data = _make_file_history()
    prompt = fh_prompts.build_user_prompt(data)
    today_str = date.today().strftime("%Y-%m-%d")
    assert today_str in prompt


def test_file_history_system_prompt_has_stability_trend_definition():
    sp = fh_prompts.SYSTEM_PROMPT.lower()
    assert "improving" in sp
    assert "degrading" in sp
    assert "stable" in sp


def test_file_history_prompt_no_emoji():
    data = _make_file_history(n_commits=3, n_defect=2)
    prompt = fh_prompts.build_user_prompt(data)
    # Unicode warning sign and its variation selector must not appear
    assert "⚠" not in prompt


# ---------------------------------------------------------------------------
# TASK-011: _shared.py — build_context_section is importable and correct
# ---------------------------------------------------------------------------

def test_shared_context_section_all_fields():
    from roebuck.prompts._shared import build_context_section
    ctx = ContextConfig(team="Platform", phase="Beta", notes="Handle with care")
    result = build_context_section(ctx)
    assert "## Project Context" in result
    assert "Platform" in result
    assert "Beta" in result
    assert "Handle with care" in result


def test_shared_context_section_partial_fields():
    from roebuck.prompts._shared import build_context_section
    ctx = ContextConfig(team="Platform")
    result = build_context_section(ctx)
    assert "Platform" in result
    assert "Development phase" not in result
    assert "Notes" not in result


# ---------------------------------------------------------------------------
# TASK-015: profile.py — extraction and enrichment prompt builders
# ---------------------------------------------------------------------------

from roebuck.prompts import profile as profile_prompts


def _make_interfaces(n: int = 3) -> list:
    """Return a list of ExtractedInterface TypedDicts for testing."""
    return [
        {
            "name": f"func_{i}",
            "kind": "function",
            "signature": f"def func_{i}(x: int) -> str",
            "module": f"src/module_{i % 2}.py",
            "is_public": True,
        }
        for i in range(n)
    ]


def test_extraction_system_prompt_instructs_interface_extraction():
    sp = profile_prompts.EXTRACTION_SYSTEM_PROMPT.lower()
    assert "public" in sp
    assert "interface" in sp
    assert "signature" in sp
    assert "module" in sp


def test_extraction_system_prompt_asks_for_json_object():
    sp = profile_prompts.EXTRACTION_SYSTEM_PROMPT.lower()
    assert "json" in sp
    assert "interfaces" in sp


def test_build_extraction_prompt_contains_source_header():
    sources = {"src/foo.py": "def hello(): pass"}
    prompt = profile_prompts.build_extraction_prompt(sources)
    assert "Source Files" in prompt
    assert "src/foo.py" in prompt
    assert "def hello" in prompt


def test_build_extraction_prompt_multiple_files():
    sources = {"a.py": "def a(): ...", "b.go": "func B() {}"}
    prompt = profile_prompts.build_extraction_prompt(sources)
    assert "a.py" in prompt
    assert "b.go" in prompt


def test_build_extraction_prompt_respects_max_chars():
    big_content = "x" * 10_000
    sources = {"file1.py": big_content, "file2.py": big_content, "file3.py": big_content}
    prompt = profile_prompts.build_extraction_prompt(sources, max_chars=5_000)
    assert "truncated" in prompt.lower()
    # Total content portion must not exceed limit by much
    assert len(prompt) < 6_000


def test_enrichment_system_prompt_instructs_narrative():
    sp = profile_prompts.ENRICHMENT_SYSTEM_PROMPT.lower()
    assert "project_summary" in sp or "project summary" in sp
    assert "architecture" in sp
    assert "module" in sp


def test_build_enrichment_prompt_contains_interfaces_table():
    interfaces = _make_interfaces(3)
    prompt = profile_prompts.build_enrichment_prompt(interfaces)
    assert "Extracted Interfaces" in prompt
    assert "func_0" in prompt
    assert "func_1" in prompt


def test_build_enrichment_prompt_contains_modules_section():
    interfaces = _make_interfaces(3)
    prompt = profile_prompts.build_enrichment_prompt(interfaces)
    assert "Modules" in prompt
    assert "src/module_0.py" in prompt
    assert "src/module_1.py" in prompt


def test_build_enrichment_prompt_excludes_private_interfaces():
    interfaces = [
        {"name": "public_fn", "kind": "function", "signature": "def public_fn()",
         "module": "mod.py", "is_public": True},
        {"name": "_private", "kind": "function", "signature": "def _private()",
         "module": "mod.py", "is_public": False},
    ]
    prompt = profile_prompts.build_enrichment_prompt(interfaces)
    assert "public_fn" in prompt
    assert "_private" not in prompt


def test_build_enrichment_prompt_empty_interfaces():
    prompt = profile_prompts.build_enrichment_prompt([])
    assert "Extracted Interfaces" in prompt
    assert "Modules" in prompt


def test_build_enrichment_prompt_truncates_large_interface_list():
    interfaces = _make_interfaces(profile_prompts.MAX_INTERFACES_IN_PROMPT + 10)
    prompt = profile_prompts.build_enrichment_prompt(interfaces)
    assert "truncated" in prompt.lower()
