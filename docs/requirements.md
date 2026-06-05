# Roebuck — Requirements

_Retrofitted: 2026-03-13. Inferred from existing code, tests, and documentation._

---

## Functional Requirements

| ID | Requirement | Basis | Priority |
|---|---|---|---|
| FR-001 | The system shall analyse a GitHub pull request and produce a report covering spec alignment, risk level, test adequacy, and recommendations | README, `analysers/pr.py`, `PRAnalysisResult` | Must |
| FR-002 | The system shall analyse the commit history of a single file and produce a report covering evolution, risk areas, and stability trend | README, `analysers/file_history.py`, `FileHistoryResult` | Must |
| FR-003 | The system shall analyse the diff between two release tags and produce a report covering deployment risk, breaking change indicators, and recommendations | README, `analysers/release.py`, `ReleaseAnalysisResult` | Must |
| FR-004 | The system shall generate a whole-repository churn/defect-correlation report identifying hotspot files, systemic issues, and recommendations | README, `analysers/churn.py`, `ChurnAnalysisResult` | Must |
| FR-005 | The system shall load project specification documents matching configured glob patterns and include them as context in PR analysis | `spec_loader.py`, `prompts/pr.py`, `SpecsConfig` | Must |
| FR-006 | The system shall write all analysis results as timestamped Markdown files to a configured output directory | `reports/markdown.py`, analyser `run()` functions | Must |
| FR-007 | The system shall read configuration from a TOML file, with the GitHub token overridable via the `GITHUB_TOKEN` environment variable | `config.py`, `test_config.py` | Must |
| FR-008 | The system shall accept a `--config` / `-c` flag on all commands to specify a config file path; the default shall be `config.toml` in the current working directory | `cli.py`, README | Must |
| FR-009 | The system shall validate configuration on load and produce a clear error message for missing files or invalid values | `config.py`, `test_config.py` | Must |
| FR-010 | The system shall cap churn analysis to a configurable maximum number of commits to bound GitHub API usage | `ChurnConfig.max_commits`, `github_client.py` | Must |
| FR-011 | The system shall detect a GitHub API rate limit exceeded condition and surface a clear error message including the reset time | `github_client.py`, `test_github_client.py` | Must |
| FR-012 | The churn analyser shall emit a partial report with a warning section when a GitHub rate limit is hit mid-run, rather than aborting with an error | Architecture doc risk #3; user requirement | Should |
| FR-013 | The system shall support additional analyser types beyond the current four as the project evolves | User requirement | Could |

---

## Non-Functional Requirements

| ID | Requirement | Category | Basis | Priority |
|---|---|---|---|---|
| NFR-001 | Credentials shall not be stored in version-controlled files; the GitHub token must be suppliable via environment variable | Security | `config.py` env override, README warning | Must |
| NFR-002 | Report filenames shall be unique to prevent silent overwrites under rapid or scripted invocation | Reliability | `markdown.py` microsecond timestamp, `test_reports.py` | Should |
| NFR-003 | Spec files shall be fetched concurrently to minimise wall-clock time when many files match the configured patterns | Performance | `spec_loader.py` `ThreadPoolExecutor` | Should |
| NFR-004 | Prompts shall be truncated to stay within configured token budgets rather than failing with an oversized-context error | Reliability | `prompts/pr.py` `MAX_DIFF_CHARS` / `MAX_SPEC_CHARS_TOTAL` | Should |
| NFR-005 | The system shall raise a clear, actionable error when the Claude response is cut off due to `max_tokens` being reached | Reliability | `claude_client.py` `stop_reason` check | Should |
| NFR-006 | Claude model, max tokens, and temperature shall be configurable per deployment via `config.toml` | Configurability | `ClaudeConfig` | Should |
| NFR-007 | The analyser pipeline shall be structured so that new analysers can be added without modifying existing modules | Extensibility | Current pipeline pattern; FR-013 | Could |
