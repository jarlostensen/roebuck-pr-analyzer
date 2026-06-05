# HOWTO: Run Roebuck on Every Pull Request with GitHub Actions

This guide shows you how to set up a GitHub Actions workflow that automatically runs
`roebuck analyse pr` on every new or updated pull request and posts the resulting
Markdown report as a PR review comment.

After completing this guide, every pull request to your repository will receive an
automated AI-powered review comment covering spec alignment, risk level, test
adequacy, and recommendations.

---

## Contents

1. [Prerequisites](#1-prerequisites)
2. [Commit a config.toml to your repository](#2-commit-a-configtoml-to-your-repository)
3. [Configure GitHub Actions secrets](#3-configure-github-actions-secrets)
4. [Understand the token and permission model](#4-understand-the-token-and-permission-model)
5. [Create the workflow file](#5-create-the-workflow-file)
6. [How the workflow posts the review comment](#6-how-the-workflow-posts-the-review-comment)
7. [Handling failures](#7-handling-failures)
8. [Scoping which PRs trigger the workflow](#8-scoping-which-prs-trigger-the-workflow)
9. [Cost and rate-limit considerations](#9-cost-and-rate-limit-considerations)
10. [Pip dependency caching](#10-pip-dependency-caching)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

Before starting, confirm you have:

- Access to Roebuck. See section 1a below for the three installation options.
- An Anthropic API key. Obtain one at https://console.anthropic.com/.
- Familiarity with GitHub Actions. You do not need to know anything about Roebuck's
  internals — this guide is self-contained.

### 1a. How Roebuck is installed in the workflow

The workflow runs inside **your target repository** (the one whose pull requests you
want to analyse). Roebuck is a separate tool that must be installed into the workflow
environment. It is not bundled with your project.

The checkout step checks out **your target repo**, not Roebuck. After checkout, the
working directory is your project root — this is where Roebuck looks for `config.toml`
and spec files. Roebuck itself is then installed separately by one of these methods:

**Option A: Install from PyPI (simplest — use this when available)**

```yaml
- name: Install Roebuck
  run: pip install roebuck
```

Roebuck is not yet published to PyPI. This option will work once a package is
published.

**Option B: Install from the Roebuck GitHub repository (recommended today)**

```yaml
- name: Install Roebuck
  run: pip install git+https://github.com/your-org/roebuck.git@main
```

Replace `your-org/roebuck` and the branch or tag reference with the actual location
of the Roebuck source repository. No extra checkout step is needed — pip fetches the
source directly over HTTPS.

If the Roebuck repository is private, the workflow runner must have access. You can
pass the `GITHUB_TOKEN` (or a dedicated PAT with `contents: read` on the Roebuck
repo) via the URL:

```yaml
- name: Install Roebuck
  env:
    ROEBUCK_INSTALL_TOKEN: ${{ secrets.ROEBUCK_INSTALL_TOKEN }}
  run: |
    pip install git+https://${ROEBUCK_INSTALL_TOKEN}@github.com/your-org/roebuck.git@main
```

**Option C: Secondary checkout (use when you need a specific local revision)**

Check out the Roebuck source into a subdirectory of the workspace, then install from
there. The first checkout must be your target repo (at `.`); the Roebuck checkout goes
into a named subdirectory so it does not overwrite your project files.

```yaml
- name: Check out target repository
  uses: actions/checkout@v4
  with:
    fetch-depth: 0
    # No 'path' specified — checks out to the workspace root (.)

- name: Check out Roebuck source
  uses: actions/checkout@v4
  with:
    repository: your-org/roebuck
    ref: main        # branch, tag, or SHA
    path: .roebuck   # subdirectory — does not overwrite your project files

- name: Install Roebuck
  run: pip install ./.roebuck
```

The workflow YAML in section 5 uses **Option B** as the default because it requires
no additional checkout step and works with any publicly accessible Roebuck repository.
Swap in Option A or C if your situation calls for it.

---

## 2. Commit a config.toml to your repository

Roebuck reads its configuration from `config.toml` in the directory where it is
invoked. In a CI environment that directory is the repository root, so you must
commit a `config.toml` there.

**Important:** The standard README warning says "never commit config.toml" because a
locally-used file often contains a real GitHub token in the `[github]` block. For CI
use you commit the file with a placeholder token value — the real token is injected
via environment variable at runtime, which takes precedence.

### What to put in config.toml

Create `config.toml` at the repository root with the following content, substituting
your actual repository name and adjusting the `[specs]` patterns to match where your
project's design documents live:

```toml
# config.toml — committed to the repository root.
# This file is safe to commit because:
#   - The [github] token field is overridden at runtime by the GITHUB_TOKEN
#     environment variable, so the placeholder value here is never used.
#   - ANTHROPIC_API_KEY is never stored in this file.

[github]
# Placeholder value — overridden by the GITHUB_TOKEN secret at runtime.
token = "placeholder"

# REQUIRED: replace with your actual repository in owner/repo-name format.
repo = "your-org/your-repo"

[claude]
model      = "claude-sonnet-4-6"
max_tokens = 4096
temperature = 0.2

[specs]
# Glob patterns (relative to repo root) for your specification and design docs.
# Roebuck loads these files and sends them to Claude as context for PR analysis.
# Adjust to match where your project's documentation lives.
patterns = [
    "docs/specs/**/*.md",
    "docs/adr/*.md",
    "README.md",
]

[churn]
lookback_days         = 90
defect_keywords       = ["fix", "bug", "hotfix", "patch", "regression", "revert"]
min_commits_threshold = 3
max_commits           = 500

[reports]
output_dir = "./reports"

[context]
# Optional: describe your team and project phase so Claude can calibrate findings.
team  = ""   # e.g. "Solo developer", "3-person startup team"
phase = ""   # e.g. "Active development", "Stabilisation"
notes = ""   # e.g. "High defect ratios reflect rapid iteration"
```

### Fields that are safe to commit

| Field | Safe to commit? | Reason |
|---|---|---|
| `[github] token` | Yes, with a placeholder | Overridden by `GITHUB_TOKEN` env var |
| `[github] repo` | Yes | Not sensitive |
| `[claude]` section | Yes | Not sensitive |
| `[specs] patterns` | Yes | Not sensitive |
| `[reports] output_dir` | Yes | Not sensitive |
| `[context]` section | Yes | Not sensitive |
| A real token in `[github] token` | NO | Store in GitHub Secrets instead |

### Recommended [specs] patterns

Choose patterns that match your project's actual documentation structure:

```toml
# For projects with a docs/ tree of design documents:
patterns = ["docs/**/*.md", "README.md"]

# For projects that use Architecture Decision Records:
patterns = ["docs/adr/*.md", "docs/specs/**/*.md", "README.md"]

# For minimal projects with only a README:
patterns = ["README.md"]
```

If no spec files are matched, Roebuck still runs but Claude has no design context
to check alignment against. The report will be less precise but still valid.

---

## 3. Configure GitHub Actions secrets

Two environment variables must reach the Roebuck process at runtime:

| Variable | Purpose | Where it comes from |
|---|---|---|
| `ANTHROPIC_API_KEY` | Authenticates requests to the Anthropic API | GitHub Actions secret you create |
| `GITHUB_TOKEN` | Authenticates GitHub API calls (fetch PR diff, commits) | See section 4 |

### Adding ANTHROPIC_API_KEY as a secret

1. Open your repository on GitHub.
2. Go to **Settings > Secrets and variables > Actions**.
3. Click **New repository secret**.
4. Name: `ANTHROPIC_API_KEY`
5. Value: your Anthropic API key (starts with `sk-ant-`).
6. Click **Add secret**.

Do not store the key anywhere else in the repository. It must only exist as a
GitHub Actions secret.

---

## 4. Understand the token and permission model

This section explains the two token choices so you can pick the right one for your
situation.

### Option A: The built-in GITHUB_TOKEN (recommended for most cases)

GitHub Actions automatically creates a short-lived `GITHUB_TOKEN` for every workflow
run. This token is scoped to the current repository and expires when the run ends.

**When it works:** Your repository's default workflow permissions allow
`pull-requests: write`. This is the default for public repositories and for many
private repositories, but some organisations lock down the default to read-only.

**When it does not work:**
- The organisation has set the default permission to "Read repository contents and
  packages permissions" (read-only).
- The workflow is triggered by a pull request from a fork. Fork-originated PRs
  receive a read-only token and cannot post comments via the built-in token.

To check your repository's default permission setting: go to
**Settings > Actions > General > Workflow permissions**.

The workflow in section 5 includes an explicit `permissions:` block that requests
`pull-requests: write`. This works even when the organisation default is read-only,
as long as you (the repository owner or admin) have not disabled permission
escalation at the organisation level.

### Option B: A Personal Access Token (PAT) stored as a secret

Use a PAT when:
- You need the workflow to analyse PRs from forks (the built-in token cannot post
  to fork PRs).
- Your organisation has disabled the `permissions:` escalation for the built-in
  token.

To create a PAT:
1. Go to GitHub > **Settings > Developer settings > Personal access tokens > Fine-grained tokens**.
2. Click **Generate new token**.
3. Set the resource owner to your organisation or account.
4. Under **Repository access**, select the target repository.
5. Under **Permissions**, grant:
   - **Pull requests**: Read and write
   - **Contents**: Read-only
6. Generate the token and copy it.
7. Store it as a repository secret named `ROEBUCK_GITHUB_TOKEN`.

Then in the workflow (section 5), replace:

```yaml
GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

with:

```yaml
GITHUB_TOKEN: ${{ secrets.ROEBUCK_GITHUB_TOKEN }}
```

Note: When using a PAT for `GITHUB_TOKEN`, the `permissions:` block in the workflow
has no effect on the PAT's actual permissions — those are set when you create the
token.

---

## 5. Create the workflow file

Create the file `.github/workflows/roebuck-pr-review.yml` in your repository with
the content below. Read through the inline comments before committing — several
values may need adjustment for your project layout.

```yaml
# .github/workflows/roebuck-pr-review.yml
#
# Runs Roebuck on every pull request and posts the analysis report as a
# PR review comment. The workflow posts a COMMENT review (not an approval
# or change request) because Roebuck is advisory, not authoritative.

name: Roebuck PR Analysis

on:
  pull_request:
    types: [opened, synchronize, reopened]
    # Optional: only run when files in these paths change.
    # Remove the paths filter to run on every PR regardless of what changed.
    # paths:
    #   - "src/**"
    #   - "tests/**"

# Grant the minimum permissions the workflow needs.
# pull-requests: write — allows posting the review comment.
# contents: read       — allows checking out the repository.
permissions:
  pull-requests: write
  contents: read

jobs:
  roebuck-analysis:
    name: Roebuck PR Analysis
    runs-on: ubuntu-latest

    steps:
      - name: Check out target repository
        # Checks out the repository whose PR is being analysed (your project, not Roebuck).
        # config.toml and spec files in this repo are what Roebuck reads.
        # v4 is current at the time of writing and receives security patches.
        # Check https://github.com/actions/checkout/releases for newer major versions.
        uses: actions/checkout@v4
        with:
          # Fetch full history so Roebuck can access all commit data.
          fetch-depth: 0

      - name: Set up Python 3.11
        # v5 is current at the time of writing and receives security patches.
        # Check https://github.com/actions/setup-python/releases for newer major versions.
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          # Enable pip cache to speed up repeated runs.
          cache: "pip"

      - name: Install Roebuck
        # Installs Roebuck from its own GitHub repository — separate from the
        # target repo checked out above.
        # Replace 'your-org/roebuck' with the actual repository location and
        # '@main' with a specific tag or SHA for reproducible builds.
        # When Roebuck is published to PyPI, replace this with: pip install roebuck
        # For a private Roebuck repo, see section 1a Option B for token handling.
        run: pip install git+https://github.com/your-org/roebuck.git@main

      - name: Create reports directory
        run: mkdir -p reports

      - name: Run Roebuck analysis
        id: roebuck
        # continue-on-error allows the next step (posting a failure comment)
        # to run even when Roebuck exits non-zero. The overall job is still
        # marked as failed by the "Fail job if analysis failed" step below.
        continue-on-error: true
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          # Run the analysis and capture the report file path from stdout.
          REPORT_PATH=$(roebuck analyse pr ${{ github.event.pull_request.number }})
          echo "report_path=${REPORT_PATH}" >> "$GITHUB_OUTPUT"
          echo "Roebuck wrote report to: ${REPORT_PATH}"

      - name: Read report content
        id: report
        if: steps.roebuck.outputs.report_path != ''
        run: |
          REPORT_PATH="${{ steps.roebuck.outputs.report_path }}"
          if [ -f "${REPORT_PATH}" ]; then
            # Use a delimiter to safely handle multi-line content in GITHUB_OUTPUT.
            {
              echo "content<<ROEBUCK_EOF"
              cat "${REPORT_PATH}"
              echo "ROEBUCK_EOF"
            } >> "$GITHUB_OUTPUT"
          else
            echo "content=Roebuck completed but the report file was not found at: ${REPORT_PATH}" >> "$GITHUB_OUTPUT"
          fi

      - name: Post analysis as PR review comment
        if: steps.report.outputs.content != ''
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh pr review ${{ github.event.pull_request.number }} \
            --comment \
            --body "${{ steps.report.outputs.content }}"

      - name: Post failure comment if analysis errored
        if: steps.roebuck.outcome == 'failure' && steps.report.outputs.content == ''
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh pr review ${{ github.event.pull_request.number }} \
            --comment \
            --body "**Roebuck analysis failed.**

          The automated PR analysis did not complete. Check the [workflow run](${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}) for details.

          Common causes:
          - \`ANTHROPIC_API_KEY\` secret is missing or invalid.
          - \`GITHUB_TOKEN\` does not have read access to the repository.
          - \`config.toml\` is missing from the repository root.
          - The Anthropic API is temporarily unavailable."

      - name: Fail job if analysis failed
        if: steps.roebuck.outcome == 'failure'
        run: |
          echo "Roebuck analysis exited with a non-zero status. Failing the workflow."
          exit 1
```

### What each step does

| Step | Purpose |
|---|---|
| Check out repository | Makes the source code and `config.toml` available |
| Set up Python 3.11 | Installs the Python version Roebuck requires |
| Install Roebuck | Installs Roebuck and all its dependencies |
| Create reports directory | Ensures the output directory exists before Roebuck runs |
| Run Roebuck analysis | Runs the analysis; captures the report path from stdout |
| Read report content | Reads the Markdown file into a step output variable |
| Post analysis as PR review comment | Posts the report to the PR using the `gh` CLI |
| Post failure comment if analysis errored | Notifies the PR if Roebuck itself failed |
| Fail job if analysis failed | Marks the workflow run as failed when Roebuck exits non-zero |

---

## 6. How the workflow posts the review comment

The workflow uses the `gh` CLI (pre-installed on all GitHub-hosted runners) to post
a body-only review comment:

```bash
gh pr review <number> --comment --body "<report content>"
```

The `--comment` flag posts a COMMENT review — it does not approve or request changes
on the pull request. This is intentional: Roebuck's analysis is advisory. A human
reviewer retains the authority to approve or reject the PR.

### Why not use the GitHub REST API directly?

The `gh` CLI wraps the `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews`
endpoint and handles authentication, URL construction, and JSON escaping
automatically. Using `gh` directly is simpler and less error-prone than calling
`curl` with a manually-constructed JSON body. If you prefer the raw API, the
equivalent call is:

```bash
curl -X POST \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${GITHUB_REPOSITORY}/pulls/${{ github.event.pull_request.number }}/reviews" \
  -d "{\"body\": \"...\", \"event\": \"COMMENT\"}"
```

Note that embedding multi-line Markdown in a JSON string via `curl` requires careful
escaping. The `gh` CLI handles this automatically.

---

## 7. Handling failures

The workflow uses a deliberate two-phase failure strategy:

1. `continue-on-error: true` on the Roebuck step allows subsequent steps to run even
   when Roebuck exits non-zero. This gives the workflow a chance to post an
   informative failure comment to the PR.

2. A dedicated "Fail job if analysis failed" step at the end checks the outcome and
   calls `exit 1` to mark the overall job as failed. This ensures the PR check
   appears as failed in the GitHub UI, which is the correct signal when the analysis
   did not complete.

### What triggers a non-zero exit from Roebuck

Roebuck exits 1 when:
- `config.toml` is missing or invalid.
- `ANTHROPIC_API_KEY` is not set or the Anthropic API returns an authentication
  error.
- `GITHUB_TOKEN` is not set, invalid, or lacks read access to the repository.
- The GitHub API returns a rate limit error.
- The Anthropic API returns a truncated response (`max_tokens` reached).
- The pull request number does not exist in the configured repository.

### Preventing the workflow from blocking merges

If you do not want a failed Roebuck run to block PR merges, do not configure the
`Roebuck PR Analysis` check as a required status check in your branch protection
rules. The workflow will still run and post its findings (or failure notice), but
it will not block the merge.

To configure required status checks: go to **Settings > Branches > Branch
protection rules** and edit the rule for your default branch.

---

## 8. Scoping which PRs trigger the workflow

By default the workflow runs on every pull request. Depending on your repository's
activity level and your Anthropic API budget, you may want to narrow this.

### Exclude draft PRs

Add `draft: false` to the filter. GitHub Actions does not support this natively as
a filter value, but you can use a conditional at the job level:

```yaml
jobs:
  roebuck-analysis:
    name: Roebuck PR Analysis
    runs-on: ubuntu-latest
    # Skip draft PRs entirely.
    if: github.event.pull_request.draft == false
```

### Run only when specific paths change

Add a `paths` filter to the trigger. The workflow only runs when a PR touches at
least one file matching the pattern:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened]
    paths:
      - "src/**"
      - "tests/**"
      - "docs/**"
```

Use this to avoid running (and paying for) analysis on PRs that only touch
non-code files such as `.github/` configuration or CI scripts.

### Run only on specific branches

Add a `branches` filter to restrict the trigger to PRs targeting your main branch:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened]
    branches:
      - main
      - master
```

### Combine filters

Filters can be combined. The following configuration runs the analysis only on
non-draft PRs targeting `main` that touch source or test files.

Note: `ready_for_review` is included in the `types` list so that a PR opened as
a draft and then converted to ready-for-review also triggers the analysis. Without
this type, converting a draft PR to ready status does not fire a new workflow run.

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    branches:
      - main
    paths:
      - "src/**"
      - "tests/**"

jobs:
  roebuck-analysis:
    if: github.event.pull_request.draft == false
```

---

## 9. Cost and rate-limit considerations

### Anthropic API costs

Each `roebuck analyse pr` call makes one API request to Claude. The cost depends on:

- The size of the PR diff (input tokens).
- The number and size of spec documents matched by `[specs] patterns` (input tokens).
- The `max_tokens` setting in `config.toml` (output token ceiling).

With `model = "claude-sonnet-4-6"` and `max_tokens = 4096`, a typical PR analysis
costs between $0.01 and $0.10 depending on the diff and spec document sizes. Large
diffs or many spec files push costs toward the higher end.

Practical controls:

| Control | How to apply it |
|---|---|
| Narrow `[specs] patterns` | Fewer or smaller spec files reduce input tokens |
| Reduce `max_tokens` | Shorter responses cost less; 2048 is often sufficient |
| Use path filters | Only analyse PRs that touch code (see section 8) |
| Exclude drafts | Skip analysis until the PR is ready for review (see section 8) |

### GitHub API rate limits

Roebuck uses the GitHub REST API to fetch PR diffs and commits. The `GITHUB_TOKEN`
provided by GitHub Actions has a rate limit of 1,000 requests per hour per
repository (for Actions contexts; GitHub Enterprise Cloud raises this to 15,000). For normal PR analysis this limit is not a
concern — a single PR analysis uses well under 50 requests.

The churn analyser (`roebuck report churn`) is the command most likely to hit rate
limits because it fetches data for many commits. That command is not used in this
workflow, so rate limits are not a significant risk here.

Roebuck detects rate limit errors and surfaces a clear message including the reset
time. If this error appears in your workflow logs, the run will fail cleanly with an
explanatory message rather than crashing silently.

---

## 10. Pip dependency caching

The `actions/setup-python` action includes built-in pip caching. The workflow in
section 5 already enables it:

```yaml
- name: Set up Python 3.11
  uses: actions/setup-python@v5
  with:
    python-version: "3.11"
    cache: "pip"
```

This caches the pip download cache between runs. Dependencies are restored from
cache on subsequent runs, reducing install time from 30-60 seconds to a few seconds.

Because Roebuck is installed from a GitHub URL (not from a local `requirements.txt`
or `pyproject.toml`), the cache key is derived from the pip cache directory contents
rather than a dependency file hash. The cache is invalidated automatically when
pip fetches a different version of Roebuck or its transitive dependencies.

If you pin Roebuck to a specific tag (recommended for reproducibility), the cache
remains stable until you update the tag in the workflow file.

---

## 11. Troubleshooting

### "Error: Resource not accessible by integration"

The `GITHUB_TOKEN` does not have `pull-requests: write`. Check that:
- The `permissions:` block is present in the workflow (it is included in section 5).
- Your organisation has not disabled permission escalation for workflow tokens.
  If it has, switch to a PAT (see section 4, Option B).

### "config.toml not found"

The workflow checks out your target repository (not Roebuck's) and runs from its
root. Roebuck looks for `config.toml` in the current working directory, which is your
project root. If `config.toml` is not committed to your project's root, Roebuck
cannot find it. Commit the file as described in section 2.

### "GITHUB_TOKEN environment variable not set" or authentication errors

The `GITHUB_TOKEN` environment variable is set in the workflow's `env:` block on the
Roebuck step. Confirm the step has:

```yaml
env:
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Note the capitalisation: `GITHUB_TOKEN` in both places.

### "ANTHROPIC_API_KEY" not found

Confirm the secret is added to the repository (section 3) and that the secret name
in the workflow matches exactly: `ANTHROPIC_API_KEY`.

### The report is posted but the content looks truncated

Increase `max_tokens` in `config.toml`. The current value may be too low for the
size of the PR diff. 4096 is the recommended starting point; you can increase to
8192 for large PRs. Check your Anthropic API plan for the model's maximum output
token limit.

### The workflow runs but posts no comment

Check that `steps.roebuck.outputs.report_path` is non-empty in the workflow logs.
If Roebuck ran successfully, it prints the report path to stdout and the workflow
captures it. If the output is empty, Roebuck may have written output to stderr
instead of stdout due to an error. Enable verbose logging by checking the full
step output in the Actions run detail page.

### PRs from forks do not receive a comment

Fork-originated PRs receive a read-only `GITHUB_TOKEN`. Switch to a PAT with
`pull-requests: write` permission and store it as a repository secret (section 4,
Option B).
