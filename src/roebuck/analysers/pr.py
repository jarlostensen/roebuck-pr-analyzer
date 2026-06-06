import logging
from pathlib import Path

from github import GithubException

from roebuck.claude_client import ClaudeClient
from roebuck.config import AppConfig
from roebuck.github_client import GitHubClient
from roebuck.models import PRAnalysisResult, PRData, ProjectProfile
from roebuck.prompts.pr import build_system_prompt, build_user_prompt
from roebuck.reports.markdown import MarkdownReportWriter
from roebuck.spec_loader import SpecLoader

_PROFILE_PATH = Path(".roebuck") / "profile.json"

logger = logging.getLogger(__name__)

_RISK_BADGE = {
    "low": "![low](https://img.shields.io/badge/risk-low-green)",
    "medium": "![medium](https://img.shields.io/badge/risk-medium-yellow)",
    "high": "![high](https://img.shields.io/badge/risk-high-orange)",
    "critical": "![critical](https://img.shields.io/badge/risk-critical-red)",
}

_ALIGNMENT_BADGE = {
    "aligned": "✅ Aligned",
    "partial": "⚠️ Partially aligned",
    "misaligned": "❌ Misaligned",
    "no_specs": "ℹ️ No specs found",
}

_ADEQUACY_BADGE = {
    "adequate": "✅ Adequate",
    "partial": "⚠️ Partial",
    "insufficient": "❌ Insufficient",
    "missing": "❌ Missing",
}


def run(number: int, cfg: AppConfig) -> Path:
    """Analyse a pull request and write a Markdown report.

    Loads the project profile from ``.roebuck/profile.json`` if present and
    checks staleness against the configured thresholds. The profile is
    excluded and a warning section is added when the hard threshold is exceeded.

    Args:
        number: Pull request number.
        cfg: Application configuration.

    Returns:
        Path to the written report file.
    """
    gh = GitHubClient(cfg.github)
    pr_data = gh.get_pr(number)
    specs = SpecLoader(gh.repo, cfg.specs.patterns).load_specs()
    claude = ClaudeClient(cfg.claude)

    profile = _load_profile()
    staleness_warning: str | None = None

    if profile is not None and cfg.profile is not None:
        ahead_by = _check_staleness(gh, profile)
        if ahead_by is not None and ahead_by >= cfg.profile.hard_stale_threshold:
            staleness_warning = (
                f"**Profile excluded from analysis**: the stored profile is "
                f"{ahead_by} commits behind HEAD, exceeding the hard stale "
                f"threshold ({cfg.profile.hard_stale_threshold}). "
                "Run `roebuck profile capture` to refresh."
            )
            profile = None
        elif ahead_by is not None and ahead_by >= cfg.profile.stale_commit_threshold:
            staleness_warning = (
                f"**Profile may be stale**: the stored profile is "
                f"{ahead_by} commits behind HEAD "
                f"(soft threshold: {cfg.profile.stale_commit_threshold}). "
                "Consider refreshing with `roebuck profile capture`."
            )

    result: PRAnalysisResult = claude.analyse(
        system=build_system_prompt(specs, profile),
        user=build_user_prompt(pr_data, specs, context=cfg.context, profile=profile),
        output_model=PRAnalysisResult,
    )

    writer = MarkdownReportWriter(cfg.reports.output_dir)
    sections = _build_sections(pr_data, result, staleness_warning)
    return writer.write(f"pr-{number}", sections)


def _load_profile() -> ProjectProfile | None:
    """Read and parse ``.roebuck/profile.json`` from the current working directory.

    Returns:
        Parsed ProjectProfile, or None if the file is absent or unparseable.
    """
    if not _PROFILE_PATH.exists():
        return None
    try:
        return ProjectProfile.model_validate_json(_PROFILE_PATH.read_text())
    except Exception:
        logger.warning("Failed to parse %s; profile will be ignored", _PROFILE_PATH)
        return None


def _check_staleness(gh: GitHubClient, profile: ProjectProfile) -> int | None:
    """Return how many commits HEAD is ahead of the profile's capture point.

    Tries ``profile.captured_commit`` first; falls back to ``profile.captured_ref``
    on a 404 (SHA rebased or force-pushed). Returns None if both attempts fail
    so the caller can still use the profile.

    Args:
        gh: Initialised GitHubClient.
        profile: Loaded project profile.

    Returns:
        ``ahead_by`` commit count, or None if the check could not be completed.
    """
    try:
        return gh.repo.compare(base=profile.captured_commit, head="HEAD").ahead_by
    except GithubException as e:
        if e.status == 404:
            try:
                return gh.repo.compare(base=profile.captured_ref, head="HEAD").ahead_by
            except Exception:
                logger.warning(
                    "Staleness check failed on both SHA and ref '%s'; skipping",
                    profile.captured_ref,
                )
                return None
        logger.warning("Staleness check failed: %s", e)
        return None
    except Exception:
        logger.warning("Staleness check failed unexpectedly")
        return None


def _build_sections(
    pr: PRData,
    r: PRAnalysisResult,
    staleness_warning: str | None = None,
) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []

    if staleness_warning:
        sections.append(("Profile Staleness Warning", staleness_warning))

    sections += [
        ("Summary", r.summary),
        ("Specification Alignment", _alignment_section(r)),
        ("Risk Assessment", _risk_section(r)),
        ("Test Coverage", _test_section(r)),
        (
            "Recommendations",
            "\n".join(f"- {rec}" for rec in r.recommendations) or "_No recommendations._",
        ),
        (
            "Changed Files",
            f"**{pr.additions}** additions / **{pr.deletions}** deletions\n\n"
            + "\n".join(f"- `{f}`" for f in pr.changed_files),
        ),
    ]

    if r.profile_delta:
        sections.append(("Profile Drift", "\n".join(f"- {d}" for d in r.profile_delta)))

    if r.spec_vs_reality_gaps:
        sections.append(("Spec vs Reality Gaps", "\n".join(f"- {g}" for g in r.spec_vs_reality_gaps)))

    return sections


def _alignment_section(r: PRAnalysisResult) -> str:
    badge = _ALIGNMENT_BADGE.get(r.spec_alignment, r.spec_alignment)
    lines = [f"**{badge}**", ""]
    if r.spec_gaps:
        lines.append("**Gaps identified:**")
        lines.extend(f"- {g}" for g in r.spec_gaps)
    return "\n".join(lines)


def _risk_section(r: PRAnalysisResult) -> str:
    badge = _RISK_BADGE.get(r.risk_level, f"**{r.risk_level.upper()}**")
    lines = [badge, ""]
    if r.risk_factors:
        lines.append("**Risk factors:**")
        lines.extend(f"- {f}" for f in r.risk_factors)
    return "\n".join(lines)


def _test_section(r: PRAnalysisResult) -> str:
    badge = _ADEQUACY_BADGE.get(r.test_adequacy, r.test_adequacy)
    lines = [f"**{badge}**", ""]
    if r.test_gaps:
        lines.append("**Test gaps:**")
        lines.extend(f"- {g}" for g in r.test_gaps)
    return "\n".join(lines)
