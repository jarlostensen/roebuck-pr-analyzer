from datetime import datetime, timedelta, timezone
from typing import Optional

from roebuck.config import ContextConfig
from roebuck.models import ChurnEntry
from roebuck.prompts._shared import build_context_section

MAX_FILES = 30

SYSTEM_PROMPT = """\
You are a software engineering analyst examining code churn and defect correlation data
for a GitHub repository. Your job is to identify high-risk hotspots, patterns of
instability, and systemic issues based on commit activity and defect-related commit ratios.

Be specific and actionable. Reference file paths from the data when drawing conclusions.
"""


def build_user_prompt(
    entries: list[ChurnEntry],
    lookback_days: int,
    defect_keywords: list[str],
    repo: str,
    context: Optional[ContextConfig] = None,
    coordination_risk_min_authors: int = 5,
    coordination_risk_min_defect_ratio: float = 0.3,
) -> str:
    """Build the user prompt for churn analysis.

    Args:
        entries (list[ChurnEntry]): churn data, pre-sorted descending by total commit count
        lookback_days (int): number of days the analysis window covers
        defect_keywords (list[str]): keywords used to classify defect-related commits
        repo (str): repository identifier in owner/name format
        context (Optional[ContextConfig]): optional project context to prepend
        coordination_risk_min_authors (int): minimum unique-author count for coordination risk flag
        coordination_risk_min_defect_ratio (float): minimum defect ratio for coordination risk flag

    Returns:
        str: formatted user prompt string
    """
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    top = entries[:MAX_FILES]

    rows = ["| File | Total Commits | Defect Commits | Defect Ratio | Unique Authors |", "| --- | --- | --- | --- | --- |"]
    for e in top:
        rows.append(f"| `{e.path}` | {e.total_commits} | {e.defect_commits} | {e.defect_ratio:.1%} | {e.unique_authors} |")

    parts = []
    if context and context.is_set():
        parts.append(build_context_section(context))
        parts.append("")
    parts += [
        f"## Repository: {repo}",
        f"## Analysis window: {since} to today ({lookback_days} days)",
        f"## Defect keywords used: {', '.join(defect_keywords)}",
        (
            "**Note**: defect classification is keyword-based and may include false positives "
            "(e.g. 'fix' matching 'prefix'). Treat defect ratios as signals, not ground truth."
        ),
        f"## Total files analysed: {len(entries)} (showing top {len(top)}, ranked by total commit count descending)",
        f"## Coordination-risk threshold: >{coordination_risk_min_authors} unique authors "
        f"AND >{coordination_risk_min_defect_ratio:.0%} defect ratio",
        "",
        "## Churn and Defect Data",
        "\n".join(rows),
        "",
        "Analyse the above data and identify:",
        "- Which files are the highest-risk hotspots and why (weight both absolute commit count and defect ratio)",
        "- Any systemic patterns (e.g. a module that keeps breaking, test files with high churn)",
        f"- Files meeting the coordination-risk threshold (>{coordination_risk_min_authors} authors"
        f" + >{coordination_risk_min_defect_ratio:.0%} defect ratio) that signal unclear ownership",
        "- Actionable recommendations to reduce risk",
    ]
    return "\n".join(parts)


