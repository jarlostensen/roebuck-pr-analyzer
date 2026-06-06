---
status: proposed
date: 2026-06-05
deciders: Jarl Ostensen
consulted: Claude (design session facilitator)
informed: []
---

# Language-Specific Extraction Plugins for Project Profile

## Context and Problem Statement

The Project Profile (ADR-0007) stores `public_interfaces` entries that include a
`signature` field. In the base design this field is populated by Claude from raw
source text. Even with constrained format instructions (type-annotated Python
signatures, REST routes), Claude may paraphrase identical signatures differently
across capture runs — different whitespace, optional parameter ordering, abbreviated
vs. full type names. This produces false-positive drift signals when `profile_delta`
is enabled, making the headline use case unreliable before a team has tested it on
their codebase.

A deterministic extraction path is needed: one where code signatures are produced
by a parser, not an LLM, so that the same interface always produces the same
`signature` string across runs, making exact-match drift comparison reliable.

## Decision Drivers

* ADR-0007 identifies `signature` format inconsistency as the root reliability risk
  for `profile_delta`; the design review listed it as a top risk
* FR-013 — the system should support additional analyser types as the project evolves
* KISS — the simplest solution that satisfies the requirements is preferred;
  entry-point discovery and external plugin registries are deferred
* Python is the primary implementation language of Roebuck itself; stdlib-only AST
  parsing via the `ast` module incurs zero new dependencies
* Starting with Python defers the "general problem" — each subsequent language is
  a separate, bounded scope

## Considered Options

* Option A — Protocol-based extractors; Python built-in; Claude fallback for
  unmatched extensions
* Option B — tree-sitter as a universal parser host; all languages share one
  grammar-loading mechanism
* Option C — External config-registered extractors; entry-point discovery for
  third-party plugins

## Decision Outcome

Chosen option: "Option A — Protocol-based extractors; Python built-in; Claude
fallback", because it:
- Delivers deterministic extraction for Python (the most common Roebuck target)
  with zero new dependencies
- Defines a minimal, stable Protocol that future extractors can implement without
  coupling to Roebuck internals
- Defers external plugin discovery until a second concrete language extractor
  validates the protocol and the extension pattern
- Leaves Options B and C explicitly deferred rather than foreclosed

### Positive Consequences

* `"ast"`-sourced `signature` fields are deterministic: exact-match drift comparison
  becomes reliable for Python interfaces without any additional configuration
* `source: "ast"` vs `source: "claude"` tagging lets the drift comparator use a
  per-entry strategy, automatically excluding unreliable Claude-produced entries
  without any user-facing configuration
* Two-phase capture (Phase 1: extractor produces interface list; Phase 2: Claude
  enrichment adds descriptions and narrative) keeps Claude's input compact —
  extracted interface lists are orders of magnitude smaller than raw source,
  reducing token cost and eliminating chunking for typical codebases
* The `extractors/` sub-package makes the extension point explicit and visible;
  adding a Go or C extractor later requires only implementing the Protocol and
  registering it in `registry.py`
* `requires_toolchain: bool` on each extractor allows the capture command to warn
  and fall back to Claude gracefully when CI lacks a required binary

### Negative Consequences

* Initial Python extractor covers only module-level non-underscore-prefixed names;
  `__all__`-based exports and re-exports from `__init__.py` are missed initially.
  The definition evolves independently of the protocol.
* The Claude-only fallback path for unmatched extensions still produces
  `source: "claude"` entries; drift detection for these is silently skipped.
  Teams with non-Python-dominant codebases get limited deterministic coverage until
  further extractors are added.
* Two-phase capture introduces a second Claude call per profile capture (Phase 2
  enrichment). The cost increment is bounded by the extracted interface count,
  not source size, and is small for typical codebases.
* Phase 2 chunking (for very large interface lists) is a new orchestration concern
  with a merge step that must be validated on large real codebases.

## Pros and Cons of the Options

### Option A — Protocol-based extractors; Python built-in; Claude fallback

`LanguageExtractor` Protocol + `ExtractedInterface` TypedDict in
`src/roebuck/extractors/__init__.py`; `PythonExtractor` using `ast` stdlib in
`src/roebuck/extractors/python.py`; plain dict registry in
`src/roebuck/extractors/registry.py`. Claude Phase 2 enrichment receives the
extracted interface list, adds purpose descriptions and narrative.

* Good, because zero new dependencies for the Python extractor
* Good, because minimal Protocol that does not foreclose tree-sitter or entry-point
  discovery later
* Good, because `source: "ast"` tagging fully resolves the `signature` reliability
  risk for Python — the most common Roebuck target language
* Good, because each subsequent language extractor is a bounded, independent problem
* Bad, because only Python is deterministic initially; all other types still use the
  Claude-only path

### Option B — tree-sitter as universal parser host

tree-sitter provides language-agnostic parse-tree access; a single
`TreeSitterExtractor` loads per-language grammar packages.

* Good, because covers many languages from a single implementation pattern
* Bad, because `tree-sitter` is a non-trivial C extension; Python bindings plus
  per-language grammar packages add significant dependency weight and CI complexity
* Bad, because premature — no validated need for multi-language deterministic
  extraction before the Python extractor is proven in practice
* Deferred: can be introduced as an alternative extractor when a second language
  is needed and if its grammar handling is cleaner than an `ast`-style approach

### Option C — External config-registered extractors (entry-point discovery)

Third-party packages register extractors via `importlib.metadata` entry points
under a `roebuck.extractors` group; the registry discovers them at startup.

* Good, because allows the community to add language support without modifying
  Roebuck
* Bad, because entry-point discovery adds startup complexity and
  version-compatibility concerns
* Bad, because premature before a second extractor exists to validate the protocol
  is stable enough to be a public extension point
* Deferred: can be layered on top of Option A once the Protocol has been proven
  stable across at least two concrete implementations

## More Information

**Design note**: [docs/design/project-profile.md](../design/project-profile.md) —
"Plugin Architecture: Language-Specific Extraction" section contains the full
specification: two-phase capture flow, chunking strategy, `source` field semantics,
`ExtractedInterface` TypedDict, `LanguageExtractor` Protocol, registry design, and
`PythonExtractor` scope.

**Key implementation constraints:**

- `LanguageExtractor` is a structural `Protocol`; extractor classes do not inherit
  from a base class, Pydantic model, or dataclass
- `ExtractedInterface` is a `TypedDict`; it must not inherit from Pydantic
  `BaseModel` (it is not LLM output — ADR-0005 two-tier split applies)
- The registry is a plain dict at this stage; no entry-point discovery
- `PythonExtractor.requires_toolchain = False` (stdlib `ast` only); future
  toolchain-dependent extractors must set `requires_toolchain = True`
- `source: Literal["ast", "claude"]` is added to each stored interface by the
  capture orchestrator, not by the extractor itself — the Protocol is extraction-only
- Phase 2 enrichment is a `ClaudeClient.analyse()` call and must follow ADR-0003's
  JSON schema injection pipeline; the enrichment output model is distinct from
  `ExtractedInterface` (which is TypedDict, not Pydantic)
- Drift comparison skips `source: "claude"` entries unconditionally, regardless of
  the `enable_drift_detection` flag value

**Related ADRs:**

- [ADR-0007](ADR-0007-project-profile-extraction.md) — Project Profile capability;
  this ADR extends it with the extraction plugin mechanism
- [ADR-0003](ADR-0003-llm-output-strategy.md) — JSON schema injection pipeline;
  Phase 2 enrichment follows this
- [ADR-0004](ADR-0004-pydantic-config-and-output.md) — Pydantic for LLM output
  models; Phase 2 enrichment output model follows this
- [ADR-0005](ADR-0005-two-tier-model-pattern.md) — dataclasses for raw data,
  Pydantic for LLM output; `ExtractedInterface` is TypedDict (raw data tier),
  Phase 2 output model is Pydantic (LLM output tier)
