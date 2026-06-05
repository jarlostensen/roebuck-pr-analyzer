# ADR-0005: Use dataclasses for raw GitHub data, Pydantic for LLM output

> This ADR was created retrospectively to document an existing decision.

- **Status**: accepted
- **Date**: 2026-03-13 (retrofitted)

## Context

`models.py` defines two distinct kinds of data structures: data fetched from the GitHub API (which does not need validation — it is read-only input) and data produced by Claude (which must be validated against a schema). A decision is needed on how to represent each.

## Decision

Use **Python dataclasses** for raw GitHub data models (`PRData`, `FileHistoryData`, `ChurnEntry`, `ReleaseData`, `FileCommit`) and **Pydantic `BaseModel`** for LLM output models (`PRAnalysisResult`, `FileHistoryResult`, `ChurnAnalysisResult`, `ReleaseAnalysisResult`).

## Considered options

- **Pydantic for everything** — consistent, but validation overhead and `model_json_schema()` export on raw data models is unnecessary and potentially confusing
- **Dataclasses for everything** — lightweight, but LLM output models lose `model_validate_json()` and `model_json_schema()` which are central to the Claude integration strategy (ADR-0003)
- **Split by purpose** (chosen) — dataclasses where validation is not needed; Pydantic where JSON schema generation and validation are required

## Consequences

**Pros:**
- Clear semantic boundary: dataclasses = "data in", Pydantic = "data out of LLM"
- No unnecessary validation overhead on GitHub API responses
- Pydantic schema generation is confined to exactly the models that need it

**Cons:**
- Two model patterns in the same `models.py` file may surprise contributors
- Dataclasses do not enforce types at runtime — a bug in `GitHubClient` mapping could produce incorrect data silently
