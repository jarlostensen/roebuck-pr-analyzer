from pathlib import Path

from roebuck.claude_client import ClaudeClient
from roebuck.config import AppConfig
from roebuck.github_client import GitHubClient
from roebuck.models import ChurnAnalysisResult, ChurnEntry
from roebuck.prompts.churn import SYSTEM_PROMPT, build_user_prompt
from roebuck.reports.markdown import MarkdownReportWriter


def run(cfg: AppConfig) -> Path:
    gh = GitHubClient(cfg.github)
    entries = gh.get_churn_data(
        lookback_days=cfg.churn.lookback_days,
        defect_keywords=cfg.churn.defect_keywords,
        min_threshold=cfg.churn.min_commits_threshold,
        max_commits=cfg.churn.max_commits,
    )

    if not entries:
        # Write a minimal report without calling Claude
        writer = MarkdownReportWriter(cfg.reports.output_dir)
        return writer.write(
            "churn",
            [("Summary", f"No files met the minimum commit threshold ({cfg.churn.min_commits_threshold}) "
                         f"in the last {cfg.churn.lookback_days} days.")],
        )

    claude = ClaudeClient(cfg.claude)
    result: ChurnAnalysisResult = claude.analyse(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(
            entries,
            lookback_days=cfg.churn.lookback_days,
            defect_keywords=cfg.churn.defect_keywords,
            repo=cfg.github.repo,
            context=cfg.context,
            coordination_risk_min_authors=cfg.churn.coordination_risk_min_authors,
            coordination_risk_min_defect_ratio=cfg.churn.coordination_risk_min_defect_ratio,
        ),
        output_model=ChurnAnalysisResult,
    )

    writer = MarkdownReportWriter(cfg.reports.output_dir)
    sections = _build_sections(entries, result, cfg)
    return writer.write("churn", sections)


def _build_sections(
    entries: list[ChurnEntry],
    r: ChurnAnalysisResult,
    cfg: AppConfig,
) -> list[tuple[str, str]]:
    return [
        ("Overview", _overview(entries, cfg)),
        ("Hotspot Analysis", r.hotspot_narrative),
        ("Top Risk Files", "\n".join(f"- `{f}`" for f in r.top_risk_files) or "_None identified._"),
        ("Systemic Issues", "\n".join(f"- {i}" for i in r.systemic_issues) or "_None identified._"),
        ("Recommendations", "\n".join(f"- {rec}" for rec in r.recommendations) or "_No recommendations._"),
        ("Full Churn Table", _churn_table(entries)),
    ]


def _overview(entries: list[ChurnEntry], cfg: AppConfig) -> str:
    total_files = len(entries)
    high_defect = sum(1 for e in entries if e.defect_ratio >= 0.5)
    coordination_risk = sum(
        1 for e in entries
        if e.unique_authors >= cfg.churn.coordination_risk_min_authors
        and e.defect_ratio >= cfg.churn.coordination_risk_min_defect_ratio
    )
    return (
        f"- **Lookback window**: {cfg.churn.lookback_days} days\n"
        f"- **Files analysed**: {total_files}\n"
        f"- **High defect-ratio files** (≥50%): {high_defect}\n"
        f"- **Coordination risk files** (≥{cfg.churn.coordination_risk_min_authors} authors"
        f" + ≥{cfg.churn.coordination_risk_min_defect_ratio:.0%} defect ratio): {coordination_risk}\n"
        f"- **Defect keywords**: {', '.join(cfg.churn.defect_keywords)}"
    )


def _churn_table(entries: list[ChurnEntry]) -> str:
    rows = [
        "| File | Total Commits | Defect Commits | Defect Ratio | Unique Authors |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for e in entries:
        rows.append(
            f"| `{e.path}` | {e.total_commits} | {e.defect_commits} | {e.defect_ratio:.1%} | {e.unique_authors} |"
        )
    return "\n".join(rows)
