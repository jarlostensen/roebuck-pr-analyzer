from typing import Optional

from roebuck.config import ContextConfig
from roebuck.models import PRData
from roebuck.prompts._shared import build_context_section

# Conservative caps — intentionally well under model context limits so the
# system prompt + metadata + LLM output fit within max_tokens headroom.
# Raise these if you need more coverage; current models (sonnet/haiku) support 200K tokens.
MAX_DIFF_CHARS = 24_000
MAX_SPEC_CHARS_TOTAL = 12_000

SYSTEM_PROMPT = """\
You are a senior software engineer performing a thorough pull request review.
Your task is to analyse the PR against the provided project specifications and
assess code quality, risk, and test coverage objectively.

Review across all of the following dimensions:
- Correctness: logic errors, edge-case handling, incorrect assumptions
- Security: injection risks, authentication/authorisation gaps, insecure defaults, secret exposure
- Performance: unnecessary allocations, N+1 queries, blocking calls in hot paths
- Error handling: unhandled exceptions, silent failures, missing input validation
- Test coverage: missing unit tests, untested edge cases, tests that do not assert meaningful behaviour
- Breaking changes: modified public API signatures, removed endpoints, changed config or env vars
- Spec alignment: whether the changed code matches the provided project specifications

Use these calibrated definitions when assigning values:

Risk level:
- critical: introduces data loss, security vulnerability, or system unavailability
- high: likely regression or incorrect behaviour under normal use
- medium: non-obvious side effects, coverage gaps, or potential issues under edge cases
- low: cosmetic, style, or trivially reversible changes

Spec alignment:
- aligned: all changed areas are covered by and consistent with the provided specs
- partial: some changed areas lack spec coverage or have minor gaps
- misaligned: one or more changes contradict stated specifications
- no_specs: no specification files were provided

Be specific — cite file names, function names, or diff lines as evidence.
Do not invent issues that are not supported by the provided context.
"""


def build_user_prompt(pr: PRData, specs: dict[str, str], context: Optional[ContextConfig] = None) -> str:
    sections = []
    if context and context.is_set():
        sections += [build_context_section(context), ""]
    sections += [
        "## Pull Request Metadata",
        f"- **Number**: #{pr.number}",
        f"- **Title**: {pr.title}",
        f"- **Author**: {pr.author}",
        f"- **Base branch**: {pr.base_branch} ← {pr.head_branch}",
        f"- **Changes**: +{pr.additions} / -{pr.deletions} across {len(pr.changed_files)} files",
        "",
        "## PR Description",
        (pr.body[:800] + "\n[TRUNCATED]") if len(pr.body) > 800 else (pr.body or "_No description provided._"),
        "",
        "## Commit Messages",
        "\n".join(f"- {msg.splitlines()[0]}" for msg in pr.commits) or "_No commits._",
        "",
        "## Changed Files",
        "\n".join(f"- `{f}`" for f in pr.changed_files),
        "",
        "## Diff",
        _truncate_diff(pr.diff),
    ]

    if specs:
        sections += ["", "## Specification Files", _trim_specs(specs)]
    else:
        sections += ["", "## Specification Files", "_No spec files matched the configured patterns._"]

    return "\n".join(sections)


def _truncate_diff(diff: str) -> str:
    if len(diff) <= MAX_DIFF_CHARS:
        return f"```diff\n{diff}\n```"
    return f"```diff\n{diff[:MAX_DIFF_CHARS]}\n```\n\n> **Note**: diff truncated at {MAX_DIFF_CHARS} characters."


def _trim_specs(specs: dict[str, str]) -> str:
    budget = MAX_SPEC_CHARS_TOTAL
    parts = []
    # Process shortest files first to fit more files within budget
    for path, content in sorted(specs.items(), key=lambda x: len(x[1])):
        header = f"### {path}\n"
        available = budget - len(header)
        if available <= 0:
            break
        if len(content) > available:
            entry = header + content[:available] + "\n\n> [TRUNCATED]"
        else:
            entry = header + content
        parts.append(entry)
        budget -= len(entry)
        if budget <= 0:
            break
    return "\n\n".join(parts)
