# ADR-0006: Use TOML for configuration

> This ADR was created retrospectively to document an existing decision.

- **Status**: accepted
- **Date**: 2026-03-13 (retrofitted)

## Context

The application requires user-supplied configuration: GitHub repo, API tokens, Claude model settings, churn analysis parameters, and output directory. A format and loading mechanism is needed.

## Decision

Use **TOML** via Python's stdlib `tomllib` (Python 3.11+). Configuration lives in `config.toml` in the current working directory, with the path overridable via `--config`.

## Considered options

- **Environment variables only** — works well for secrets (token), but awkward for structured settings like `churn.defect_keywords` (a list) or `specs.patterns` (glob list)
- **YAML** — human-friendly for nested config, but requires a third-party library (`PyYAML` or `ruamel.yaml`)
- **JSON** — no comments support; less ergonomic for human-edited config
- **TOML via `tomllib`** (chosen) — stdlib in Python 3.11+, no extra dependency; supports nested tables and arrays naturally; comment support; widely understood

## Consequences

**Pros:**
- No additional dependency — `tomllib` is in the stdlib
- TOML's table syntax maps directly to the nested Pydantic config models
- Users can comment out optional sections; defaults are applied by Pydantic
- `GITHUB_TOKEN` env var override means secrets need not appear in the file

**Cons:**
- `config.toml` may contain the GitHub token if the user opts not to use the env var — credential leak risk if accidentally committed (mitigated by `.gitignore` entry and README warning)
- `--config` defaults to `config.toml` in the current working directory, so the tool must be invoked from the directory containing the config file unless `--config` is specified explicitly
