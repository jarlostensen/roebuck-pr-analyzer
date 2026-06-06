---
status: proposed
date: 2026-06-05
deciders: Jarl Ostensen
consulted: Claude (design session facilitator)
informed: []
---

# Project Profile Extraction for Spec-Free and Spec-Drift-Aware PR Analysis

## Context and Problem Statement

The PR analyser assesses spec alignment by loading documents matched by `[specs]
patterns`. For teams without formal documentation this dimension is inert: the
analysis produces no alignment output. A second, related problem affects teams that
do have documentation: design documents drift from the actual implementation silently
over time, and the current analyser has no mechanism to detect this. A capability is
needed that provides a meaningful alignment signal for spec-less projects and a
reality-check signal for spec-rich ones, without requiring teams to write or maintain
formal documentation manually.

## Decision Drivers

* FR-001 — PR analysis must cover spec alignment; currently inert for projects with
  no `[specs]` documents
* FR-013 — the system should support additional analyser types as the project evolves
* ADR-0003 — all LLM-structured output must use the JSON schema injection +
  Pydantic validation pipeline
* ADR-0004 — Pydantic is the single source of truth for output schema definition
* ADR-0001 — new commands follow the Typer CLI pattern
* KISS — the simplest solution that satisfies the requirements is preferred;
  lifecycle management commands are deferred until the core loop is validated

## Considered Options

* Option A — Separate profile commands; PR analysis uses stored profile transparently
* Option B — Inline per-PR profile delta extraction, no stored baseline
* Option C — Full lifecycle management with diff and status commands

## Decision Outcome

Chosen option: "Option A — Separate profile commands; PR analysis uses stored
profile transparently", because it delivers all three use cases (substitute spec,
spec-drift detection, retrofit documentation) through explicit, auditable commands
without requiring per-PR extraction overhead, and can be shipped incrementally before
the full lifecycle management of Option C is warranted.

### Positive Consequences

* Teams without formal documentation gain a non-trivial alignment check from the
  first PR after running `roebuck profile capture`
* Spec drift (documentation that no longer matches the code) is surfaced
  automatically in `spec_vs_reality_gaps` when both specs and a profile are present
* Retrofit documentation has a clear generation path (`roebuck profile generate-docs`)
  and an adoption workflow (review, edit, commit, add to `[specs] patterns`)
* The feature is incremental: profile capture can be shipped before generate-docs,
  and before the `spec_vs_reality_gaps` PR enrichment is added
* The profile is version-controlled alongside the code it describes

### Negative Consequences

* Adds a `.roebuck/` directory to every target repository; some teams will find
  this intrusive
* Profile staleness above the hard threshold (`profile.hard_stale_threshold`,
  default 100 commits) silently disables profile enrichment; teams must act on the
  soft-threshold warning before hitting the cutoff or lose the capability until
  they recapture
* A new `[profile]` config section and sampling-pattern configuration adds setup
  friction; users must know which files represent the public-facing surface
* Drift detection (`profile_delta`) is off by default (`enable_drift_detection =
  false`) and requires explicit opt-in after validating on the target codebase;
  the headline use case is not available out of the box
* Profile capture cost is unknown until sampling is tested against real codebases;
  the `max_chars` cap bounds it but an appropriate default requires empirical data
* `profile_delta` and `spec_vs_reality_gaps` always appear in the `PRAnalysisResult`
  JSON schema injected into every PR analysis prompt, even when no profile is
  present; field descriptions instruct Claude to return empty lists in that case,
  but the schema change is permanent and visible to all consumers

## Pros and Cons of the Options

### Option A — Separate profile commands; PR analysis uses stored profile transparently

Two new commands (`roebuck profile capture`, `roebuck profile generate-docs`) manage
a `ProjectProfile` stored in `.roebuck/profile.json`; the PR analyser enriches its
prompt automatically when the file is present.

* Good, because clean separation of concerns: profile lifecycle is explicit and
  auditable independently of PR analysis
* Good, because the stored profile survives between CI runs without external storage
  (it is committed to the repo)
* Good, because generated documentation can be edited and adopted as a spec, closing
  the sanity-check loop without any new infrastructure
* Good, because satisfies FR-013 with two new command types
* Bad, because requires the team to remember to run `roebuck profile capture` and
  commit the result; the profile goes stale if not maintained
* Bad, because adds a `.roebuck/` directory to every target repository

### Option B — Inline per-PR delta extraction, no stored profile

Every PR analysis produces a `PRProfileDelta` alongside the review result, describing
interface changes in that specific PR; no separate capture step and no stored file.

* Good, because no new commands or stored files; no repository pollution
* Good, because each PR report is fully self-contained
* Bad, because per-PR deltas cannot substitute for a full-project reference; there is
  no prior state to compare against without a stored profile, so the spec-free
  alignment use case is not satisfied
* Bad, because conflicts with the single-output `ClaudeClient.analyse()` pattern
  established in ADR-0003; extending to combined output requires architectural change
* Bad, because the retrofit-documentation use case is not supported

### Option C — Full lifecycle management with diff and status commands

A superset of Option A with additional commands (`roebuck profile diff`,
`roebuck profile status`) and automated staleness tracking.

* Good, because addresses the complete use-case surface including explicit diff and
  health reporting
* Bad, because the additional surface area is premature before the core profile
  capture and PR enrichment loop has been validated in practice
* Bad, because `roebuck profile diff` requires a second Claude call to compare
  narrative layers semantically, adding cost and a new class of unreliable output

## More Information

**Design note**: [docs/design/project-profile.md](../design/project-profile.md) —
contains the full schema definition, sampling strategy, staleness warning design,
prompt budget allocation, and the generated-docs adoption workflow.

**Key implementation constraints (updated after design review 2026-06-05):**

- The narrative layer (`project_summary`, `architecture_notes`) is for human
  consumption only. Drift detection runs on structured fields exclusively.
- `ProjectProfile` Pydantic model pre-defines all fields; Claude fills what applies
  and leaves inapplicable fields as empty lists. Claude does not invent new fields.
- `profile_version: int = 1` is included in the model; increment on breaking schema
  changes to enable forward-compatible reads and clear error messages.
- `captured_ref` (branch/tag name) is stored alongside `captured_commit` (SHA) as a
  fallback for SHA-reachability failures caused by rebase or force-push workflows.
- Staleness check uses a single `repo.compare(base=captured_commit, head="HEAD")` API
  call placed after the existing rate-limit pre-check. Soft threshold (default 20
  commits): warning in report body and stderr, profile still used. Hard threshold
  (default 100 commits): profile excluded from the prompt entirely with a prominent
  warning. On `GithubException 404` (unreachable SHA), falls back to `captured_ref`;
  if that also fails, staleness check is skipped and profile is still used.
- Budget allocation is sequential: diff (MAX_DIFF_CHARS) → specs
  (MAX_SPEC_CHARS_TOTAL) → profile (MAX_PROFILE_CHARS). The diff is never truncated
  to make room for the profile.
- `profile_delta` and `spec_vs_reality_gaps` use `default_factory=list` with
  `Field(description=...)` annotations that instruct Claude to return empty lists
  when the preconditions are not met. They always appear in the injected JSON schema.
- The system prompt instruction for `spec_vs_reality_gaps` is appended
  conditionally — only when both spec files and a profile are loaded at call time.
- `profile_delta` is gated by `profile.enable_drift_detection = false` (default off).
  When enabled, drift comparison runs only on `source: "ast"` interface entries
  (deterministic, from language-specific extractors); `source: "claude"` entries are
  excluded unconditionally. Enable only after empirical validation on the target
  codebase. See ADR-0008 for the extractor plugin design.
- `profile capture` warns and exits if `.roebuck/profile.json` exists without a
  `captured_at` key (not written by Roebuck). `--force` overrides.
- `generate-docs` output goes to `reports.output_dir` (consistent with FR-006), not
  a hardcoded `docs/generated/` path.
- Profile capture fetches from GitHub HEAD via the API (uses SpecLoader); local-only
  use is not supported. Requires `github.token` and `github.repo` in config.
- Profile capture requires an explicit `[profile]` section in `config.toml` with
  `patterns` and `max_chars`. If absent, the command exits with a warning.
- When generated documentation is edited and adopted as a spec, it becomes a
  human-authored spec. The profile remains the implementation-reality source; the
  adopted doc represents stated intent. Divergence surfaces in `spec_vs_reality_gaps`.

**Related ADRs:**
- [ADR-0008](ADR-0008-language-extractor-plugins.md) — language-specific extraction
  plugins; defines the `LanguageExtractor` Protocol, two-phase capture, and
  `source: "ast" | "claude"` tagging that makes `profile_delta` reliable for Python
- [ADR-0003](ADR-0003-llm-output-strategy.md) — JSON schema injection pipeline that
  all new structured output must follow
- [ADR-0004](ADR-0004-pydantic-config-and-output.md) — Pydantic as the single source
  of truth for schema definition
- [ADR-0005](ADR-0005-two-tier-model-pattern.md) — dataclasses for raw input data,
  Pydantic for LLM output; `ProjectProfile` follows the Pydantic side of this split
