# Design: Project Profile — API Surface Extraction and Spec-Free Alignment

Date: 2026-06-05
Status: Draft

---

## Problem

The PR analyser ([FR-001](../requirements.md)) assesses spec alignment by loading project
documents matched by `[specs] patterns`. For teams without formal documentation —
early-stage, high-velocity, small teams — this dimension of the analysis produces no
output. The alignment check is inert.

A second, related problem affects teams that *do* have documentation: design documents
drift from the actual implementation over time without anyone noticing. The existing
analyser checks PRs against specs but cannot detect that the spec itself no longer
describes what the code does.

The capability being designed addresses both:

1. **Substitute spec** — for spec-less projects, extract a structured description of
   the codebase (the *project profile*) and use it as an implicit reference for PR
   alignment checks.

2. **Reality check** — for spec-rich projects, compare the stored profile against the
   human-authored specs during PR analysis, surfacing gaps between documented intent
   and actual behaviour.

3. **Retrofit documentation** — materialise the stored profile as a human-readable
   Markdown draft that the team can review, edit, and commit as a first-generation spec.
   Once committed and added to `[specs] patterns`, the generated doc enters the existing
   spec-alignment loop.

4. **Sanity-check loop** — after a team adopts generated documentation as a spec,
   future PR runs validate the codebase against it. The team can see whether the code
   still does what they said it should. `roebuck profile capture` can be re-run to
   surface new drift.

---

## Constraints

- The tool operates on arbitrary GitHub repositories with no assumed tech stack.
  Profile extraction defaults to Claude for unrecognised file types; language-specific
  AST extractors are used where available (Python built-in, others via the plugin
  protocol — see "Plugin Architecture" section below).
- Persisted profile data must survive between CI runs. A local-only file is
  insufficient for GitHub Actions use. Committing `.roebuck/profile.json` to the
  target repository is the chosen persistence mechanism.
- Any new structured output must use the Pydantic → `ClaudeClient.analyse()` pipeline
  established in ADR-0003 and ADR-0004.
- New commands follow the Typer CLI pattern from ADR-0001.
- The narrative component of the profile is for human consumption only.
  Automated comparison and drift detection run on structured fields exclusively
  (narrative text diffs are too noisy to be reliable).
- Profile capture fetches file contents via `SpecLoader`, which calls the GitHub REST
  API (`repo.get_git_tree` + `repo.get_contents`). It reads the repository's HEAD
  commit on GitHub, not a local working tree. Local-only or offline use is not
  supported; a configured `github.token` and `github.repo` are always required.
- Prompt budget for PR analysis already has `MAX_DIFF_CHARS` and `MAX_SPEC_CHARS_TOTAL`
  caps. Adding a profile introduces a third budget (`MAX_PROFILE_CHARS`). Allocation is
  sequential: the diff is filled first (up to `MAX_DIFF_CHARS`), then spec files (up to
  `MAX_SPEC_CHARS_TOTAL`), then the profile (up to `MAX_PROFILE_CHARS` or whatever token
  headroom remains). The diff is never truncated to make room for the profile.

---

## Options considered

### Option A: Separate profile commands; PR analysis uses profile transparently (chosen)

`roebuck profile capture` extracts a `ProjectProfile` and stores it to
`.roebuck/profile.json`. `roebuck profile generate-docs` materialises it as a Markdown
draft. The PR analyser enriches its prompt automatically when the profile is present.

Chosen because: clean separation of concerns; profile lifecycle is explicit and auditable;
generated docs can be edited and adopted as specs; the feature can be delivered
incrementally.

### Option B: Inline delta extraction per PR, no stored profile

Every PR analysis produces a `PRProfileDelta` alongside the review result, describing
interface changes in that PR. No separate capture step.

Rejected because: per-PR deltas cannot substitute for a full-project reference when
no prior state exists; conflicts with the single-output `ClaudeClient.analyse()`
pattern (ADR-0003); does not support the retrofit-documentation or spec-vs-reality
use cases.

### Option C: Full lifecycle management with diff/status commands

A superset of Option A with additional commands (`roebuck profile diff`,
`roebuck profile status`) and richer staleness tracking.

Deferred: Option A delivers the core loop; lifecycle management commands can be added
once the profile schema and capture strategy are validated in practice.

---

## Decision

Implement Option A as a new `profile` command group with two subcommands:

```
roebuck profile capture          extract and store the project profile
roebuck profile generate-docs    materialise stored profile as Markdown draft
```

### Profile schema

The `ProjectProfile` Pydantic model has two layers:

**Narrative layer** (human-readable, not used for automated comparison):
- `project_summary` — one paragraph describing the project's purpose and domain
- `architecture_notes` — key architectural patterns Claude observes (e.g. layered
  architecture, event-driven, monolith vs. services)

**Structured layer** (used for drift detection and PR prompt enrichment):
- `public_modules` — list of `{path, purpose}` entries for the main source modules
- `public_interfaces` — list of `{name, kind, signature, module, source}` entries
  for the named interfaces. `signature` is a canonical, deterministic string — how
  that string is produced depends on `source`:
  - `source: "ast"` — produced by a language-specific AST extractor (e.g.
    `PythonExtractor`). The extractor decides the canonical form; for Python this is
    the full type-annotated signature as written in source
    (`def charge(amount: Decimal, currency: str) -> Receipt`). Exact-match drift
    comparison is reliable for these entries.
  - `source: "claude"` — produced by the Claude fallback path when no extractor
    matches the file type. Claude is instructed to use the most compact unambiguous
    form for the paradigm (REST: `POST /payments/{id}/refund (amount?)`), but
    cross-run consistency is not guaranteed. Drift comparison is skipped for these
    entries regardless of the `enable_drift_detection` flag.
  The `source` field is added by the capture orchestrator, not by the extractor
  protocol itself.
- `data_models` — list of `{name, fields_summary, module}` entries for key data
  structures
- `external_dependencies` — list of notable external contracts this project depends on
- `profile_version` — integer schema version, always `1` for this design; incremented
  when the model schema changes in a breaking way
- `captured_at` — ISO-8601 timestamp
- `captured_commit` — full SHA of the HEAD commit at capture time
- `captured_ref` — branch or tag name at the time of capture (used as a fallback if
  `captured_commit` is no longer reachable due to rebase or force-push)

Claude fills whatever fields apply. Inapplicable fields are empty lists. The schema
is stable and pre-defined in the Pydantic model; Claude does not invent new fields.

### Capture sampling strategy

Profile capture sends a representative sample of the codebase, not the full source.
A new `[profile]` section in `config.toml` configures which files to sample:

```toml
[profile]
patterns = ["src/**/*.py", "src/**/*.ts", "api/**/*.py"]
max_chars = 40000
```

Files matching `patterns` are concatenated (respecting `max_chars`) and sent to
Claude for extraction. This reuses the existing `SpecLoader` mechanism and keeps the
sampling strategy explicit and user-controlled.

If `[profile]` is absent, a warning is printed and the command exits without
capturing — there is no implicit fallback that might produce a misleading profile.

`profile capture` fetches via the GitHub API (HEAD commit of the configured repo),
not from the local filesystem. It requires network access and a valid `github.token`
with `contents: read` scope.

### Staleness and warnings

The profile stores `captured_at`, `captured_commit`, and `captured_ref`. The PR
analyser checks staleness via a single GitHub API call:

```
ahead_by = repo.compare(base=captured_commit, head="HEAD").ahead_by
```

This is one REST call (`GET /repos/{owner}/{repo}/compare/{base}...{head}`) and
returns the number of commits between the capture SHA and current HEAD. It is placed
after the existing rate-limit pre-check in `GitHubClient` so it counts against the
same budget as the rest of the PR analysis calls.

**SHA reachability fallback**: if `repo.compare()` raises `GithubException` (404 —
SHA not reachable, common on force-push or rebase workflows), the staleness check
falls back to comparing against `captured_ref`. If that also fails, the staleness
check is skipped entirely with a warning logged: the profile is still used (it is
not discarded because of an unreachable SHA), but no commit-count staleness signal
is available.

**Soft threshold** (`profile.stale_commit_threshold`, default 20): if `ahead_by`
exceeds this value, a staleness warning is prepended to the PR report body and
printed to stderr. The profile is still used for analysis.

**Hard threshold** (`profile.hard_stale_threshold`, default 100): if `ahead_by`
exceeds this value, the profile is excluded from the prompt entirely. The PR report
includes a prominent warning explaining why profile enrichment was skipped and
prompting a recapture. This prevents misleading alignment checks from a profile that
is too far behind HEAD to be meaningful.

The warning (soft or hard) always appears in the report body (for archival) and on
stderr. It includes:
- Profile age in days
- Number of commits since capture (`ahead_by`)
- The `captured_ref` for context
- A prompt to run `roebuck profile capture`

### PR analysis enrichment

When `.roebuck/profile.json` exists and has not exceeded the hard staleness threshold:

1. The profile's structured fields are injected into the PR user prompt after spec
   files, within `MAX_PROFILE_CHARS`. Budget is allocated sequentially: diff first
   (up to `MAX_DIFF_CHARS`), then specs (up to `MAX_SPEC_CHARS_TOTAL`), then the
   profile (up to `MAX_PROFILE_CHARS`). A header distinguishes it from spec files:
   `## Project Profile (captured {captured_at}, commit {captured_commit[:8]})`.

2. When both specs and profile are present, the system prompt is extended with a
   conditional instruction (only appended when both sources are loaded, not always):
   "The Project Profile describes the current implementation. Where the provided
   specification documents appear to diverge from it, list those gaps in
   `spec_vs_reality_gaps`."

3. `PRAnalysisResult` gains two new fields:

   ```python
   profile_delta: Annotated[
       list[str],
       Field(
           default_factory=list,
           description=(
               "Interfaces added, removed, or changed by this PR relative to the "
               "stored project profile. Return an empty list if no project profile "
               "was provided or if drift detection is disabled."
           ),
       ),
   ]
   spec_vs_reality_gaps: Annotated[
       list[str],
       Field(
           default_factory=list,
           description=(
               "Gaps between the provided specification documents and the project "
               "profile's description of current behaviour. Return an empty list "
               "if only one source (specs or profile) is present."
           ),
       ),
   ]
   ```

   Both fields always appear in the JSON schema injected by `ClaudeClient.analyse()`
   (since the schema is derived from the model class, not the call site). The field
   descriptions guide Claude to return empty lists when the conditions for population
   are not met, keeping output predictable for existing consumers.

   Existing consumers will see these new fields as empty lists in all current PR
   reports — they are backwards-compatible additions.

### Generated documentation

`roebuck profile generate-docs` writes its output to the configured `reports.output_dir`
(default `./reports`), consistent with FR-006. The filename is
`project-profile-<YYYY-MM-DD>.md`. The file:

- Begins with a provenance header: "Generated by Roebuck from profile captured on
  {date} at commit {sha}. Review before committing as a spec."
- Contains sections derived from both the narrative and structured layers.
- Is not automatically added to `[specs] patterns`. The team must explicitly add it
  after review.

Once the team edits and commits the generated doc and adds it to `[specs] patterns`,
it becomes a human-authored spec like any other. The PR analyser treats it as a spec,
not as a generated file. If the profile and the edited doc later diverge (because the
team changed the code without updating the doc, or vice versa), the
`spec_vs_reality_gaps` field surfaces the discrepancy.

### Collision detection and idempotency

Before writing `.roebuck/profile.json`, `profile capture` checks whether the file
already exists. If it does and does not contain a `captured_at` key (i.e. it was not
written by Roebuck), the command prints a warning and exits without overwriting:

```
Warning: .roebuck/profile.json exists but does not appear to be a Roebuck profile.
Use --force to overwrite.
```

`--force` bypasses this check. When the file was previously written by Roebuck (has
`captured_at`), the command overwrites silently — this is the normal update path.

### Drift detection reliability and opt-in gating

`profile_delta` population is gated behind a config flag:

```toml
[profile]
enable_drift_detection = false   # default; set true after validating on your codebase
```

When `false`, `profile_delta` is always returned as an empty list. The field still
appears in the output schema and in every PR report; it is simply empty.

When `true`, drift detection runs only on `source: "ast"` entries. Entries with
`source: "claude"` are always excluded from comparison because cross-run consistency
of Claude-produced signatures is not guaranteed even with constrained format
instructions. This is an automatic per-entry decision — no additional configuration
is needed. As more file types gain AST extractors, drift detection coverage grows
without any config change.

The reason for the default-off gate: even AST-produced signatures need empirical
validation on real codebases before teams rely on `profile_delta` in CI. Shipping
it as populated output before that validation risks teams learning to ignore it.
Once a team has run profile capture and PR analysis on their codebase and found the
delta output accurate for their primary language, they enable the flag.
`spec_vs_reality_gaps` is not gated (it compares human-authored text, which is more
stable than extracted code signatures) and is populated whenever both sources
are present.

### First-run bootstrapping

When a PR is analysed and no `.roebuck/profile.json` exists, the report includes a
note: "No project profile found. Run `roebuck profile capture` to enable API
stability tracking and spec-free alignment checks."

---

## Plugin Architecture: Language-Specific Extraction

### Problem

The original design populated `public_interfaces` using Claude from raw source text.
Even with constrained format instructions, Claude may paraphrase identical signatures
differently across runs — different whitespace, optional parameter ordering,
abbreviated vs. full type names. This is the root cause of false-positive drift
signals identified in the design review. Deterministic extraction — using a parser
rather than an LLM — eliminates this class of unreliability for supported languages.

### Two-phase capture

Profile capture is split into two phases:

**Phase 1 — Deterministic extraction**: A `LanguageExtractor` parses each source
file and returns a list of `ExtractedInterface` records. This is deterministic code,
not an LLM call. Files are processed one at a time with no size limit. Files with
no matching extractor are buffered for Phase 1b.

**Phase 1b — Claude fallback** (unmatched file types only): Buffered source content
is chunked by `MAX_SOURCE_CHARS_PER_CHUNK`. A Claude call per chunk returns partial
`ExtractedInterface` lists; these are merged with the AST-produced list. Claude
entries are tagged `source: "claude"` by the orchestrator.

**Phase 2 — Claude enrichment** (always): A single Claude call receives the merged
interface list (compact — orders of magnitude smaller than raw source) and returns
purpose descriptions for each interface, module summaries, and the narrative layer.
If the merged list exceeds `MAX_ENRICHMENT_CHARS` (large monorepos with thousands
of public symbols), it is chunked by module; descriptions are merged after all calls.
Chunking Phase 2 is the exception, not the rule.

### Extractor protocol

```python
# src/roebuck/extractors/__init__.py

from typing import Protocol
from typing_extensions import TypedDict


class ExtractedInterface(TypedDict):
    name: str
    kind: str        # "function" | "class" | "method" | "endpoint" | ...
    signature: str   # canonical, deterministic — extractor decides the format
    module: str
    is_public: bool  # extractor decides the definition of "public"


class LanguageExtractor(Protocol):
    extensions: frozenset[str]
    requires_toolchain: bool  # True = needs external binary (Go, libclang, etc.)

    def extract(self, source: str, path: str) -> list[ExtractedInterface]:
        """Extract public interfaces from a single source file."""
        ...
```

`source` (the `"ast"` / `"claude"` tag) is not part of `ExtractedInterface` as
returned by the protocol — it is added by the capture orchestrator when merging.
The protocol is extraction-only; tagging is the orchestrator's responsibility.

### Python extractor

`src/roebuck/extractors/python.py` uses the `ast` standard library module — zero
new dependencies. It visits `FunctionDef`, `AsyncFunctionDef`, and `ClassDef` nodes
to produce fully type-annotated signatures reconstructed from the AST.

Initial "public" definition: module-level names that do not begin with `_`; class
methods follow the same rule within the class body. This is intentionally simple.
The Python extractor's definition of "public" can be refined independently of the
protocol without breaking anything.

`PythonExtractor.requires_toolchain = False`.

### Extractor registry

```python
# src/roebuck/extractors/registry.py

from roebuck.extractors import LanguageExtractor
from roebuck.extractors.python import PythonExtractor

_REGISTRY: dict[str, LanguageExtractor] = {
    ext: PythonExtractor() for ext in PythonExtractor.extensions
}


def get_extractor(path: str) -> LanguageExtractor | None:
    """Return the registered extractor for this file's extension, or None."""
    suffix = path.rsplit(".", 1)[-1] if "." in path else ""
    return _REGISTRY.get(f".{suffix}")
```

The registry is a plain dict. No entry-point discovery, no configuration. Adding a
second language extractor means adding an entry to `_REGISTRY`. External plugin
discovery is explicitly deferred to a future ADR once the protocol is proven stable
with two concrete extractors.

### Codebase structure

```
src/roebuck/
  extractors/
    __init__.py      # ExtractedInterface TypedDict, LanguageExtractor Protocol
    python.py        # PythonExtractor — ast stdlib, requires_toolchain=False
    registry.py      # get_extractor(path: str) -> LanguageExtractor | None
```

### CI and toolchain

If a future extractor sets `requires_toolchain = True`, the profile capture command
checks whether the toolchain is available before calling `extract()`. If not, it
warns and falls back to Claude-only extraction for those files. The toolchain check,
and documenting what is needed in CI, is the extractor author's responsibility.

---

## Consequences

**What this makes easier:**

- Teams without formal documentation get a non-trivial alignment check from the first
  PR after running `roebuck profile capture`.
- Spec drift (documentation that no longer matches the code) is surfaced automatically
  without requiring human review of the spec.
- Retrofit documentation has a clear generation path and adoption workflow.
- The feature is incremental: `profile capture` can be shipped before `generate-docs`,
  and before the `spec_vs_reality_gaps` enrichment is added to PR analysis.

**What this makes harder:**

- The project adds a `.roebuck/` directory to every target repository — some teams
  will find this intrusive. There is no hosted alternative at this stage.
- Profile staleness is a constant maintenance pressure. The soft warning and hard
  cutoff thresholds are the primary mitigations; teams that ignore the warnings will
  eventually have profile enrichment silently disabled at the hard cutoff. This is
  the correct failure mode (no misleading analysis is better than wrong analysis) but
  it requires the team to act on the warning.
- The `[profile] patterns` sampling strategy requires the user to know which files
  represent the public-facing surface. For large or unfamiliar codebases this
  configuration step is non-trivial.
- Drift detection (`profile_delta`) is off by default. Teams must explicitly enable
  it after validating on their codebase. This is intentional but means the headline
  use case requires extra setup.

**Risks that remain:**

- **Sampling inconsistency**: if `[profile] patterns` is not configured carefully,
  the captured profile may miss key interfaces or over-represent boilerplate. A future
  `profile suggest-patterns` command (using churn data to identify high-signal files)
  could reduce this friction.
- **Two sources of truth once generated docs are adopted**: when a team edits a
  generated doc and adds it to `[specs] patterns`, the profile (implementation reality)
  and the spec (stated intent) can diverge. The convention — profile describes what
  the code does; spec describes what it should do — must be communicated clearly in
  CLI output and documentation, otherwise teams are unsure which to update when they
  diverge.
- **Profile capture cost is empirically unknown**: the `max_chars` cap bounds token
  usage but the right default value for different codebase sizes has not been tested.
  The initial `40000` is a conservative estimate; it should be validated on at least
  two real codebases before a production default is set.
- **Claude fallback signatures remain non-deterministic**: for file types with no
  registered extractor, `source: "claude"` entries are excluded from drift comparison
  automatically. Coverage grows as more AST extractors are added, but teams with
  predominantly non-Python codebases get limited deterministic drift detection initially.
- **Python extractor "public" definition is initially narrow**: module-level
  non-underscore names will miss `__all__`-based exports and re-exports from
  `__init__.py`. The definition can be refined without protocol changes, but early
  adopters may see incomplete `public_interfaces` until it is improved.
