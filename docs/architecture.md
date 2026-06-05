# Roebuck — Architecture & Design Review

_Generated: 2026-03-12_

---

## Purpose

Roebuck is a CLI tool that applies Claude as an LLM engine to GitHub repository analysis. It surfaces four kinds of insight from a repo's activity:

| Command | What it analyses |
|---|---|
| `roebuck analyse pr <n>` | PR diff vs. project specs — alignment, risk, test gaps |
| `roebuck analyse file <path>` | Commit history of a single file — stability trend, risk areas |
| `roebuck analyse release <tag>` | Changes between two release tags — deployment risk, breaking changes |
| `roebuck report churn` | Whole-repo churn/defect correlation — hotspot files |

All commands produce a timestamped Markdown report in the configured `reports.output_dir`.

---

## Architecture

### Pipeline (all analysers share this pattern)

```
config.toml / ENV
      │
      ▼
  AppConfig (Pydantic)
      │
      ├──▶ GitHubClient (PyGithub)
      │         │
      │         ▼
      │    Raw data model (dataclass)
      │         │
      │    [SpecLoader — PR only]
      │         │
      ├──▶ ClaudeClient
      │         │  system prompt + JSON schema injected
      │         │  user prompt = markdown-formatted data
      │         ▼
      │    Pydantic result model (validated JSON)
      │
      └──▶ MarkdownReportWriter
               │
               ▼
         reports/{slug}-{timestamp}.md
```

### Module map

```
src/roebuck/
├── cli.py              — Typer app; lazy imports analysers
├── config.py           — Pydantic AppConfig + load_config()
├── models.py           — dataclasses (GitHub data) + Pydantic (LLM output)
├── github_client.py    — PyGithub wrapper; all GitHub I/O
├── claude_client.py    — Anthropic client; schema injection + JSON parse
├── spec_loader.py      — Fetches design docs matching glob patterns
├── analysers/          — pr.py, file_history.py, churn.py, release.py
├── prompts/            — Prompt builders, one per analyser
└── reports/markdown.py — MarkdownReportWriter
```

### Data flow: PR analysis (most complex path)

1. `GitHubClient.get_pr()` → reconstructs unified diff from per-file patches
2. `SpecLoader.load_specs()` → fetches matching docs from HEAD tree; trims to 12K chars
3. `build_user_prompt()` → markdown block: metadata + commits + diff (truncated at 24K) + specs
4. `ClaudeClient.analyse()` → injects Pydantic JSON schema into system prompt; parses response
5. `MarkdownReportWriter.write()` → sections from `(heading, content)` tuples

### Claude integration strategy

`ClaudeClient.analyse()` appends the full Pydantic model's `model_json_schema()` to the system prompt and instructs Claude to return only a conforming JSON object. Response is stripped of code fences then validated with `model_validate_json()`. A `ValidationError` is re-raised as `RuntimeError` with raw response context.

This avoids function-calling / tool-use overhead and works with any Claude model, at the cost of being more fragile (see risks below).

---

## Design decisions worth noting

**Lazy analyser imports in CLI.** Each `@app.command` function imports its analyser module inside the function body. This keeps CLI startup fast but is unusual — anyone reading `cli.py` won't see what it depends on from top-level imports.

**dataclass for raw data, Pydantic for LLM output.** Clean separation: GitHub data doesn't need validation, LLM output does. Reasonable, but means two different model patterns in the same `models.py`.

**Diff reconstruction.** `get_pr()` reconstructs a unified diff from PyGithub's per-file patch strings rather than fetching the raw diff directly. This works but loses some unified diff metadata (e.g. hunk context headers may vary).

**Shortest-first spec trimming.** `_trim_specs()` processes smallest spec files first to maximise file count within the 12K budget. This is a reasonable heuristic but may exclude the most important (often large) files like `README.md` unless they happen to be short.

---

## Risks and issues requiring review

### 1. Token budget is not model-aware
**File:** [src/roebuck/prompts/pr.py](../src/roebuck/prompts/pr.py), [src/roebuck/prompts/release.py](../src/roebuck/prompts/release.py)

`MAX_DIFF_CHARS = 24_000` and `MAX_SPEC_CHARS_TOTAL = 12_000` are hardcoded. The actual context window depends on the model configured (`claude-sonnet-4-6` has 200K tokens; `haiku` has 200K too, but older models differ). The 24K char diff + 12K spec + metadata + system prompt is well within current limits but will silently under-utilise large models or could break if someone configures an older/smaller model. The limits should either be documented as intentional conservative caps or derived from the model config.

### 2. Single response content block assumed
**File:** [src/roebuck/claude_client.py](../src/roebuck/claude_client.py), line `text = response.content[0].text.strip()`

`response.content[0]` assumes the first block is always a text block. The Anthropic API can return tool-use blocks or multiple content blocks. If Claude returns something unexpected (e.g. a stop reason of `max_tokens` with a partial tool call), this will raise an `AttributeError` with no useful error message. Should guard: check `response.content[0].type == "text"` and handle `stop_reason == "max_tokens"` explicitly.

### 3. No retry or rate-limit backoff
**File:** [src/roebuck/github_client.py](../src/roebuck/github_client.py)

`RateLimitExceededException` is caught and re-raised as `RuntimeError`. GitHub REST has a 5000 req/hr authenticated limit. The churn analyser iterates commits across all files in a date window — on an active repo this can exhaust the limit silently. Should check `gh.get_rate_limit()` before heavy operations and surface a clear message (ideally with retry-after time) rather than a generic RuntimeError.

### 4. Churn analysis loads entire commit history per file
**File:** [src/roebuck/github_client.py](../src/roebuck/github_client.py) — `get_churn_data()`

The current approach iterates commits in the date window, then for each commit fetches the file list to group by path. On a large active repo (thousands of commits over 90 days), this is O(commits × files) in API calls and will hit rate limits or be very slow. A better strategy: use the GitHub commit search API with `path=` filter per file, or pre-filter via the `since`/`until` commit list endpoint.

### 5. Report filenames collide under rapid invocation
**File:** [src/roebuck/reports/markdown.py](../src/roebuck/reports/markdown.py)

Timestamp format is `%Y%m%d-%H%M%S` — second-level resolution. Running the same command twice within a second (realistic in scripts/CI) will overwrite the previous report silently. Consider adding microseconds or a short random suffix.

### 6. `spec_loader` fetches file content in a loop with no concurrency
**File:** [src/roebuck/spec_loader.py](../src/roebuck/spec_loader.py)

`load_specs()` calls `self._repo.get_contents(item.path)` for each matched file sequentially. On a repo with many matching spec files this is slow. Since PyGithub is synchronous, parallelism would require `ThreadPoolExecutor`, but this is worth noting if spec glob patterns are broad.

### 7. `get_release_diff` falls back silently when no previous tag exists
**File:** [src/roebuck/github_client.py](../src/roebuck/github_client.py) — `_previous_tag()`

If there's only one tag in the repo (first release), `_previous_tag()` presumably raises or returns nothing. The failure mode isn't visible in the code summary — confirm it raises a clear error rather than producing an empty diff or comparing against an invalid ref.

### 8. Temperature fixed at 0.2 with no per-task override
**File:** [src/roebuck/config.py](../src/roebuck/config.py)

Temperature 0.2 is sensible for structured JSON output but is applied uniformly across all analysers. The churn and file history prompts ask for narrative analysis where slightly higher temperature might produce better prose. This is minor but worth a config option (`claude.temperature_narrative`?) if output quality becomes a complaint.

### 9. No integration or end-to-end tests
**File:** [tests/](../tests/)

Only `test_config.py` exists (6 tests). All analyser logic, GitHub client calls, Claude prompt formatting, and report writing are untested. At minimum, the prompt builders and `_strip_code_fences` / report writer should have unit tests. The GitHub and Claude clients need mock-based integration tests to catch regressions in data mapping.

### 10. Credentials in `config.toml` are a git-leak risk
**File:** [config.toml.example](../config.toml.example)

The config file has a `github.token` field. Even though `GITHUB_TOKEN` env takes precedence, a user who copies the example and commits `config.toml` with a real token will leak credentials. `.gitignore` should pre-emptively exclude `config.toml` (not just `config.toml.example`). The README / example should call this out prominently.

---

## Summary

The architecture is clean and the pipeline is easy to follow. The main concerns in priority order:

| Priority | Issue |
|---|---|
| High | No retry/backoff on GitHub rate limits — will fail silently on large repos |
| High | `response.content[0].text` unguarded — fragile against API changes |
| High | No `.gitignore` entry for `config.toml` — credential leak risk |
| Medium | Churn analysis is O(commits) in API calls — scalability problem |
| Medium | No tests beyond config — regressions will be hard to catch |
| Low | Hardcoded token budgets not tied to model config |
| Low | Report filename collision under sub-second invocation |
| Low | Spec trimming may exclude the most important files |
