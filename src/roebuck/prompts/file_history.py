from datetime import date
from typing import Optional

from roebuck.config import ContextConfig
from roebuck.models import FileHistoryData
from roebuck.prompts._shared import build_context_section

MAX_COMMITS = 100  # cap history sent to Claude

SYSTEM_PROMPT = """\
You are a senior software engineer analysing the commit history of a single file
to understand its evolution, stability, and risk profile.

Identify patterns such as: repeated bug fixes, ownership churn, periods of heavy
change, and areas that warrant closer review. Be specific and cite commit messages
as evidence where relevant.

Use this definition when assigning stability_trend:
- improving: defect-related commit frequency is decreasing over the most recent third of the history
- degrading: defect-related commit frequency is increasing over the most recent third of the history
- stable: no clear trend — defect frequency is roughly constant or the history is too short to distinguish
"""


def build_user_prompt(
    data: FileHistoryData,
    context: Optional[ContextConfig] = None,
    today: Optional[date] = None,
) -> str:
    """Build the user prompt for file history analysis.

    Args:
        data (FileHistoryData): commit history for the target file
        context (Optional[ContextConfig]): optional project context to prepend
        today (Optional[date]): reference date for "recent" judgements; defaults to today

    Returns:
        str: formatted user prompt string
    """
    today = today or date.today()
    commits = data.commits[:MAX_COMMITS]
    truncated = len(data.commits) > MAX_COMMITS

    defect_count = sum(1 for c in data.commits if c.is_defect)
    total = len(data.commits)

    rows = ["| SHA | Date | Author | Defect? | Message |", "| --- | --- | --- | --- | --- |"]
    for c in commits:
        flag = "yes" if c.is_defect else "no"
        first_line = c.message.splitlines()[0][:80]
        rows.append(f"| `{c.sha}` | {c.date.strftime('%Y-%m-%d')} | {c.author} | {flag} | {first_line} |")

    lines = []
    if context and context.is_set():
        lines += [build_context_section(context), ""]
    lines += [
        f"## Analysis date: {today.strftime('%Y-%m-%d')}",
        f"## File: `{data.path}`",
        f"## Total commits: {total} | Defect-related: {defect_count} ({defect_count/total:.1%})" if total else "## No commits found.",
        "",
        "## Commit History",
        "\n".join(rows),
    ]
    if truncated:
        lines.append(
            f"\n> **Note**: Showing the {MAX_COMMITS} most recent commits; "
            f"{len(data.commits) - MAX_COMMITS} older commits are omitted."
        )

    return "\n".join(lines)


