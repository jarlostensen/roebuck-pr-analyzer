# Roebuck — Task Plan

_Last updated: 2026-06-06._

---

## Project

- **Repo**: local (not yet a git repository — `git init` recommended before implementation)
- **VCS**: git / GitHub (confirmed)
- **Branching strategy**: feature branch per task (`feature/TASK-NNN-short-description`)
- **Test command**: `pytest`
- **Requirements**: [docs/requirements.md](requirements.md)
- **Architecture**: [docs/architecture.md](architecture.md)
- **ADRs**: [docs/adr/](adr/)

---

## Tasks

### TASK-001: Replace informal string enum fields with `Literal` types in LLM output models

**File**: `src/roebuck/models.py`
**Requirement**: ADR-0004 (con: invalid enum values from Claude pass validation silently)
**Priority**: Medium

Fields such as `risk_level: str` accept any string from Claude. Using `Literal["low", "medium", "high", "critical"]` causes Pydantic to reject unexpected values immediately, surfacing prompt or model regressions early.

Affects: `PRAnalysisResult.risk_level`, `PRAnalysisResult.spec_alignment`, `PRAnalysisResult.test_adequacy`, `FileHistoryResult.stability_trend`, `ReleaseAnalysisResult.risk_level`.

---

### TASK-002: Emit partial churn report with warning when rate limit is hit mid-run

**Files**: `src/roebuck/github_client.py`, `src/roebuck/analysers/churn.py`
**Requirement**: [FR-012](requirements.md)
**Priority**: High

Currently `get_churn_data()` raises `RuntimeError` if a rate limit exception occurs mid-iteration. The mid-run periodic check already breaks out of the loop with partial data — this behaviour should be formalised:

1. `get_churn_data()` returns whatever entries have been collected so far, plus a boolean or sentinel indicating truncation.
2. `analysers/churn.py` detects truncation and prepends a warning section to the report rather than propagating an error.

---

### TASK-003: Write unit tests for `SpecLoader`

**File**: `tests/test_spec_loader.py`
**Requirement**: [FR-005](requirements.md)
**Priority**: Medium

`SpecLoader` is untested. Tests should cover:

- Files matching one or more glob patterns are returned
- Files not matching any pattern are excluded
- Content is fetched concurrently (verify all matched paths appear in result)
- A file that raises on `get_contents()` is silently skipped
- A `list` response from `get_contents()` (directory) is skipped
- `get_git_tree()` failure raises `RuntimeError`

---

### TASK-004: Write unit tests for analyser orchestrators

**Files**: `tests/test_analysers.py` (or per-analyser files)
**Requirement**: [FR-001](requirements.md), [FR-002](requirements.md), [FR-003](requirements.md), [FR-004](requirements.md)
**Priority**: Medium

The four `run()` functions in `analysers/` are untested. Each wires together `GitHubClient`, `ClaudeClient`, and `MarkdownReportWriter`. Tests should mock all three and verify:

- `run()` returns a `Path` pointing to an existing file
- The correct GitHub fetch method is called with the right arguments
- The correct prompt builder is called
- `ClaudeClient.analyse()` is called with the correct `output_model`
- On `RuntimeError` from GitHub or Claude, the error propagates (not swallowed)

For the churn analyser additionally:
- Empty entries result in a minimal report without calling Claude (existing behaviour)
- Partial data (TASK-002) produces a report with a warning section

---

### TASK-005: Write tests for CLI command dispatch

**File**: `tests/test_cli.py`
**Requirement**: [FR-008](requirements.md), [FR-009](requirements.md)
**Priority**: Low

Use `typer.testing.CliRunner` to test:

- Each command (`analyse pr`, `analyse file`, `analyse release`, `report churn`) exits 0 on success (mock analyser `run()`)
- Missing config file exits 1 with an error message
- `--config` flag routes to the correct path
- Invalid config exits 1 with a validation error message

---

### ~~TASK-006: Add JSON output schema to all four system prompts~~ — RESOLVED (pre-existing)

`ClaudeClient.analyse()` already appends the full `model_json_schema()` output and a JSON-only instruction to every system prompt at runtime (`src/roebuck/claude_client.py:26-32`). No changes to individual prompt modules are required. Identified during implementation review on 2026-06-05.

---

### ~~TASK-007: Add explicit analysis questions to `release.py` user prompt~~ — COMPLETED 2026-06-05

**File**: `src/roebuck/prompts/release.py`
**Requirement**: [FR-003](requirements.md)
**Priority**: High

`build_user_prompt` in `release.py` currently ends after the diff block with no instructions — unlike `churn.py`, which closes with a bulleted task list. The model has no explicit questions to answer.

Add a closing section to the user prompt that asks:
- What is the overall deployment risk level (low / medium / high / critical)?
- Are there breaking changes to public APIs, DB schemas, or configuration?
- Which files carry the highest deployment risk and why?
- What specific actions should be taken before deploying this release?

Additionally, enumerate the breaking-change taxonomy in the system prompt (API signature changes, removed endpoints, DB migrations, env-var additions, dependency major-version bumps, config schema changes), because "identify breaking changes" is too vague without domain enumeration.

**Acceptance**: The user prompt string ends with a structured question block; the system prompt names at least five categories of breaking change; `pytest tests/test_prompts.py::test_release_prompt_has_analysis_questions` passes.

---

### ~~TASK-008: Add risk calibration and spec-alignment definitions to `pr.py` and `release.py`~~ — COMPLETED 2026-06-05

**Files**: `src/roebuck/prompts/pr.py`, `src/roebuck/prompts/release.py`
**Requirement**: [FR-001](requirements.md), [FR-003](requirements.md)
**Priority**: High

Both prompts produce `risk_level` but never define what distinguishes each level. Without calibration the model's output is non-reproducible. `pr.py` additionally produces `spec_alignment` with no definition of what constitutes "partial" vs "misaligned".

Add to `pr.py` system prompt:
- Risk calibration: `critical` = data loss or security exposure; `high` = likely regression or incorrect behaviour; `medium` = non-obvious side effects or coverage gaps; `low` = cosmetic, style, or trivially reversible.
- Spec-alignment calibration: `aligned` = all changed areas are covered by specs; `partial` = some changed areas lack spec coverage; `misaligned` = changes contradict stated specs; `no_specs` = no spec files were provided.

Add to `release.py` system prompt the same risk-level calibration.

Also add to `pr.py` system prompt the explicit review dimensions currently missing: security vulnerabilities, performance implications, error handling, and API/interface breaking changes.

**Acceptance**: All four calibration definitions appear in each respective system prompt string; `pytest tests/test_prompts.py` passes.

---

### ~~TASK-009: Fix `churn.py` prompt — surface thresholds, ranking criterion, keyword caveat~~ — COMPLETED 2026-06-05

**File**: `src/roebuck/prompts/churn.py`
**Requirement**: [FR-004](requirements.md)
**Priority**: Medium

Three weaknesses in the churn user prompt:

1. **Ranking criterion unknown**: The top-`MAX_FILES` slice is sent but the model is never told how the files are ranked. Add a note: files are sorted by total commit count descending; the model should not assume lower-ranked files are low-risk.
2. **Config thresholds not surfaced**: `ChurnConfig.coordination_risk_min_authors` (default 5) and `coordination_risk_min_defect_ratio` (default 0.3) are computed in the analyser but never passed to the prompt. Pass them through `build_user_prompt` and include them as: *"Files with ≥N unique authors and ≥R% defect ratio are operator-defined coordination-risk candidates."*
3. **Keyword false-positive caveat missing**: The defect-keyword detection is heuristic ("fix" matches "prefix"). Add a note to the user prompt: *"Defect classification is keyword-based and may have false positives; treat defect ratios as signals, not ground truth."*

**Acceptance**: All three additions appear in the generated user prompt string; `build_user_prompt` signature updated to accept `coordination_risk_min_authors: int` and `coordination_risk_min_defect_ratio: float`; call sites updated; `pytest tests/test_prompts.py` passes.

---

### ~~TASK-010: Fix `file_history.py` prompt — today anchor, stability-trend definition, emoji removal~~ — COMPLETED 2026-06-05

**File**: `src/roebuck/prompts/file_history.py`
**Requirement**: [FR-002](requirements.md)
**Priority**: Medium

Three issues:

1. **No today anchor**: The commit table includes dates but the prompt never states the current date. The model cannot distinguish "recent" from "historical" without a reference point. Pass `today: date` into `build_user_prompt` and include it as `## Analysis date: {today}` near the top.
2. **Stability trend not defined**: `FileHistoryResult.stability_trend` is `"improving"|"stable"|"degrading"` but no definition is provided. Add to system prompt: *"improving = defect-related commit frequency decreasing over the most recent third of the history; degrading = increasing; stable = no clear trend."*
3. **Emoji in table data**: The Defect? column uses `"⚠️ yes"` (Unicode emoji), which can break in encoding-unaware pipelines and is inconsistent with the project's no-Unicode rule. Replace with `"yes *"` or plain `"yes"`.

**Acceptance**: Generated user prompt includes today's date; system prompt contains stability-trend definition; no emoji characters appear in the prompt output; `pytest tests/test_prompts.py` passes.

---

### ~~TASK-011: Extract shared `_context_section` to a prompt utilities module~~ — COMPLETED 2026-06-05

**Files**: `src/roebuck/prompts/pr.py`, `src/roebuck/prompts/churn.py`, `src/roebuck/prompts/file_history.py`, `src/roebuck/prompts/release.py`, `src/roebuck/prompts/_shared.py` (new)
**Requirement**: [FR-001](requirements.md), [FR-002](requirements.md), [FR-003](requirements.md), [FR-004](requirements.md)
**Priority**: Low

`_context_section(context: ContextConfig) -> str` is copy-pasted identically in all four prompt modules. Create `src/roebuck/prompts/_shared.py` containing the single canonical implementation and update all four modules to import from it.

No functional change — this is a maintenance fix to prevent the four copies from silently diverging.

**Acceptance**: `_shared.py` contains the function; no prompt module defines its own `_context_section`; `pytest` continues to pass with no changes to test logic.

---

## Phase: Project Profile (ADR-0007, ADR-0008)

Design: [docs/design/project-profile.md](design/project-profile.md).
ADRs: [ADR-0007](adr/ADR-0007-project-profile-extraction.md), [ADR-0008](adr/ADR-0008-language-extractor-plugins.md).

Dependencies between tasks: TASK-012 and TASK-013 have no inter-dependencies and can be
worked in parallel. TASK-014 (extractors) has no dependencies. TASK-015 (prompts) depends
on TASK-012. TASK-016 (capture analyser) depends on TASK-013, TASK-014, TASK-015.
TASK-017 (CLI) depends on TASK-016. TASK-018 (PR enrichment) depends on TASK-012 and
TASK-013. TASK-019 (generate-docs) depends on TASK-012 and TASK-016.

---

### TASK-012: Add `ProjectProfile` Pydantic model and extend `PRAnalysisResult`

**Files**: `src/roebuck/models.py`, `tests/test_models.py`
**Requirements**: FR-013, ADR-0007, ADR-0004
**Priority**: High — blocks TASK-015, TASK-016, TASK-018

Add nested Pydantic models to `models.py`:
- `PublicModule(path: str, purpose: str)`
- `PublicInterface(name: str, kind: str, signature: str, module: str, source: Literal["ast", "claude"], is_public: bool)`
- `DataModel(name: str, fields_summary: str, module: str)`
- `ProjectProfile` with: `profile_version: int = 1`, `project_summary: str`, `architecture_notes: str`,
  `public_modules: list[PublicModule]`, `public_interfaces: list[PublicInterface]`,
  `data_models: list[DataModel]`, `external_dependencies: list[str]`,
  `captured_at: datetime`, `captured_commit: str`, `captured_ref: str`

Extend `PRAnalysisResult` with:
- `profile_delta: list[str]` — `Field(default_factory=list, description="Interfaces added, removed, or changed by this PR relative to the stored project profile. Return an empty list if no project profile was provided or if drift detection is disabled.")`
- `spec_vs_reality_gaps: list[str]` — `Field(default_factory=list, description="Gaps between the provided specification documents and the project profile's description of current behaviour. Return an empty list if only one source (specs or profile) is present.")`

**Acceptance**: `ProjectProfile.model_validate_json(...)` round-trips correctly; `PRAnalysisResult`
new fields default to empty list; existing `pytest tests/test_prompts.py` still passes (schema injection picks up the new fields transparently).

---

### TASK-013: Add `ProfileConfig` to app configuration

**Files**: `src/roebuck/config.py`, `tests/test_config.py`
**Requirements**: FR-013, ADR-0007
**Priority**: High — blocks TASK-016, TASK-018

Add `ProfileConfig` Pydantic model with fields:
- `patterns: list[str]` — glob patterns for source files to sample
- `max_chars: int = Field(default=40000, ge=1000)` — total character budget for sampled source
- `stale_commit_threshold: int = Field(default=20, ge=1)` — soft staleness warning threshold
- `hard_stale_threshold: int = Field(default=100, ge=1)` — hard staleness exclusion threshold
- `enable_drift_detection: bool = False` — gates `profile_delta` population

Add `profile: ProfileConfig | None = None` to `AppConfig`. If the `[profile]` section is absent
from `config.toml`, `cfg.profile` is `None` and all profile features are silently skipped.

**Acceptance**: Config with `[profile]` section loads `ProfileConfig` correctly; config without
`[profile]` section has `cfg.profile is None`; negative `max_chars` raises validation error;
`pytest tests/test_config.py` passes.

---

### TASK-014: Implement `LanguageExtractor` protocol and `PythonExtractor`

**Files**: `src/roebuck/extractors/__init__.py`, `src/roebuck/extractors/python.py`,
`src/roebuck/extractors/registry.py`, `tests/test_extractors.py`
**Requirements**: FR-013, ADR-0008
**Priority**: High — blocks TASK-016

- `src/roebuck/extractors/__init__.py`: define `ExtractedInterface` TypedDict (`name`, `kind`,
  `signature`, `module`, `is_public`) and `LanguageExtractor` Protocol (`extensions: frozenset[str]`,
  `requires_toolchain: bool`, `extract(source: str, path: str) -> list[ExtractedInterface]`)
- `src/roebuck/extractors/python.py`: `PythonExtractor` using `ast` stdlib; `extensions = frozenset({".py"})`; `requires_toolchain = False`; visits module-level `FunctionDef`, `AsyncFunctionDef`, and `ClassDef` nodes; excludes names starting with `_`; reconstructs type-annotated signature strings from the AST
- `src/roebuck/extractors/registry.py`: `get_extractor(path: str) -> LanguageExtractor | None` — plain dict lookup keyed by file extension

Syntax errors in source must not propagate — return empty list and log a warning.

**Acceptance**: `PythonExtractor` extracts `def foo(x: int) -> str: ...` as `signature="def foo(x: int) -> str"`;
private names (`_helper`) are excluded; `get_extractor("main.py")` returns a `PythonExtractor` instance;
`get_extractor("main.go")` returns `None`; syntax errors return empty list; `pytest tests/test_extractors.py` passes.

---

### TASK-015: Write profile prompt builders

**Files**: `src/roebuck/prompts/profile.py`, `tests/test_prompts.py`
**Requirements**: FR-013, ADR-0007, ADR-0003
**Priority**: Medium — blocks TASK-016

Add `src/roebuck/prompts/profile.py` with:
- `EXTRACTION_SYSTEM_PROMPT`: instructs Claude to extract public interfaces as JSON matching the
  `ExtractedInterface` schema; used for Phase 1b (Claude fallback for unmatched file types)
- `build_extraction_prompt(sources: dict[str, str], max_chars: int) -> str`: user prompt with
  concatenated source content (respecting `max_chars`)
- `ENRICHMENT_SYSTEM_PROMPT`: instructs Claude to add `purpose` descriptions to a provided
  interface list and produce `project_summary` and `architecture_notes`
- `build_enrichment_prompt(interfaces: list[ExtractedInterface]) -> str`: user prompt from
  extracted interface list for Phase 2 enrichment

Follow the same module structure as `src/roebuck/prompts/pr.py` (module-level constants, typed builder functions).

**Acceptance**: Both builders return non-empty strings containing their key section headers;
`pytest tests/test_prompts.py` covers both builders; existing prompt tests unaffected.

---

### TASK-016: Implement `profile capture` analyser

**Files**: `src/roebuck/analysers/profile.py`, `tests/test_analysers.py`
**Requirements**: FR-013, ADR-0007, ADR-0008
**Priority**: Medium — blocks TASK-017, TASK-019

Add `capture(cfg: AppConfig, force: bool = False) -> None` to a new `src/roebuck/analysers/profile.py`:

1. Exit with clear message if `cfg.profile is None`
2. Collision check: if `.roebuck/profile.json` exists without `captured_at` key, warn and exit unless `force=True`
3. Fetch matched files via `SpecLoader(cfg.github)` using `cfg.profile.patterns` and `cfg.profile.max_chars`
4. Phase 1: call `get_extractor(path).extract(source, path)` for each file with a matching extractor; buffer unmatched files
5. Phase 1b: if buffered files exist, call Claude with `build_extraction_prompt()` and parse the extraction result; tag these as `source="claude"`; tag Phase 1 results as `source="ast"`
6. Phase 2: call Claude with `build_enrichment_prompt()` on the merged interface list; parse as `ProjectProfile` (ADR-0003 pipeline)
7. Set `profile_version=1`, `captured_at=datetime.now(UTC)`, `captured_commit`, `captured_ref` on the result
8. Write `ProjectProfile.model_dump_json()` to `.roebuck/profile.json`; create `.roebuck/` directory if absent

**Acceptance**: `capture()` writes valid JSON that round-trips through `ProjectProfile.model_validate_json()`;
collision check prevents overwrite without `force=True`; `cfg.profile is None` exits with message;
mocked tests verify Phase 1, 1b, and 2 are called with correct arguments; `pytest tests/test_analysers.py` passes.

---

### TASK-017: Add `profile` CLI command group

**Files**: `src/roebuck/cli.py`, `tests/test_cli.py`
**Requirements**: FR-013, ADR-0001
**Priority**: Medium — required for end-to-end use

Add `profile_app = typer.Typer(help="Manage the project profile.", no_args_is_help=True)` and
`app.add_typer(profile_app, name="profile")`.

Add two subcommands:
- `profile capture [--force] [--config PATH]` — calls `capture(cfg, force=force)`
- `profile generate-docs [--config PATH]` — calls `generate_docs(cfg)`

Follow the existing `_load(config_path, repo)` helper pattern.

**Acceptance**: `roebuck profile --help` lists both subcommands; `CliRunner` tests verify each
command dispatches correctly and exits 0 on success (analyser mocked); missing config exits 1;
`pytest tests/test_cli.py` passes.

---

### TASK-018: Extend PR analysis with profile enrichment and staleness check

**Files**: `src/roebuck/analysers/pr.py`, `src/roebuck/prompts/pr.py`,
`tests/test_analysers.py`, `tests/test_prompts.py`
**Requirements**: FR-001, FR-013, ADR-0007
**Priority**: Medium

In `src/roebuck/analysers/pr.py`:
- After loading specs, attempt to read `.roebuck/profile.json` from CWD; parse as `ProjectProfile`
- Call `repo.compare(base=profile.captured_commit, head="HEAD").ahead_by` for staleness check
- Soft threshold (`cfg.profile.stale_commit_threshold`): prepend warning to report, still use profile
- Hard threshold (`cfg.profile.hard_stale_threshold`): exclude profile, add prominent warning section
- SHA fallback: on `GithubException` 404, retry with `profile.captured_ref`; if that also fails, skip staleness check and still use profile

In `src/roebuck/prompts/pr.py`:
- Add `profile: ProjectProfile | None = None` parameter to `build_user_prompt`
- Inject profile structured fields after specs section, within `MAX_PROFILE_CHARS = 8000`
- Add `spec_vs_reality_gaps` instruction to system prompt only when called with both specs and profile

**Acceptance**: PR analysis with profile present injects profile content into user prompt;
PR analysis without `.roebuck/profile.json` is unchanged; staleness above hard threshold excludes profile;
`profile_delta` is empty when `cfg.profile.enable_drift_detection` is False;
`pytest tests/test_prompts.py` and `tests/test_analysers.py` pass; existing PR tests are unaffected.

---

### TASK-019: Implement `profile generate-docs` command

**Files**: `src/roebuck/analysers/profile.py`, `tests/test_analysers.py`
**Requirements**: FR-013, ADR-0007
**Priority**: Low — standalone; no blockers

Add `generate_docs(cfg: AppConfig) -> Path` to `src/roebuck/analysers/profile.py`:
- Read `.roebuck/profile.json`; exit with clear error if absent or unparseable
- Render a Markdown document:
  - Provenance header: "Generated by Roebuck from profile captured on {date} at commit {sha[:8]}. Review before committing as a spec."
  - Sections: Project Summary, Architecture Notes, Public Modules table, Public Interfaces table, Data Models table, External Dependencies list
- Write to `cfg.reports.output_dir / f"project-profile-{date.today()}.md"` (consistent with FR-006)
- Return the written path

**Acceptance**: Output file contains provenance header and all structured sections; absent profile file
exits with error (non-zero); `pytest tests/test_analysers.py` passes.
