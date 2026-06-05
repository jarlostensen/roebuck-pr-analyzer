# Roebuck

GitHub repository analysis CLI powered by Claude. Surfaces spec alignment, risk, file stability, and churn hotspots as timestamped Markdown reports.

## Commands

```
roebuck analyse pr <number>           PR diff vs. project specs — alignment, risk, test gaps
roebuck analyse file <path>           Commit history of a file — stability trend, risk areas
roebuck analyse release <tag>         Changes between release tags — deployment risk, breaking changes
roebuck analyse release <tag> --base  Compare against a specific base tag/ref
roebuck report churn                  Whole-repo churn/defect correlation — hotspot files
```

All commands write a timestamped Markdown report to the configured `reports.output_dir` (default: `./reports`).

## Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- A GitHub Personal Access Token with `repo` read scope

## Installation

Install into a virtual environment before running:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install .               # production
pip install -e ".[dev]"     # development (includes pytest)
```

After installation the `roebuck` entry point is available:

```bash
roebuck --help
```

Without installing, the package can also be run directly from the source tree as long as dependencies are present in the environment:

```bash
python -m roebuck --help
```

## Setup

**1. Set environment variables:**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export GITHUB_TOKEN=ghp_...        # or set in config.toml (see below)
```

**2. Create `config.toml` from the example:**

```bash
cp config.toml.example config.toml
```

Edit `config.toml` with your repository (`owner/repo-name`) and adjust Claude/churn settings as needed.

> **Warning:** Never commit `config.toml` — it may contain your GitHub token.

## Configuration

```toml
[github]
token = "ghp_..."          # overridden by GITHUB_TOKEN env var
repo  = "owner/repo-name"

[claude]
model      = "claude-sonnet-4-6"
max_tokens = 4096
temperature = 0.2

[specs]
# Glob patterns for design/spec docs loaded as PR analysis context
patterns = ["docs/specs/**/*.md", "docs/adr/*.md", "README.md"]

[churn]
lookback_days        = 90
defect_keywords      = ["fix", "bug", "hotfix", "patch", "regression", "revert"]
min_commits_threshold = 3
max_commits          = 500   # bounds GitHub API usage

[reports]
output_dir = "./reports"

[context]
team  = ""    # e.g. "Solo developer", "3-person startup team"
phase = ""    # e.g. "Active development", "Stabilisation", "Maintenance"
notes = ""    # any additional context for interpreting results
```

Use `--config` / `-c` to point at a non-default config file:

```bash
roebuck --config /path/to/other.toml analyse pr 42
```

### Project context

The optional `[context]` section lets you describe your team and development situation so Claude can calibrate its analysis accordingly. Without context, reports are written for a generic codebase — a 75% defect ratio gets flagged as alarming regardless of whether it reflects a solo developer iterating rapidly or a production system with a serious stability problem.

| Field | What to put here |
|---|---|
| `team` | Size and structure of the team — e.g. `"Solo developer"`, `"2 founders"`, `"25-person eng org"` |
| `phase` | Where the project is in its lifecycle — e.g. `"Early/active development"`, `"Stabilisation"`, `"Maintenance mode"` |
| `notes` | Anything else that affects how findings should be read — e.g. `"High defect ratios reflect iterative discovery"`, `"Auth module is intentionally experimental"` |

All fields are optional and can be left blank. When set, the context block appears at the top of every prompt sent to Claude.

Use `--repo` / `-r` to override the configured repository on any command without editing the config file:

```
roebuck analyse pr 42 --repo other-owner/other-repo
roebuck report churn -r other-owner/other-repo
```

## How it works

Each command follows the same pipeline:

1. **GitHubClient** fetches raw data (PR diff, commits, tags, file history)
2. **SpecLoader** (PR only) retrieves matching design docs from the repo tree
3. **ClaudeClient** injects a Pydantic JSON schema into the system prompt and parses the structured response
4. **MarkdownReportWriter** renders the result to `reports/<slug>-<timestamp>.md`

## Development

The dev dependencies (pytest) are installed with:

```bash
pip install -e ".[dev]"
```

Run the test suite from the project root:

```bash
pytest
```

Tests are in `tests/` and cover config loading, prompt builders, the GitHub client (mocked), the Claude client (mocked), and report writing. The package must be installed (`pip install -e ".[dev]"`) before running pytest — the tests import from `roebuck` directly.

## Dependencies

| Package | Purpose |
|---|---|
| `typer` + `rich` | CLI and terminal output |
| `pydantic` | Config validation and LLM output parsing |
| `PyGithub` | GitHub REST API client |
| `anthropic` | Claude API client |
