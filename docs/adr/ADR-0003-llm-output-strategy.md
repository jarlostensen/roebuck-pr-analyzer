# ADR-0003: Use direct messages API with JSON schema injection for structured LLM output

> This ADR was created retrospectively to document an existing decision.

- **Status**: accepted
- **Date**: 2026-03-13 (retrofitted)

## Context

Each analyser needs Claude to return structured, machine-readable output (risk levels, lists of recommendations, etc.) that can be rendered into a Markdown report. A strategy is needed to reliably obtain structured JSON from the Claude API.

## Decision

Use the **Anthropic messages API directly**, injecting the Pydantic model's `model_json_schema()` into the system prompt and instructing Claude to return only a conforming JSON object. Parse the response with `model_validate_json()`.

## Considered options

- **Tool use / function calling** — Claude returns structured output via a tool call; the SDK enforces the schema. More reliable but adds request complexity and requires tool-use-capable models.
- **JSON schema injection into system prompt** (chosen) — append the schema to the system prompt; parse the text response as JSON. Works with any Claude model, no tool-use overhead.
- **Unstructured prose + post-processing** — ask Claude for narrative output and parse it with regex or a second LLM call. Fragile and harder to test.

## Consequences

**Pros:**
- Works with any Claude model, including older or cheaper variants
- No additional SDK complexity; `ClaudeClient.analyse()` is a single, generic method
- Pydantic schema is the single source of truth for both prompt injection and response validation

**Cons:**
- More fragile than tool use: if Claude wraps the JSON in markdown fences or adds explanation text, post-processing (`_strip_code_fences`) is required
- A `ValidationError` on the parsed response produces a `RuntimeError` with limited context — the model may have returned partially valid JSON that is hard to debug
- `response.content[0]` is assumed to be a text block; unexpected content types (tool-use blocks) raise `AttributeError` without this being guarded (now guarded with an explicit type check)
