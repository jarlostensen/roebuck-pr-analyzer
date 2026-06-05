from datetime import date
from pathlib import Path

from roebuck.claude_client import ClaudeClient
from roebuck.config import AppConfig
from roebuck.github_client import GitHubClient
from roebuck.models import FileHistoryData, FileHistoryResult
from roebuck.prompts.file_history import SYSTEM_PROMPT, build_user_prompt
from roebuck.reports.markdown import MarkdownReportWriter

_TREND_BADGE = {
    "improving": "📈 Improving",
    "stable": "➡️ Stable",
    "degrading": "📉 Degrading",
}


def run(path: str, cfg: AppConfig) -> Path:
    gh = GitHubClient(cfg.github)
    data: FileHistoryData = gh.get_file_history(
        path=path,
        defect_keywords=cfg.churn.defect_keywords,
    )

    if not data.commits:
        writer = MarkdownReportWriter(cfg.reports.output_dir)
        return writer.write(
            _slug(path),
            [("Summary", f"No commits found for `{path}` in the repository.")],
        )

    claude = ClaudeClient(cfg.claude)
    result: FileHistoryResult = claude.analyse(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(data, context=cfg.context, today=date.today()),
        output_model=FileHistoryResult,
    )

    writer = MarkdownReportWriter(cfg.reports.output_dir)
    sections = _build_sections(path, data, result)
    return writer.write(_slug(path), sections)


def _build_sections(
    path: str,
    data: FileHistoryData,
    r: FileHistoryResult,
) -> list[tuple[str, str]]:
    defect_count = sum(1 for c in data.commits if c.is_defect)
    total = len(data.commits)
    trend = _TREND_BADGE.get(r.stability_trend, r.stability_trend)

    return [
        (
            "Overview",
            f"- **File**: `{path}`\n"
            f"- **Total commits**: {total}\n"
            f"- **Defect-related commits**: {defect_count} ({defect_count/total:.1%})\n"
            f"- **Stability trend**: {trend}",
        ),
        ("Evolution Summary", r.evolution_summary),
        ("Risk Areas", "\n".join(f"- {a}" for a in r.risk_areas) or "_None identified._"),
        ("Notable Periods", "\n".join(f"- {p}" for p in r.notable_periods) or "_None identified._"),
        ("Commit History", _commit_table(data)),
    ]


def _commit_table(data: FileHistoryData) -> str:
    rows = [
        "| SHA | Date | Author | Defect? | Message |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in data.commits:
        flag = "⚠️ yes" if c.is_defect else "no"
        first_line = c.message.splitlines()[0][:80]
        rows.append(
            f"| `{c.sha}` | {c.date.strftime('%Y-%m-%d')} | {c.author} | {flag} | {first_line} |"
        )
    return "\n".join(rows)


def _slug(path: str) -> str:
    return "file-" + path.replace("/", "-").replace(".", "-")
