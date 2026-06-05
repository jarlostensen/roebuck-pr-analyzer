# ADR-0004: Use Pydantic for configuration validation and LLM output schema

> This ADR was created retrospectively to document an existing decision.

- **Status**: accepted
- **Date**: 2026-03-13 (retrofitted)

## Context

The application needs to validate a TOML config file (with defaults, range constraints, and format checks) and to define the expected shape of Claude's JSON responses in a way that can be both injected into prompts and used to validate the parsed output.

## Decision

Use **Pydantic v2** for both configuration models (`AppConfig` and sub-models) and LLM output models (`PRAnalysisResult`, `ChurnAnalysisResult`, etc.).

## Considered options

- **`dataclasses` + manual validation** — no schema generation; would require a separate JSON Schema library for prompt injection
- **`attrs`** — similar capability, but smaller ecosystem and no built-in JSON schema export
- **Pydantic v2** (chosen) — `model_json_schema()` enables direct schema injection into Claude's system prompt; `model_validate_json()` parses and validates the response; `field_validator` handles cross-field constraints cleanly

## Consequences

**Pros:**
- Single library serves both config validation and LLM output schema — no duplication
- `model_json_schema()` produces the JSON Schema injected into the system prompt automatically when new fields are added
- Field constraints (`ge`, `le`, regex) are declarative and self-documenting
- Validation errors include field paths and messages, surfaced directly to the user on bad config

**Cons:**
- Pydantic v2 has a steeper learning curve than plain dataclasses for contributors unfamiliar with it
- LLM output models use string fields with informal enum values (e.g. `risk_level: str` with expected values `"low" | "medium" | "high" | "critical"`) rather than `Literal` types — invalid values from Claude pass validation silently
