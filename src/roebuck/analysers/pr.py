from pathlib import Path

from roebuck.claude_client import ClaudeClient
from roebuck.config import AppConfig
from roebuck.github_client import GitHubClient
from roebuck.models import PRAnalysisResult, PRData
from roebuck.prompts.pr import SYSTEM_PROMPT, build_user_prompt
from roebuck.reports.markdown import MarkdownReportWriter
from roebuck.spec_loader import SpecLoader

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
    gh = GitHubClient(cfg.github)
    pr_data = gh.get_pr(number)
    specs = SpecLoader(gh.repo, cfg.specs.patterns).load_specs()
    claude = ClaudeClient(cfg.claude)

    result: PRAnalysisResult = claude.analyse(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(pr_data, specs, context=cfg.context),
        output_model=PRAnalysisResult,
    )

    writer = MarkdownReportWriter(cfg.reports.output_dir)
    sections = _build_sections(pr_data, result)
    return writer.write(f"pr-{number}", sections)


def _build_sections(pr: PRData, r: PRAnalysisResult) -> list[tuple[str, str]]:
    return [
        ("Summary", r.summary),
        (
            "Specification Alignment",
            _alignment_section(r),
        ),
        (
            "Risk Assessment",
            _risk_section(r),
        ),
        (
            "Test Coverage",
            _test_section(r),
        ),
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
