from pathlib import Path

from roebuck.claude_client import ClaudeClient
from roebuck.config import AppConfig
from roebuck.github_client import GitHubClient
from roebuck.models import ReleaseAnalysisResult, ReleaseData
from roebuck.prompts.release import SYSTEM_PROMPT, build_user_prompt
from roebuck.reports.markdown import MarkdownReportWriter

_RISK_BADGE = {
    "low": "🟢 Low",
    "medium": "🟡 Medium",
    "high": "🟠 High",
    "critical": "🔴 Critical",
}


def run(tag: str, base: str | None, cfg: AppConfig) -> Path:
    gh = GitHubClient(cfg.github)
    data: ReleaseData = gh.get_release_diff(tag=tag, base=base)

    claude = ClaudeClient(cfg.claude)
    result: ReleaseAnalysisResult = claude.analyse(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(data, repo=cfg.github.repo, context=cfg.context),
        output_model=ReleaseAnalysisResult,
    )

    writer = MarkdownReportWriter(cfg.reports.output_dir)
    sections = _build_sections(data, result)
    return writer.write(f"release-{tag}", sections)


def _build_sections(
    data: ReleaseData,
    r: ReleaseAnalysisResult,
) -> list[tuple[str, str]]:
    risk_badge = _RISK_BADGE.get(r.risk_level, f"**{r.risk_level.upper()}**")
    date_str = data.tag_date.strftime("%Y-%m-%d") if data.tag_date else "unknown"

    return [
        (
            "Overview",
            f"- **Release**: `{data.tag}` (released: {date_str})\n"
            f"- **Compared to**: `{data.base_tag}`\n"
            f"- **Risk level**: {risk_badge}\n"
            f"- **Changes**: +{data.additions} / -{data.deletions} across {len(data.changed_files)} files",
        ),
        ("Risk Summary", r.risk_summary),
        (
            "High Risk Files",
            "\n".join(f"- `{f}`" for f in r.high_risk_files) or "_None identified._",
        ),
        (
            "Breaking Change Indicators",
            "\n".join(f"- {b}" for b in r.breaking_change_indicators) or "_None identified._",
        ),
        (
            "Recommendations",
            "\n".join(f"- {rec}" for rec in r.recommendations) or "_No recommendations._",
        ),
        (
            "Changed Files",
            "\n".join(f"- `{f}`" for f in data.changed_files) or "_No files changed._",
        ),
    ]
