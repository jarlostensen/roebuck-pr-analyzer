"""Unit tests for Pydantic output models."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from roebuck.models import (
    DataModel,
    PRAnalysisResult,
    ProjectProfile,
    PublicInterface,
    PublicModule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_profile(**kwargs) -> ProjectProfile:
    defaults = dict(
        project_summary="A tool for analysing GitHub pull requests.",
        architecture_notes="Layered CLI with pluggable analysers.",
        captured_at=_now(),
        captured_commit="abc123def456" * 3,
        captured_ref="main",
    )
    defaults.update(kwargs)
    return ProjectProfile(**defaults)


def _make_interface(**kwargs) -> PublicInterface:
    defaults = dict(
        name="analyse",
        kind="function",
        signature="def analyse(pr: PRData) -> PRAnalysisResult",
        module="src/roebuck/analysers/pr.py",
        source="ast",
        is_public=True,
    )
    defaults.update(kwargs)
    return PublicInterface(**defaults)


# ---------------------------------------------------------------------------
# PublicInterface
# ---------------------------------------------------------------------------

def test_public_interface_ast_source():
    iface = _make_interface(source="ast")
    assert iface.source == "ast"


def test_public_interface_claude_source():
    iface = _make_interface(source="claude")
    assert iface.source == "claude"


def test_public_interface_rejects_invalid_source():
    with pytest.raises(ValidationError):
        _make_interface(source="llm")


# ---------------------------------------------------------------------------
# ProjectProfile
# ---------------------------------------------------------------------------

def test_project_profile_minimal():
    profile = _make_profile()
    assert profile.profile_version == 1
    assert profile.public_interfaces == []
    assert profile.public_modules == []
    assert profile.data_models == []
    assert profile.external_dependencies == []


def test_project_profile_with_interfaces():
    iface = _make_interface()
    profile = _make_profile(public_interfaces=[iface])
    assert len(profile.public_interfaces) == 1
    assert profile.public_interfaces[0].name == "analyse"


def test_project_profile_with_modules():
    mod = PublicModule(path="src/roebuck/analysers/pr.py", purpose="PR analysis orchestrator")
    profile = _make_profile(public_modules=[mod])
    assert profile.public_modules[0].path == "src/roebuck/analysers/pr.py"


def test_project_profile_with_data_models():
    dm = DataModel(name="PRData", fields_summary="number, title, diff, ...", module="src/roebuck/models.py")
    profile = _make_profile(data_models=[dm])
    assert profile.data_models[0].name == "PRData"


def test_project_profile_roundtrips_json():
    iface = _make_interface()
    mod = PublicModule(path="src/roebuck/cli.py", purpose="CLI entry point")
    profile = _make_profile(public_interfaces=[iface], public_modules=[mod])
    json_str = profile.model_dump_json()
    restored = ProjectProfile.model_validate_json(json_str)
    assert restored.project_summary == profile.project_summary
    assert restored.public_interfaces[0].signature == iface.signature
    assert restored.public_modules[0].path == mod.path
    assert restored.captured_commit == profile.captured_commit


def test_project_profile_requires_captured_at():
    with pytest.raises(ValidationError):
        ProjectProfile(
            project_summary="x",
            architecture_notes="y",
            captured_commit="abc",
            captured_ref="main",
            # captured_at intentionally missing
        )


# ---------------------------------------------------------------------------
# PRAnalysisResult — new fields default to empty list
# ---------------------------------------------------------------------------

def test_pr_analysis_result_profile_delta_defaults_empty():
    result = PRAnalysisResult(
        spec_alignment="no_specs",
        spec_gaps=[],
        risk_level="low",
        risk_factors=[],
        test_adequacy="adequate",
        test_gaps=[],
        summary="All good.",
        recommendations=[],
    )
    assert result.profile_delta == []
    assert result.spec_vs_reality_gaps == []


def test_pr_analysis_result_accepts_profile_delta():
    result = PRAnalysisResult(
        spec_alignment="partial",
        spec_gaps=["Missing auth spec"],
        risk_level="medium",
        risk_factors=["Untested path"],
        test_adequacy="partial",
        test_gaps=["No error path tests"],
        summary="Some concerns.",
        recommendations=["Add tests"],
        profile_delta=["charge() signature changed"],
        spec_vs_reality_gaps=["Spec says synchronous; code is async"],
    )
    assert result.profile_delta == ["charge() signature changed"]
    assert result.spec_vs_reality_gaps == ["Spec says synchronous; code is async"]
