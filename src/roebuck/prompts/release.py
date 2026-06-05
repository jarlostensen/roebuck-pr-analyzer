from typing import Optional

from roebuck.config import ContextConfig
from roebuck.models import ReleaseData
from roebuck.prompts._shared import build_context_section

# Conservative cap — intentionally well under model context limits.
# Raise if needed; current models (sonnet/haiku) support 200K tokens.
MAX_DIFF_CHARS = 24_000

SYSTEM_PROMPT = """\
You are a senior software engineer performing a release risk assessment.
Analyse the changes between two release tags and identify risks, potential
breaking changes, and areas that require careful attention during deployment.

Be specific — cite file names and diff context as evidence.

Use these calibrated definitions when assigning a risk level:
- critical: introduces data loss, security vulnerability, or system unavailability
- high: likely regression, service disruption, or broken integration under normal use
- medium: non-obvious side effects, partial breakage under specific conditions, or rollback complexity
- low: cosmetic changes, documentation updates, or trivially reversible modifications

When assessing breaking changes, consider each of these categories:
- Public API changes: modified or removed function/method signatures, renamed types
- Removed endpoints: deleted routes, removed CLI commands, dropped public interfaces
- Database schema changes: new migrations, altered columns, dropped tables or indexes
- Configuration changes: new required environment variables or config keys, removed keys
- Dependency upgrades: major-version bumps that may alter behaviour or drop compatibility
- Serialisation changes: modified data formats, renamed JSON fields, changed enums
"""


def build_user_prompt(data: ReleaseData, repo: str, context: Optional[ContextConfig] = None) -> str:
    date_str = data.tag_date.strftime("%Y-%m-%d") if data.tag_date else "unknown"
    diff_block = (
        f"```diff\n{data.diff[:MAX_DIFF_CHARS]}\n```\n\n> **Note**: diff truncated."
        if len(data.diff) > MAX_DIFF_CHARS
        else f"```diff\n{data.diff}\n```"
    )

    parts = []
    if context and context.is_set():
        parts += [build_context_section(context), ""]
    parts += [
        f"## Repository: {repo}",
        f"## Release: `{data.tag}` (released: {date_str})",
        f"## Comparing: `{data.base_tag}` → `{data.tag}`",
        f"## Summary: +{data.additions} / -{data.deletions} across {len(data.changed_files)} files",
        "",
        "## Changed Files",
        "\n".join(f"- `{f}`" for f in data.changed_files) or "_No files changed._",
        "",
        "## Diff",
        diff_block,
        "",
        "## Analysis Questions",
        "Answer each of the following based on the diff and file list above:",
        "1. What is the overall deployment risk level (low / medium / high / critical)?",
        "2. Are there breaking changes to public APIs, database schemas, or configuration?",
        "3. Which changed files carry the highest deployment risk and why?",
        "4. What specific actions should be taken before or during deployment of this release?",
    ]
    return "\n".join(parts)


