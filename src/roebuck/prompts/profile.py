"""Prompt builders for the ``roebuck profile capture`` two-phase pipeline.

Phase 1b — extraction: Claude extracts public interfaces from source files whose
file type has no registered :class:`~roebuck.extractors.LanguageExtractor`.

Phase 2 — enrichment: Claude receives the compact extracted interface list and
produces the narrative and structural layers of the project profile
(:class:`~roebuck.models.ProfileEnrichmentResult`).
"""
from roebuck.extractors import ExtractedInterface

MAX_SOURCE_CHARS = 40_000
MAX_INTERFACES_IN_PROMPT = 500


EXTRACTION_SYSTEM_PROMPT = """\
You are a code analysis expert extracting public interface definitions from source files.

For each public interface in the provided source, identify:
- name: the identifier name exactly as written in source
- kind: the interface type — "function", "class", "method", "endpoint", "type", \
"event", or the most appropriate term for this paradigm
- signature: the most compact, unambiguous canonical representation for this \
language/paradigm (examples: REST "POST /payments/{id}/refund (amount?)"; \
TypeScript "function fetchUser(id: string): Promise<User>"; Go \
"func Charge(amount int64, currency string) (*Receipt, error)")
- module: the source file path provided alongside the content
- is_public: true if the interface is part of the module's external contract; \
false for internal helpers, unexported names, or underscore-prefixed identifiers

Exclude private implementation details. When in doubt about publicity, prefer \
including over excluding.

Return a JSON object with a single key "interfaces" containing an array of \
interface objects matching the schema above.
"""

ENRICHMENT_SYSTEM_PROMPT = """\
You are a senior software architect producing a structured project profile from \
a codebase's public API surface.

Given a list of extracted public interfaces and their source modules, produce:

- project_summary: one concise paragraph describing the project's purpose and domain
- architecture_notes: key architectural patterns and structural decisions visible in the \
interface surface (e.g. layered architecture, event-driven, CLI with pluggable analysers)
- public_modules: for each module path provided in the interface list, one entry with \
path and a one-sentence purpose description
- data_models: key data structures identifiable from the interface signatures (parameter \
types, return types); include name, a brief fields_summary, and the module where they appear
- external_dependencies: notable external systems, APIs, or contracts this project \
depends on, as inferred from the interface signatures

Base your analysis strictly on the provided interfaces and module paths. Do not invent \
capabilities that are not evidenced by the interface list.
"""


def build_extraction_prompt(sources: dict[str, str], max_chars: int = MAX_SOURCE_CHARS) -> str:
    """Build the user prompt for Phase 1b Claude extraction of unmatched file types.

    Concatenates source file contents up to ``max_chars`` total and formats
    them with per-file headers so Claude can attribute each interface to the
    correct module path.

    Args:
        sources: Mapping of file path to source content.
        max_chars: Maximum total characters of source content to include.
            Content beyond this limit is truncated with a notice.

    Returns:
        User prompt string ready for :class:`~roebuck.claude_client.ClaudeClient`.
    """
    parts: list[str] = ["## Source Files\n"]
    remaining = max_chars

    for path, content in sources.items():
        if remaining <= 0:
            parts.append(f"\n_Source content truncated at {max_chars} characters._")
            break
        header = f"\n### {path}\n\n```\n"
        footer = "\n```\n"
        available = remaining - len(header) - len(footer)
        if available <= 0:
            parts.append(f"\n_Source content truncated at {max_chars} characters._")
            break
        chunk = content[:available]
        parts.append(header + chunk + footer)
        remaining -= len(header) + len(chunk) + len(footer)

    return "".join(parts)


def build_enrichment_prompt(interfaces: list[ExtractedInterface]) -> str:
    """Build the user prompt for Phase 2 Claude enrichment.

    Formats the merged extracted interface list as a Markdown table and lists
    the unique module paths. Claude uses this to produce the narrative,
    module purposes, data models, and external dependencies that make up
    :class:`~roebuck.models.ProfileEnrichmentResult`.

    Args:
        interfaces: Merged list of extracted interfaces from Phase 1 (AST) and
            Phase 1b (Claude fallback). Only public interfaces are included.

    Returns:
        User prompt string ready for :class:`~roebuck.claude_client.ClaudeClient`.
    """
    public = [i for i in interfaces if i["is_public"]]
    if len(public) > MAX_INTERFACES_IN_PROMPT:
        truncated = True
        public = public[:MAX_INTERFACES_IN_PROMPT]
    else:
        truncated = False

    rows = [
        "## Extracted Interfaces\n",
        "| Name | Kind | Signature | Module |",
        "| --- | --- | --- | --- |",
    ]
    for iface in public:
        sig = iface["signature"].replace("|", r"\|")
        rows.append(f"| {iface['name']} | {iface['kind']} | {sig} | {iface['module']} |")

    if truncated:
        rows.append(f"\n_Table truncated to {MAX_INTERFACES_IN_PROMPT} interfaces._")

    modules = sorted({i["module"] for i in public})
    rows.append("\n## Modules\n")
    for mod in modules:
        rows.append(f"- {mod}")

    return "\n".join(rows)
