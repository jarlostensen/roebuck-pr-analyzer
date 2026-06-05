# ADR-0001: Use Typer + Rich as the CLI framework

> This ADR was created retrospectively to document an existing decision.

- **Status**: accepted
- **Date**: 2026-03-13 (retrofitted)

## Context

Roebuck is a command-line tool with multiple sub-commands (`analyse pr`, `analyse file`, `analyse release`, `report churn`). A framework is needed to handle argument parsing, help text generation, and terminal output formatting.

## Decision

Use **Typer** for command/argument declaration and **Rich** for styled terminal output (status spinners, coloured messages).

## Considered options

- **argparse** (stdlib) — verbose, no decorator-based API, no built-in Rich integration
- **Click** — mature and flexible, but Typer builds on Click and adds type-annotation-driven argument declaration with less boilerplate
- **Typer + Rich** — concise decorator API, automatic `--help` generation, Rich integration built in

## Consequences

**Pros:**
- Sub-command nesting (`app.add_typer`) maps cleanly to the `analyse` / `report` command groups
- Type annotations drive both argument parsing and help text — no duplication
- Rich `console.status()` provides progress feedback during long API calls at no extra cost

**Cons:**
- Typer is a third-party dependency (though small and stable)
- Lazy analyser imports inside command functions (to keep startup fast) are non-idiomatic and make top-level dependencies invisible
