# Roebuck — Task Plan

_Last updated: 2026-06-05._

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

### TASK-007: Add explicit analysis questions to `release.py` user prompt

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

### TASK-008: Add risk calibration and spec-alignment definitions to `pr.py` and `release.py`

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

### TASK-009: Fix `churn.py` prompt — surface thresholds, ranking criterion, keyword caveat

**File**: `src/roebuck/prompts/churn.py`
**Requirement**: [FR-004](requirements.md)
**Priority**: Medium

Three weaknesses in the churn user prompt:

1. **Ranking criterion unknown**: The top-`MAX_FILES` slice is sent but the model is never told how the files are ranked. Add a note: files are sorted by total commit count descending; the model should not assume lower-ranked files are low-risk.
2. **Config thresholds not surfaced**: `ChurnConfig.coordination_risk_min_authors` (default 5) and `coordination_risk_min_defect_ratio` (default 0.3) are computed in the analyser but never passed to the prompt. Pass them through `build_user_prompt` and include them as: *"Files with ≥N unique authors and ≥R% defect ratio are operator-defined coordination-risk candidates."*
3. **Keyword false-positive caveat missing**: The defect-keyword detection is heuristic ("fix" matches "prefix"). Add a note to the user prompt: *"Defect classification is keyword-based and may have false positives; treat defect ratios as signals, not ground truth."*

**Acceptance**: All three additions appear in the generated user prompt string; `build_user_prompt` signature updated to accept `coordination_risk_min_authors: int` and `coordination_risk_min_defect_ratio: float`; call sites updated; `pytest tests/test_prompts.py` passes.

---

### TASK-010: Fix `file_history.py` prompt — today anchor, stability-trend definition, emoji removal

**File**: `src/roebuck/prompts/file_history.py`
**Requirement**: [FR-002](requirements.md)
**Priority**: Medium

Three issues:

1. **No today anchor**: The commit table includes dates but the prompt never states the current date. The model cannot distinguish "recent" from "historical" without a reference point. Pass `today: date` into `build_user_prompt` and include it as `## Analysis date: {today}` near the top.
2. **Stability trend not defined**: `FileHistoryResult.stability_trend` is `"improving"|"stable"|"degrading"` but no definition is provided. Add to system prompt: *"improving = defect-related commit frequency decreasing over the most recent third of the history; degrading = increasing; stable = no clear trend."*
3. **Emoji in table data**: The Defect? column uses `"⚠️ yes"` (Unicode emoji), which can break in encoding-unaware pipelines and is inconsistent with the project's no-Unicode rule. Replace with `"yes *"` or plain `"yes"`.

**Acceptance**: Generated user prompt includes today's date; system prompt contains stability-trend definition; no emoji characters appear in the prompt output; `pytest tests/test_prompts.py` passes.

---

### TASK-011: Extract shared `_context_section` to a prompt utilities module

**Files**: `src/roebuck/prompts/pr.py`, `src/roebuck/prompts/churn.py`, `src/roebuck/prompts/file_history.py`, `src/roebuck/prompts/release.py`, `src/roebuck/prompts/_shared.py` (new)
**Requirement**: [FR-001](requirements.md), [FR-002](requirements.md), [FR-003](requirements.md), [FR-004](requirements.md)
**Priority**: Low

`_context_section(context: ContextConfig) -> str` is copy-pasted identically in all four prompt modules. Create `src/roebuck/prompts/_shared.py` containing the single canonical implementation and update all four modules to import from it.

No functional change — this is a maintenance fix to prevent the four copies from silently diverging.

**Acceptance**: `_shared.py` contains the function; no prompt module defines its own `_context_section`; `pytest` continues to pass with no changes to test logic.
