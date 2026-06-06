"""Analyser for the ``roebuck profile`` command group.

Implements two-phase profile capture:
  Phase 1  — deterministic extraction via :class:`~roebuck.extractors.LanguageExtractor`
  Phase 1b — Claude extraction fallback for unmatched file types
  Phase 2  — Claude enrichment: narrative, module purposes, data models
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from roebuck.claude_client import ClaudeClient
from roebuck.config import AppConfig
from roebuck.extractors import ExtractedInterface
from roebuck.extractors.registry import get_extractor
from roebuck.github_client import GitHubClient
from roebuck.models import (
    ExtractionResult,
    ProfileEnrichmentResult,
    ProjectProfile,
    PublicInterface,
)
from roebuck.prompts.profile import (
    ENRICHMENT_SYSTEM_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    build_enrichment_prompt,
    build_extraction_prompt,
)
from roebuck.spec_loader import SpecLoader

_PROFILE_PATH = Path(".roebuck") / "profile.json"

logger = logging.getLogger(__name__)


def capture(cfg: AppConfig, force: bool = False) -> Path | None:
    """Extract a project profile and write it to ``.roebuck/profile.json``.

    Two-phase extraction:

    1. AST-based extraction for registered file types (deterministic;
       interfaces tagged ``source="ast"``).
    2. Claude extraction fallback for unmatched file types (interfaces
       tagged ``source="claude"``).

    Followed by a Claude enrichment call that adds narrative, module
    purposes, data models, and external dependencies.

    Args:
        cfg: Application configuration. If ``cfg.profile`` is ``None``,
            the function prints a warning and returns ``None``.
        force: When ``True``, overwrites an existing ``.roebuck/profile.json``
            even if it was not written by Roebuck. Defaults to ``False``.

    Returns:
        Path to the written profile file, or ``None`` if capture was skipped.
    """
    if cfg.profile is None:
        print(
            "No [profile] section in config.toml. "
            "Add patterns and max_chars to enable profile capture."
        )
        return None

    if not _collision_check(_PROFILE_PATH, force):
        return None

    gh = GitHubClient(cfg.github)
    claude = ClaudeClient(cfg.claude)

    raw_sources = SpecLoader(gh.repo, cfg.profile.patterns).load_specs()
    sources = _apply_budget(raw_sources, cfg.profile.max_chars)

    ast_interfaces, buffered = _phase1_extract(sources)

    claude_interfaces = _phase1b_extract(buffered, claude, cfg.profile.max_chars) if buffered else []

    merged: list[ExtractedInterface] = ast_interfaces + claude_interfaces

    enrichment: ProfileEnrichmentResult = claude.analyse(
        system=ENRICHMENT_SYSTEM_PROMPT,
        user=build_enrichment_prompt(merged),
        output_model=ProfileEnrichmentResult,
    )

    captured_commit, captured_ref = _get_head_info(gh)

    public_interfaces = [
        PublicInterface(**iface, source="ast")
        for iface in ast_interfaces
        if iface["is_public"]
    ] + [
        PublicInterface(**iface, source="claude")
        for iface in claude_interfaces
        if iface["is_public"]
    ]

    profile = ProjectProfile(
        project_summary=enrichment.project_summary,
        architecture_notes=enrichment.architecture_notes,
        public_modules=enrichment.public_modules,
        public_interfaces=public_interfaces,
        data_models=enrichment.data_models,
        external_dependencies=enrichment.external_dependencies,
        captured_at=datetime.now(timezone.utc),
        captured_commit=captured_commit,
        captured_ref=captured_ref,
    )

    _PROFILE_PATH.parent.mkdir(exist_ok=True)
    _PROFILE_PATH.write_text(profile.model_dump_json(indent=2))
    return _PROFILE_PATH


def generate_docs(cfg: AppConfig) -> Path:
    """Render the stored project profile as a Markdown draft document.

    Reads ``.roebuck/profile.json`` from the current working directory,
    renders a human-readable Markdown file from both the narrative and
    structured layers, and writes it to ``cfg.reports.output_dir``.

    Args:
        cfg: Application configuration; ``reports.output_dir`` determines
            the output location.

    Returns:
        Path to the written Markdown file.

    Raises:
        FileNotFoundError: If ``.roebuck/profile.json`` does not exist.
        RuntimeError: If the profile file cannot be parsed.
    """
    if not _PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"{_PROFILE_PATH} not found. "
            "Run `roebuck profile capture` to create a profile first."
        )
    try:
        profile = ProjectProfile.model_validate_json(_PROFILE_PATH.read_text())
    except Exception as e:
        raise RuntimeError(f"Failed to parse {_PROFILE_PATH}: {e}") from e

    today = datetime.now(timezone.utc).date()
    sha8 = profile.captured_commit[:8]
    filename = f"project-profile-{today}.md"

    lines: list[str] = [
        f"> Generated by Roebuck from profile captured on "
        f"{profile.captured_at.strftime('%Y-%m-%d')} at commit {sha8}. "
        f"Review before committing as a spec.",
        "",
        "# Project Profile",
        "",
        "## Summary",
        "",
        profile.project_summary,
        "",
        "## Architecture Notes",
        "",
        profile.architecture_notes,
        "",
    ]

    if profile.public_modules:
        lines += ["## Public Modules", "", "| Module | Purpose |", "| --- | --- |"]
        for mod in profile.public_modules:
            lines.append(f"| `{mod.path}` | {mod.purpose} |")
        lines.append("")

    if profile.public_interfaces:
        lines += [
            "## Public Interfaces",
            "",
            "| Name | Kind | Signature | Module |",
            "| --- | --- | --- | --- |",
        ]
        for iface in profile.public_interfaces:
            sig = iface.signature.replace("|", r"\|")
            lines.append(f"| `{iface.name}` | {iface.kind} | `{sig}` | `{iface.module}` |")
        lines.append("")

    if profile.data_models:
        lines += [
            "## Data Models",
            "",
            "| Name | Fields | Module |",
            "| --- | --- | --- |",
        ]
        for dm in profile.data_models:
            lines.append(f"| `{dm.name}` | {dm.fields_summary} | `{dm.module}` |")
        lines.append("")

    if profile.external_dependencies:
        lines += ["## External Dependencies", ""]
        for dep in profile.external_dependencies:
            lines.append(f"- {dep}")
        lines.append("")

    output_dir = cfg.reports.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / filename
    out_path.write_text("\n".join(lines))
    return out_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _collision_check(profile_path: Path, force: bool) -> bool:
    """Return True if capture should proceed; False if it should be aborted.

    Prints a warning and returns False when the file exists, was not written
    by Roebuck (no ``captured_at`` key), and ``force`` is False.

    Args:
        profile_path: Path to the profile JSON file.
        force: When True, always returns True regardless of file state.
    """
    if not profile_path.exists() or force:
        return True
    try:
        existing = json.loads(profile_path.read_text())
        if "captured_at" not in existing:
            print(
                f"Warning: {profile_path} exists but does not appear to be a "
                "Roebuck profile (missing 'captured_at'). Use --force to overwrite."
            )
            return False
    except (json.JSONDecodeError, OSError):
        print(
            f"Warning: {profile_path} exists but could not be read. "
            "Use --force to overwrite."
        )
        return False
    return True


def _apply_budget(sources: dict[str, str], max_chars: int) -> dict[str, str]:
    """Trim the sources dict to at most ``max_chars`` total characters.

    Files are included in iteration order. The last file that crosses the
    boundary is truncated rather than dropped entirely.

    Args:
        sources: Mapping of file path to content from SpecLoader.
        max_chars: Maximum total characters to include.

    Returns:
        Trimmed mapping — a subset (and possibly truncation) of ``sources``.
    """
    result: dict[str, str] = {}
    remaining = max_chars
    for path, content in sources.items():
        if remaining <= 0:
            break
        chunk = content[:remaining]
        result[path] = chunk
        remaining -= len(chunk)
    return result


def _phase1_extract(
    sources: dict[str, str],
) -> tuple[list[ExtractedInterface], dict[str, str]]:
    """Run Phase 1 deterministic extraction over all fetched source files.

    Files with a registered :class:`~roebuck.extractors.LanguageExtractor`
    are parsed; unmatched files are buffered for Phase 1b.

    Args:
        sources: Fetched source files (path → content).

    Returns:
        A tuple of (ast_interfaces, buffered_sources) where
        ``ast_interfaces`` are the extracted interfaces tagged for
        ``source="ast"`` later, and ``buffered_sources`` are the files
        with no registered extractor.
    """
    ast_interfaces: list[ExtractedInterface] = []
    buffered: dict[str, str] = {}
    for path, content in sources.items():
        extractor = get_extractor(path)
        if extractor is not None:
            ast_interfaces.extend(extractor.extract(content, path))
        else:
            buffered[path] = content
    return ast_interfaces, buffered


def _phase1b_extract(
    buffered: dict[str, str],
    claude: ClaudeClient,
    max_chars: int,
) -> list[ExtractedInterface]:
    """Run Phase 1b Claude extraction for unmatched file types.

    Sends buffered source files to Claude and returns extracted interfaces
    as :class:`~roebuck.extractors.ExtractedInterface` TypedDicts. The
    ``source`` tag is added by the caller.

    Args:
        buffered: Source files with no registered extractor.
        claude: Initialised ClaudeClient.
        max_chars: Character budget passed to the extraction prompt builder.

    Returns:
        List of extracted interfaces as TypedDicts (without ``source`` tag).
    """
    result: ExtractionResult = claude.analyse(
        system=EXTRACTION_SYSTEM_PROMPT,
        user=build_extraction_prompt(buffered, max_chars),
        output_model=ExtractionResult,
    )
    # Convert Pydantic ExtractedInterfaceItem → ExtractedInterface TypedDict
    return [i.model_dump() for i in result.interfaces]


def _get_head_info(gh: GitHubClient) -> tuple[str, str]:
    """Return ``(commit_sha, branch_name)`` for the repository's default branch.

    Falls back to ``("unknown", "unknown")`` if the GitHub API call fails,
    so capture can still proceed without metadata.

    Args:
        gh: Initialised GitHubClient.

    Returns:
        Tuple of (full commit SHA, branch name).
    """
    try:
        default_branch = gh.repo.default_branch
        sha = gh.repo.get_branch(default_branch).commit.sha
        return sha, default_branch
    except Exception:
        logger.warning(
            "Could not determine HEAD commit SHA; "
            "captured_commit and captured_ref will be 'unknown'"
        )
        return "unknown", "unknown"
